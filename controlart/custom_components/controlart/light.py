"""Plataforma light: saídas de relé (on/off) e de dimmer (brilho + rampa)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MAC,
    DOMAIN,
    MODULE_RELAY,
    OPT_CHANNELS,
    OPT_LIGHT_NAMES,
    OPT_LIGHT_OUTPUTS,
)
from .coordinator import ControlArtCoordinator
from .helpers import eligible_light_outputs, module_device_info

_LOGGER = logging.getLogger(__name__)

_MAX_RAMP = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria as entidades de luz a partir das opções."""
    coordinator: ControlArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    channels: dict[str, str] = entry.options.get(OPT_CHANNELS, {})
    eligible = eligible_light_outputs(coordinator.module_type, channels)
    active = set(entry.options.get(OPT_LIGHT_OUTPUTS, eligible))
    names: dict[str, str] = entry.options.get(OPT_LIGHT_NAMES, {})

    entities: list[LightEntity] = []
    for out in eligible:
        if out not in active:
            continue
        name = names.get(str(out)) or f"Saída {out + 1}"
        if coordinator.module_type == MODULE_RELAY:
            entities.append(RelayLight(coordinator, entry, out, name))
        else:
            entities.append(DimmerLight(coordinator, entry, out, name))
    async_add_entities(entities)


class _BaseLight(CoordinatorEntity[ControlArtCoordinator], LightEntity):
    """Base comum às luzes ControlArt."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: ControlArtCoordinator,
        entry: ConfigEntry,
        output: int,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._output = output
        self._attr_name = name
        mac = entry.data[CONF_MAC]
        self._attr_unique_id = f"{mac}_light_{output}"
        self._attr_device_info = module_device_info(entry)

    @property
    def _raw(self) -> int:
        outputs = self.coordinator.state.outputs
        if self._output < len(outputs):
            return outputs[self._output]
        return 0


class RelayLight(_BaseLight):
    """Saída de relé exposta como luz on/off."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        return self._raw != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_relay(self._output, 1)
        self._optimistic(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_relay(self._output, 0)
        self._optimistic(0)

    def _optimistic(self, value: int) -> None:
        outputs = self.coordinator.state.outputs
        if self._output < len(outputs):
            outputs[self._output] = value
        self.async_write_ha_state()


class DimmerLight(_BaseLight):
    """Saída de dimmer exposta como luz com brilho (controle por percentual)."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.TRANSITION

    @property
    def _minmax(self) -> tuple[int, int]:
        mm = self.coordinator.state.minmax
        if self._output < len(mm):
            return mm[self._output]
        return (0, 255)

    @property
    def is_on(self) -> bool:
        return self._raw > 0

    @property
    def brightness(self) -> int | None:
        raw = self._raw
        if raw <= 0:
            return 0
        mn, mx = self._minmax
        if mx <= mn:
            pct = raw / 255 * 100
        else:
            pct = (raw - mn) / (mx - mn) * 100
        pct = min(100.0, max(1.0, pct))
        return round(pct / 100 * 255)

    def _ramp(self, kwargs: dict[str, Any]) -> int:
        if ATTR_TRANSITION in kwargs:
            return max(0, min(_MAX_RAMP, round(kwargs[ATTR_TRANSITION] * 10)))
        ramps = self.coordinator.state.ramps
        if self._output < len(ramps):
            return ramps[self._output]
        return 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            percent = max(1, min(100, round(kwargs[ATTR_BRIGHTNESS] / 255 * 100)))
        else:
            percent = 100
        ramp = self._ramp(kwargs)
        await self.coordinator.async_set_dimmer_percent(
            self._output, percent, ramp
        )
        self._optimistic(percent)

    async def async_turn_off(self, **kwargs: Any) -> None:
        ramp = self._ramp(kwargs)
        await self.coordinator.async_set_dimmer_percent(self._output, 0, ramp)
        self._optimistic(0)

    def _optimistic(self, percent: int) -> None:
        """Estima o valor bruto para resposta imediata na interface."""
        outputs = self.coordinator.state.outputs
        if self._output < len(outputs):
            if percent <= 0:
                outputs[self._output] = 0
            else:
                mn, mx = self._minmax
                outputs[self._output] = round(mn + (mx - mn) * percent / 100)
        self.async_write_ha_state()
