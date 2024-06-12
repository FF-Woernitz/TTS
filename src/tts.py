#!/usr/bin/env python3
import json
import os
import platform
import shutil
import signal
import time
import threading
import queue
import uuid
from json import JSONDecodeError
from os.path import isfile
from subprocess import Popen


import paho.mqtt.client as mqtt
from gtts import gTTS
from pydub import AudioSegment

from .config import Config
from .consts import *

logging.basicConfig(format=LOG_FORMAT)
logger = logging.getLogger(__name__)

connected = threading.Event()
stopProgram = threading.Event()
stopCurrent = threading.Event()
audioQueue = queue.Queue()


def signalhandler(signum):
    logger.info("Signal handler called with signal {}".format(signum))

    stopProgram.set()
    stopCurrent.set()
    logger.warning("exiting...")
    exit(0)


def on_connect(client, data_object, flags, result):  # pylint: disable=W0613,R0913
    """Callback on connection to MQTT server."""
    config = Config()
    client.subscribe(MQTT_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]))
    client.publish(
        MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]), MQTT_AVAILABLE, retain=True
    )
    data_object["connected"].set()
    logger.info("Connected to MQTT")


def on_message(mqtt_client, data_object, msg):
    """Default callback on MQTT message."""
    logger.error("Unknown MQTT topic: %s", msg.topic)


