"""Plataforma cover: canais-motor do módulo relé (cortina/persiana/portão).

O módulo expressa a posição como 0..255, onde 255 é a cortina totalmente
fechada. O Home Assistant usa 0..100 com 0 = fechada. Sem inversão a
conversão também troca o sentido (255 -> 0). A opção "invert" desfaz essa
troca por software, sem mexer na calibração do módulo.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MAC,
    COVER_DEVICE_CLASSES,
    COVER_POS_MAX,
    DEFAULT_COVER_DEVICE_CLASS,
    DOMAIN,
    OPT_CHANNELS,
    OPT_COVERS,
)
from .coordinator import ControlArtCoordinator, MotorState
from .helpers import cover_channels, module_device_info

_LOGGER = logging.getLogger(__name__)

SERVICE_CALIBRATE = "calibrate"
SERVICE_SET_MOTOR_MODE = "set_motor_mode"

_CALIBRATE_ACTIONS = ["start_up", "stop_up", "start_down", "stop_down", "reset"]
_MOTOR_MODES = {"normal": 0, "no_feedback": 1}

# Direções aceitas pelo comando mdcmd_sendcmd (FUNC=2 / Forçar).
_DIR_UP = 0
_DIR_STOP = 1
_DIR_DOWN = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria as entidades de cortina a partir das opções."""
    coordinator: ControlArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    channels: dict[str, str] = entry.options.get(OPT_CHANNELS, {})
    covers_conf: dict[str, Any] = entry.options.get(OPT_COVERS, {})

    entities: list[CoverEntity] = []
    for ch in cover_channels(channels):
        conf = covers_conf.get(str(ch), {})
        entities.append(ControlArtCover(coordinator, entry, ch, conf))
    async_add_entities(entities)

    if entities:
        platform = entity_platform.async_get_current_platform()
        platform.async_register_entity_service(
            SERVICE_CALIBRATE,
            {vol.Required("action"): vol.In(_CALIBRATE_ACTIONS)},
            "async_calibrate",
        )
        platform.async_register_entity_service(
            SERVICE_SET_MOTOR_MODE,
            {vol.Required("mode"): vol.In(list(_MOTOR_MODES))},
            "async_set_motor_mode",
        )


class ControlArtCover(CoordinatorEntity[ControlArtCoordinator], CoverEntity):
    """Canal-motor de um módulo relé exposto como cover."""

    _attr_has_entity_name = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        coordinator: ControlArtCoordinator,
        entry: ConfigEntry,
        channel: int,
        conf: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._invert: bool = bool(conf.get("invert", False))

        name = (conf.get("name") or "").strip() or f"Cortina {channel + 1}"
        self._attr_name = name

        mac = entry.data[CONF_MAC]
        self._attr_unique_id = f"{mac}_cover_{channel}"
        self._attr_device_info = module_device_info(entry)

        device_class = conf.get("device_class", DEFAULT_COVER_DEVICE_CLASS)
        if device_class in COVER_DEVICE_CLASSES:
            try:
                self._attr_device_class = CoverDeviceClass(device_class)
            except ValueError:
                self._attr_device_class = None

    # --------------------------------------------------------------- estado
    @property
    def _motor(self) -> MotorState | None:
        return self.coordinator.state.motors.get(self._channel)

    @property
    def current_cover_position(self) -> int | None:
        """Posição no padrão HA: 0 = fechada, 100 = aberta."""
        motor = self._motor
        if motor is None or motor.position is None:
            return None
        return self._module_to_ha(motor.position)

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def is_opening(self) -> bool:
        motor = self._motor
        if motor is None:
            return False
        return bool(motor.out_down if self._invert else motor.out_up)

    @property
    def is_closing(self) -> bool:
        motor = self._motor
        if motor is None:
            return False
        return bool(motor.out_up if self._invert else motor.out_down)

    # ----------------------------------------------------------- conversão
    def _module_to_ha(self, position: int) -> int:
        """Converte posição do módulo (0..255) para a escala HA (0..100)."""
        position = max(0, min(COVER_POS_MAX, position))
        if self._invert:
            return round(position / COVER_POS_MAX * 100)
        return round((COVER_POS_MAX - position) / COVER_POS_MAX * 100)

    def _ha_to_module(self, position: int) -> int:
        """Converte posição HA (0..100) para a escala do módulo (0..255)."""
        position = max(0, min(100, position))
        if self._invert:
            return round(position / 100 * COVER_POS_MAX)
        return round((100 - position) / 100 * COVER_POS_MAX)

    # ------------------------------------------------------------- comandos
    async def async_open_cover(self, **kwargs: Any) -> None:
        direction = _DIR_DOWN if self._invert else _DIR_UP
        await self.coordinator.async_cover_move(self._channel, direction)

    async def async_close_cover(self, **kwargs: Any) -> None:
        direction = _DIR_UP if self._invert else _DIR_DOWN
        await self.coordinator.async_cover_move(self._channel, direction)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_cover_move(self._channel, _DIR_STOP)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs[ATTR_POSITION]
        await self.coordinator.async_cover_set_position(
            self._channel, self._ha_to_module(position)
        )

    # ------------------------------------------------ serviços de entidade
    async def async_calibrate(self, action: str) -> None:
        """Serviço controlart.calibrate."""
        await self.coordinator.async_calibrate(self._channel, action)

    async def async_set_motor_mode(self, mode: str) -> None:
        """Serviço controlart.set_motor_mode."""
        await self.coordinator.async_set_motor_mode(
            self._channel, _MOTOR_MODES[mode]
        )
