"""Config flow e Options flow da integração ControlArt."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CHANNEL_ROLE_COVER,
    CHANNEL_ROLE_LIGHTS,
    CHANNEL_ROLES,
    CONF_FIRMWARE,
    CONF_MAC,
    CONF_MAC_BYTES,
    CONF_MODULE_TYPE,
    COVER_DEVICE_CLASSES,
    DEFAULT_COVER_DEVICE_CLASS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DIMMER_OUTPUT_COUNT,
    DOMAIN,
    KEYPAD_KEYS,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MODEL_NAMES,
    MODULE_DIMMER,
    MODULE_RELAY,
    MOTOR_CHANNEL_COUNT,
    OPT_CHANNELS,
    OPT_COVERS,
    OPT_EXPOSE_INPUTS,
    OPT_KEYPADS,
    OPT_LIGHT_NAMES,
    OPT_LIGHT_OUTPUTS,
    OPT_SCAN_INTERVAL,
    RELAY_OUTPUT_COUNT,
)
from .helpers import eligible_light_outputs
from .protocol import ControlArtProtocol

_LOGGER = logging.getLogger(__name__)


def _format_firmware(raw: str) -> str | None:
    """Converte '3027' em '3.027'."""
    raw = raw.strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return f"{value // 1000}.{value % 1000:03d}"


async def _probe_module(host: str, port: int) -> dict[str, Any]:
    """Conecta ao módulo e identifica MAC, firmware e tipo (relé/dimmer)."""
    protocol = ControlArtProtocol(host, port)
    await protocol.async_start()
    try:
        mac_line = await protocol.async_query(
            "get_mac_addr", lambda line: line.startswith("macaddr_RT"), timeout=5
        )
        # macaddr_RT,33-79-F4
        hex_part = mac_line.split(",", 1)[1].strip()
        mac_bytes = [int(x, 16) for x in hex_part.split("-")]
        if len(mac_bytes) != 3:
            raise ValueError("MAC inesperado")

        firmware: str | None = None
        try:
            fw_line = await protocol.async_query(
                "get_firmware_version",
                lambda line: line.strip().isdigit(),
                timeout=5,
            )
            firmware = _format_firmware(fw_line)
        except asyncio.TimeoutError:
            _LOGGER.debug("Firmware não retornado por %s", host)

        dec_mac = ",".join(str(b) for b in mac_bytes)
        status = await protocol.async_query(
            f"mdcmd_getmd,{dec_mac}",
            lambda line: line.startswith(("setcmd", "setdmmd")),
            timeout=5,
        )
        module_type = (
            MODULE_RELAY if status.startswith("setcmd") else MODULE_DIMMER
        )
        return {
            CONF_MAC: hex_part.upper(),
            CONF_MAC_BYTES: mac_bytes,
            CONF_FIRMWARE: firmware,
            CONF_MODULE_TYPE: module_type,
        }
    finally:
        await protocol.async_stop()


class ControlArtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Assistente de configuração inicial (um por módulo)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            try:
                info = await _probe_module(host, port)
            except (ConnectionError, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            except (ValueError, IndexError):
                errors["base"] = "unexpected_response"
            else:
                await self.async_set_unique_id(info[CONF_MAC])
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port}
                )
                model = MODEL_NAMES[info[CONF_MODULE_TYPE]]
                title = f"ControlArt {model} ({info[CONF_MAC]})"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        **info,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                        int, vol.Range(min=1, max=65535)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ControlArtOptionsFlow()


class ControlArtOptionsFlow(OptionsFlow):
    """Tela de opções: saídas, cortinas, teclados e geral."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    @property
    def _module_type(self) -> str:
        return self.config_entry.data[CONF_MODULE_TYPE]

    def _current(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._module_type == MODULE_RELAY:
            menu = ["channels", "lights", "covers", "keypads", "general"]
        else:
            menu = ["lights", "keypads", "general"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    # --------------------------------------------------- canais (só relé)
    async def async_step_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Define o papel de cada par de canais 0..4: luzes ou cortina."""
        current = self._current()
        channels: dict[str, str] = current.get(OPT_CHANNELS, {})

        if user_input is not None:
            new_channels = {
                str(ch): user_input[f"channel_{ch}"]
                for ch in range(MOTOR_CHANNEL_COUNT)
            }
            options = {**current, OPT_CHANNELS: new_channels}
            return self.async_create_entry(title="", data=options)

        schema: dict[Any, Any] = {}
        for ch in range(MOTOR_CHANNEL_COUNT):
            default = channels.get(str(ch), CHANNEL_ROLE_LIGHTS)
            schema[vol.Required(f"channel_{ch}", default=default)] = vol.In(
                CHANNEL_ROLES
            )
        return self.async_show_form(
            step_id="channels", data_schema=vol.Schema(schema)
        )

    # ------------------------------------------------------- luzes (nomes)
    async def async_step_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Seleciona quais saídas de luz expor e dá nomes amigáveis."""
        current = self._current()
        channels: dict[str, str] = current.get(OPT_CHANNELS, {})
        eligible = eligible_light_outputs(self._module_type, channels)
        current_names: dict[str, str] = current.get(OPT_LIGHT_NAMES, {})
        active = current.get(OPT_LIGHT_OUTPUTS, eligible)

        if user_input is not None:
            selected = sorted(int(o) for o in user_input.get("outputs", []))
            names = {}
            for out in selected:
                value = (user_input.get(f"name_{out}") or "").strip()
                if value:
                    names[str(out)] = value
            options = {
                **current,
                OPT_LIGHT_OUTPUTS: selected,
                OPT_LIGHT_NAMES: names,
            }
            return self.async_create_entry(title="", data=options)

        labels = {out: f"Saída {out + 1}" for out in eligible}
        schema: dict[Any, Any] = {
            vol.Optional(
                "outputs", default=[o for o in active if o in eligible]
            ): cv.multi_select(labels)
        }
        for out in eligible:
            schema[
                vol.Optional(
                    f"name_{out}",
                    description={"suggested_value": current_names.get(str(out), "")},
                )
            ] = str
        return self.async_show_form(
            step_id="lights", data_schema=vol.Schema(schema)
        )

    # ----------------------------------------------------- cortinas/motores
    async def async_step_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configura nome, classe e inversão de cada canal-cortina."""
        current = self._current()
        channels: dict[str, str] = current.get(OPT_CHANNELS, {})
        cover_channels = [
            ch
            for ch in range(MOTOR_CHANNEL_COUNT)
            if channels.get(str(ch)) == CHANNEL_ROLE_COVER
        ]
        if not cover_channels:
            return self.async_abort(reason="no_covers")

        covers: dict[str, Any] = current.get(OPT_COVERS, {})

        if user_input is not None:
            new_covers = {}
            for ch in cover_channels:
                new_covers[str(ch)] = {
                    "name": (user_input.get(f"name_{ch}") or "").strip(),
                    "device_class": user_input[f"class_{ch}"],
                    "invert": user_input[f"invert_{ch}"],
                }
            options = {**current, OPT_COVERS: new_covers}
            return self.async_create_entry(title="", data=options)

        schema: dict[Any, Any] = {}
        for ch in cover_channels:
            conf = covers.get(str(ch), {})
            schema[
                vol.Optional(
                    f"name_{ch}",
                    description={"suggested_value": conf.get("name", "")},
                )
            ] = str
            schema[
                vol.Required(
                    f"class_{ch}",
                    default=conf.get("device_class", DEFAULT_COVER_DEVICE_CLASS),
                )
            ] = vol.In(COVER_DEVICE_CLASSES)
            schema[
                vol.Required(f"invert_{ch}", default=conf.get("invert", False))
            ] = bool
        return self.async_show_form(
            step_id="covers", data_schema=vol.Schema(schema)
        )

    # ----------------------------------------------------------- teclados
    async def async_step_keypads(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Faz SCAN da rede CAN Bus e gerencia os keypads expostos."""
        current = self._current()
        configured: dict[str, Any] = current.get(OPT_KEYPADS, {})

        if user_input is not None:
            selected = user_input.get("keypads", [])
            keypads = {}
            for dev_id in selected:
                name = (user_input.get(f"name_{dev_id}") or "").strip()
                keypads[dev_id] = {
                    "type": int(user_input[f"type_{dev_id}"]),
                    "name": name,
                }
            options = {**current, OPT_KEYPADS: keypads}
            return self.async_create_entry(title="", data=options)

        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        try:
            found = await coordinator.async_scan_keypads()
        except Exception:  # noqa: BLE001
            found = {}

        # Mescla os keypads encontrados com os já configurados.
        known: dict[str, int] = {
            dev: conf.get("type", 2) for dev, conf in configured.items()
        }
        known.update(found)

        if not known:
            return self.async_abort(reason="no_keypads")

        labels = {}
        for dev_id, typ in sorted(known.items()):
            keys = KEYPAD_KEYS.get(typ, 4)
            online = " (online)" if dev_id in found else ""
            labels[dev_id] = f"{dev_id} — {keys} teclas{online}"

        schema: dict[Any, Any] = {
            vol.Optional(
                "keypads", default=list(configured.keys())
            ): cv.multi_select(labels)
        }
        for dev_id, typ in sorted(known.items()):
            conf = configured.get(dev_id, {})
            schema[
                vol.Optional(
                    f"name_{dev_id}",
                    description={"suggested_value": conf.get("name", "")},
                )
            ] = str
            schema[vol.Required(f"type_{dev_id}", default=typ)] = vol.In(
                list(KEYPAD_KEYS)
            )
        return self.async_show_form(
            step_id="keypads", data_schema=vol.Schema(schema)
        )

    # -------------------------------------------------------------- geral
    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = self._current()
        if user_input is not None:
            options = {
                **current,
                OPT_EXPOSE_INPUTS: user_input[OPT_EXPOSE_INPUTS],
                OPT_SCAN_INTERVAL: user_input[OPT_SCAN_INTERVAL],
            }
            return self.async_create_entry(title="", data=options)

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_EXPOSE_INPUTS,
                    default=current.get(OPT_EXPOSE_INPUTS, False),
                ): bool,
                vol.Required(
                    OPT_SCAN_INTERVAL,
                    default=current.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)
