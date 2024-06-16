#!/usr/bin/env python3
import itertools
import json
import os
import platform
import shutil
import signal
import time
import threading
import queue
import typing
import uuid
from json import JSONDecodeError
from os.path import isfile
from subprocess import Popen
from dataclasses import dataclass, field

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
disabled = threading.Event()
audioQueue = queue.PriorityQueue()

audioTaskCounter = itertools.count()


@dataclass(order=True)
class AudioTask:
    priority: int
    taskNum: int
    cmds: typing.Any = field(compare=False)


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
        data = json.loads(msg.payload.decode('utf-8'))
        assert "tasks" in data
    except (JSONDecodeError, AssertionError):
        logger.warning("Error decoding command")
        return

    if "priority" in data:
        priority = data["priority"]
    else:
        priority = 50

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

    audio_tasks = []
    for task in data["tasks"]:
        logger.info(f"Received command: {task['cmd']}")
        if task['cmd'].lower() not in ["sleep", "sound", "tts"]:
            logger.warning("Unknown command!")
            return

        # if task['cmd'].lower() == "stop":
        #     stopCurrent.set()
        #
        # elif task['cmd'].lower() == "stopall":
        #     with audioQueue.mutex:
        #         audioQueue.queue.clear()
        #         audioQueue.all_tasks_done.notify_all()
        #         audioQueue.unfinished_tasks = 0
        #     stopCurrent.set()

        elif task['cmd'].lower() == "sleep":
            if "data" not in task or not str(task['data']).isnumeric():
                logger.warning("Error decoding data")
                return
            audio_tasks.append(("sleep", task['data']))

        else:
            if "data" not in task:
                logger.warning("Error decoding data")
                return

            filename = f"{uuid.uuid4()}"
            logger.debug(f"Filename: {filename}")
            if data['cmd'].lower() == "sound":
                if not isfile(os.path.join(config[CONF_AUDIO_SOUNDS_PATH], f'{data["data"]}.wav')):
                    logger.warning("File does not exist")
                    return
                thread = threading.Thread(target=sound_worker, args=[filename, data['data'], gain])
                thread.start()
                audio_tasks.append(("file", (thread, filename)))

            else:
                if "data" not in data:
                    logger.warning("Error decoding data")
                    return
                thread = threading.Thread(target=tts_worker, args=[filename, data['data'], gain])
                thread.start()
                audio_tasks.append(("file", (thread, filename)))
    try:
        audioQueue.put_nowait(AudioTask(priority, next(audioTaskCounter), audio_tasks))
    except queue.Full:
        logger.critical("Audio queue is full")
        return


def sound_worker(filename, sound, gain):
    config = Config()
    shutil.copyfile(os.path.join(config[CONF_AUDIO_SOUNDS_PATH], f'{sound}.wav'),
                    os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))

    gain(filename, gain)


def tts_worker(filename, text, gain):
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
    gain(filename, gain)


def gain(filename, gain):
    if gain != [0, 0]:
        config = Config()
        logger.debug(f"Modifying gain to {gain}")
        sound = AudioSegment.from_wav(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
        sound = sound.apply_gain_stereo(*gain)
        sound.export(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'), format="wav")


def audio_worker():
    config = Config()

    while not stopProgram.is_set():
        while disabled.is_set():
            time.sleep(0.1)
        try:
            data = audioQueue.get_nowait()
            for cmd in data.cmds:
                logger.debug(f"Running command: {cmd[0]}")
                if cmd[0] == "sleep":
                    logger.debug(f"Sleeping for {cmd[1]} seconds")
                    time.sleep(cmd[1])
                    continue

                elif cmd[0] in ["sound", "tts"]:
                    t = cmd[1][0]
                    filename = cmd[1][1]
                    if t.is_alive():
                        t.join(5)
                        if t.is_alive():
                            logger.warning("Thread runs too long, skipping")
                            continue
                    logger.info(f"Playing {os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav')}")
                    if not config[CONF_AUDIO_DISABLE]:
                        args = ['/usr/bin/paplay', '-p', '-d', config[CONF_AUDIO_DEVICE],
                                os.path.abspath(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))]
                        p = Popen(args)
                        while p.poll() is None:
                            if stopProgram.is_set() or stopCurrent.is_set():
                                p.terminate()
                                break
                            time.sleep(0.1)
                    else:
                        sound = AudioSegment.from_wav(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
                        logger.warning(
                            f"Skipping playback as requested by config. Waiting for {len(sound) / 1000} seconds.")
                        time.sleep(len(sound) / 1000)

                    logger.debug("Playback complete.")
                    if not config[CONF_AUDIO_KEEP_FILE]:
                        logger.debug("Deleting audio file.")
                        os.remove(os.path.join(config[CONF_AUDIO_TEMP_PATH], f'{filename}.wav'))
                else:
                    logger.critical("Unknown command")
                stopCurrent.clear()
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
