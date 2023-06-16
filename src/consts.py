import logging
import voluptuous as vol
from voluptuous import Any

"""Constants common the various modules."""
AUTHOR = "TobsA"
VERSION = "1.1.1"

CONF_CONFIG = "config"
CONF_CONFIG_EXAMPLE = "config_example"
CONF_MQTT_SERVER = "mqtt_server"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"
CONF_MQTT_HEARTBEAT = "mqtt_heartbeat"
CONF_MQTT_TLS = "mqtt_tls"
CONF_AUDIO_DISABLE = "audio_disable"
CONF_AUDIO_DEVICE = "audio_device"
CONF_AUDIO_SOUNDS_PATH = "audio_sounds_path"
CONF_AUDIO_TEMP_PATH = "audio_temp_path"
CONF_AUDIO_KEEP_FILE = "audio_keep_file"
CONF_TTS_LANG = "tts_lang"
CONF_TTS_TLD = "tts_tld"
CONF_TTS_SLOW = "tts_slow"
CONF_LOG_LEVEL = "log_level"
CONF_LOG_COLOR = "log_color"

DEFAULT_CONFIG_FILE = "config.yaml"
DEFAULT_MQTT_SERVER = "127.0.0.1"
DEFAULT_MQTT_PORT = "1883"
DEFAULT_MQTT_USERNAME = ""
DEFAULT_MQTT_PASSWORD = ""
DEFAULT_MQTT_BASE_TOPIC = "tts"
DEFAULT_MQTT_HEARTBEAT = True
DEFAULT_MQTT_TLS = False
DEFAULT_AUDIO_DISABLE = False
DEFAULT_AUDIO_DEVICE = None
DEFAULT_AUDIO_SOUNDS_PATH = "/app/sounds"
DEFAULT_AUDIO_TEMP_PATH = "/tmp"
DEFAULT_AUDIO_KEEP_FILE = False
DEFAULT_TTS_LANG = "de"
DEFAULT_TTS_TLD = "de"
DEFAULT_TTS_SLOW = False
DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOG_COLOR = False

ALL_SUPPORTED_LOG_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

RESET_COLOR = "\x1b[0m"
RED_COLOR = "\x1b[31;21m"
YELLOW_COLOR = "\x1b[33;21m"
LOG_FORMAT = "%(asctime)s %(levelname)s: %(message)s{}".format(RESET_COLOR)

CONF_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MQTT_SERVER, default=DEFAULT_MQTT_SERVER): str,
        vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_MQTT_USERNAME, default=DEFAULT_MQTT_USERNAME): str,
        vol.Optional(CONF_MQTT_PASSWORD, default=DEFAULT_MQTT_PASSWORD): str,
        vol.Optional(CONF_MQTT_BASE_TOPIC, default=DEFAULT_MQTT_BASE_TOPIC): str,
        vol.Optional(CONF_MQTT_HEARTBEAT, default=DEFAULT_MQTT_HEARTBEAT): bool,
        vol.Optional(CONF_MQTT_TLS, default=DEFAULT_MQTT_TLS): bool,

        vol.Required(CONF_AUDIO_DISABLE, default=DEFAULT_AUDIO_DISABLE): bool,
        vol.Required(CONF_AUDIO_DEVICE, default=DEFAULT_AUDIO_DEVICE): Any(None, str),
        vol.Required(CONF_AUDIO_SOUNDS_PATH, default=DEFAULT_AUDIO_SOUNDS_PATH): str,
        vol.Required(CONF_AUDIO_TEMP_PATH, default=DEFAULT_AUDIO_TEMP_PATH): str,
        vol.Required(CONF_AUDIO_KEEP_FILE, default=DEFAULT_AUDIO_KEEP_FILE): bool,

        vol.Optional(CONF_TTS_LANG, default=DEFAULT_TTS_LANG): str,
        vol.Optional(CONF_TTS_TLD, default=DEFAULT_TTS_TLD): str,
        vol.Optional(CONF_TTS_SLOW, default=DEFAULT_TTS_SLOW): bool,
        vol.Optional(CONF_LOG_LEVEL, default=DEFAULT_LOG_LEVEL): vol.In(
            ALL_SUPPORTED_LOG_LEVELS
        ),
        vol.Optional(CONF_LOG_COLOR, default=DEFAULT_LOG_COLOR): bool,
    },
    extra=False,
)

MQTT_STATUS = "{}/status"
MQTT_COMMAND_TOPIC = "{}/cmd"
MQTT_HEARTBEAT_TOPIC = "{}/heartbeat"
MQTT_AVAILABLE = "online"
MQTT_NOT_AVAILABLE = "offline"


class SetupError(Exception):
    pass