def on_message_cmd(mqtt_client, data_object, msg):
    config = Config()
    logger.debug(msg.payload.decode('utf-8'))
    try:
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            assert "cmd" in data
        except (JSONDecodeError, AssertionError):
            logger.warning("Error decoding command")
            return
        logger.info(f"Received command: {data['cmd']}")
        if data['cmd'].lower() not in ["stop", "stopall", "sleep", "sound", "tts"]:
            logger.warning("Unknown command!")
            return

        if data['cmd'].lower() == "stop":
            stopCurrent.set()

        elif data['cmd'].lower() == "stopall":
            with audioQueue.mutex:
                audioQueue.queue.clear()
                audioQueue.all_tasks_done.notify_all()
                audioQueue.unfinished_tasks = 0
            stopCurrent.set()

        elif data['cmd'].lower() == "sleep":
            if "data" not in data or not str(data['data']).isnumeric():
                logger.warning("Error decoding data")
                return
            audioQueue.put(("sleep", data['data'], None), False)

        elif data['cmd'].lower() in ["sound", "tts"]:
            if "data" not in data:
                logger.warning("Error decoding data")
                return

            if "gain" in data and "channel" in data:
                logger.warning("gain and channel are mutually exclusive")
                return
            elif "gain" in data and len(data["gain"]) == 2:
                gain = data["gain"]
            elif "channel" in data:
                if data['channel'].lower() == "left":
                    gain = [0, -100]
                elif data["channel"].lower() == "right":
                    gain = [-100, 0]
                else:
                    gain = [0, 0]
            else:
                gain = [0, 0]

            filename = f"{uuid.uuid4()}"
            logger.debug(f"Filename: {filename}")
            if data['cmd'].lower() == "sound":
                if not isfile(os.path.join(config[CONF_AUDIO_SOUNDS_PATH], f'{data["data"]}.wav')):
                    logger.warning("File does not exist")
                    return
                shutil.copyfile(os.path.join(config[CONF_AUDIO_SOUNDS_PATH], f'{data["data"]}.wav'), os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
                audioQueue.put(("sound", filename, gain), False)

            else:
                if "data" not in data:
                    logger.warning("Error decoding data")
                    return
                thread = threading.Thread(target=tts_worker, args=[filename, data['data']])
                thread.start()
                audioQueue.put(("tts", (thread, filename), gain), False)

        logger.debug(f"Command {data['cmd']} completed")

    except queue.Full:
        logger.critical("Audio queue is full")
        return


def tts_worker(filename, text):
    config = Config()
    logger.debug("Requesting TTS from Google")
    tts = gTTS(text, lang=config[CONF_TTS_LANG], tld=config[CONF_TTS_TLD], slow=config[CONF_TTS_SLOW])
    tts.save(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.mp3'))

    sound = AudioSegment.from_mp3(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.mp3'))
    sound = sound.set_frame_rate(48000)
    sound.export(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'), format="wav")

    if not config[CONF_AUDIO_KEEP_FILE]:
        logger.debug("Deleting tts mp3 file")
        os.remove(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.mp3'))

    logger.debug("Requesting TTS from Google completed")


def audio_worker():
    config = Config()

    while not stopProgram.is_set():
        try:
            data = audioQueue.get_nowait()
            cmd = data[0]
            logger.debug("Running command: %s", cmd)
            if cmd == "sleep":
                logger.debug(f"Sleeping for {data[1]} seconds")
                time.sleep(data[1])
                continue

            elif cmd in ["sound", "tts"]:
                if cmd == "tts":
                    t = data[1][0]
                    filename = data[1][1]
                    if t.is_alive():
                        t.join(5)
                        if t.is_alive():
                            logger.warning("TTS thread runs too long, skipping")
                            continue
                else:
                    filename = data[1]

                # Modify gain?
                if data[2] != [0, 0]:
                    logger.debug(f"Modifying gain to {data[2]}")
                    sound = AudioSegment.from_wav(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
                    sound = sound.apply_gain_stereo(*data[2])
                    sound.export(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}_edit.wav'), format="wav")
                    os.remove(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
                    filename += "_edit"

                logger.info(f"Playing {os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav')}")
                if not config[CONF_AUDIO_DISABLE]:
                    args = ['/usr/bin/paplay', '-p', '-d', config[CONF_AUDIO_DEVICE], os.path.abspath(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))]
                    p = Popen(args)
                    while p.poll() is None:
                        if stopProgram.is_set() or stopCurrent.is_set():
                            p.terminate()
                            continue
                        time.sleep(0.1)
                else:
                    sound = AudioSegment.from_wav(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
                    logger.warning(f"Skipping playback as requested by config. Waiting for {len(sound) / 1000} seconds.")
                    time.sleep(len(sound) / 1000)

                logger.debug("Playback complete.")
                if not config[CONF_AUDIO_KEEP_FILE]:
                    logger.debug("Deleting audio file.")
                    os.remove(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))

            else:
                logger.critical("Unknown command")
        except queue.Empty:
            time.sleep(1)
        except KeyboardInterrupt as e:
            signalhandler("KeyboardInterrupt")
            raise e
        except BaseException:
            logger.exception("Exception in audio thread")


def create_mqtt_client():
    """Create MQTT client object, setup callbacks and connection to server."""

    config = Config()
    logger.debug("Connecting to %s:%s", config[CONF_MQTT_SERVER], config[CONF_MQTT_PORT])
    mqttc = mqtt.Client(
        userdata={
            "audioQueue": audioQueue,
            "connected": connected
        },
    )
    if config[CONF_MQTT_TLS]:
        mqttc.tls_set()

    mqttc.will_set(
        MQTT_STATUS.format(config[CONF_MQTT_BASE_TOPIC]), MQTT_NOT_AVAILABLE, retain=True
    )
    mqttc.on_connect = on_connect

    # Add message callbacks that will only trigger on a specific subscription match.
    mqttc.message_callback_add(
        MQTT_COMMAND_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]), on_message_cmd
    )

    mqttc.on_message = on_message

    if config[CONF_MQTT_USERNAME] != '':
        mqttc.username_pw_set(config[CONF_MQTT_USERNAME], config[CONF_MQTT_PASSWORD])

    mqttc.connect(config[CONF_MQTT_SERVER], config[CONF_MQTT_PORT])
    return mqttc


def main(args):
    config = Config()
    config.setup(args)

    if config[CONF_LOG_COLOR]:
        logging.addLevelName(
            logging.WARNING,
            "{}{}".format(YELLOW_COLOR, logging.getLevelName(logging.WARNING)),
        )
        logging.addLevelName(
            logging.ERROR, "{}{}".format(RED_COLOR, logging.getLevelName(logging.ERROR))
        )
    logger.setLevel(ALL_SUPPORTED_LOG_LEVELS[config[CONF_LOG_LEVEL]])

    mqttc = create_mqtt_client()

    threading.Thread(target=audio_worker).start()

    signal.signal(signal.SIGTERM, signalhandler)
    if platform.system() == 'Linux':
        signal.signal(signal.SIGHUP, signalhandler)

    logger.info("Starting mqtt client...")
    mqttc.loop_start()
    while not connected.is_set():
        logger.info("Waiting for connect")
        time.sleep(1)

    try:
        while not stopProgram.is_set():
            if config[CONF_MQTT_HEARTBEAT]:
                mqttc.publish(MQTT_HEARTBEAT_TOPIC.format(config[CONF_MQTT_BASE_TOPIC]), str(int(time.time())))
            time.sleep(30)
    except KeyboardInterrupt:
        signalhandler("KeyboardInterrupt")
