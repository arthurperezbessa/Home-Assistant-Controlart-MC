"""Constantes da integração ControlArt (módulos cabeados relé e dimmer)."""
from __future__ import annotations

DOMAIN = "controlart"

DEFAULT_PORT = 4998
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300

# --- Chaves do config entry (data) -------------------------------------------
CONF_MAC = "mac"               # string "4B-3B-64" (3 últimos bytes do MAC)
CONF_MAC_BYTES = "mac_bytes"   # [int, int, int]
CONF_MODULE_TYPE = "module_type"
CONF_FIRMWARE = "firmware"

MODULE_RELAY = "relay"
MODULE_DIMMER = "dimmer"

MODEL_NAMES = {
    MODULE_RELAY: "MD-ETH-MCRL2",
    MODULE_DIMMER: "MD-ETH-MCDM2",
}

# --- Chaves de opções ---------------------------------------------------------
OPT_CHANNELS = "channels"            # relé: {str(ch): "lights"|"cover"} ch 0..4
OPT_LIGHT_OUTPUTS = "light_outputs"  # lista de saídas-luz ativas (ints)
OPT_LIGHT_NAMES = "light_names"      # {str(out): nome}
OPT_COVERS = "covers"                # {str(ch): {name, device_class, invert}}
OPT_KEYPADS = "keypads"              # {dev_id: {"type": int, "name": str}}
OPT_EXPOSE_INPUTS = "expose_inputs"  # bool
OPT_SCAN_INTERVAL = "scan_interval"

CHANNEL_ROLE_LIGHTS = "lights"
CHANNEL_ROLE_COVER = "cover"
CHANNEL_ROLES = [CHANNEL_ROLE_LIGHTS, CHANNEL_ROLE_COVER]

# --- Hardware -----------------------------------------------------------------
RELAY_OUTPUT_COUNT = 10
DIMMER_OUTPUT_COUNT = 9
INPUT_COUNT = 12
MOTOR_CHANNEL_COUNT = 5  # canais 0..4; canal CH usa os relés 2*CH e 2*CH+1

# Posição da cortina no módulo: 0..255 (255 = totalmente fechada)
COVER_POS_MAX = 255

# Tipos de keypad da rede CAN Bus -> número de teclas
KEYPAD_KEYS = {1: 3, 2: 4, 3: 6}

# Eventos enviados pelos keypads (campo EVT da string setcankpfb)
KEYPAD_EVT_MAP = {
    0: "click",
    1: "double_click",
    2: "long_click",
    3: "press",
    4: "release",
}
KEYPAD_EVENT_TYPES = list(KEYPAD_EVT_MAP.values())

# Classes de dispositivo disponíveis para cortinas/motores
COVER_DEVICE_CLASSES = [
    "curtain",
    "blind",
    "shade",
    "shutter",
    "awning",
    "gate",
    "garage",
    "door",
    "window",
]
DEFAULT_COVER_DEVICE_CLASS = "curtain"

# Sinal de dispatcher para eventos de keypad
SIGNAL_KEYPAD = f"{DOMAIN}_keypad_event"

PLATFORMS = ["light", "cover", "event", "binary_sensor"]
