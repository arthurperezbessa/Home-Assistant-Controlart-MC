"""Plataforma binary_sensor: entradas físicas do módulo.

As 12 entradas cabeadas só são expostas quando a opção "expose_inputs"
está ligada na tela de opções da integração.
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, DOMAIN, INPUT_COUNT, OPT_EXPOSE_INPUTS
from .coordinator import ControlArtCoordinator
from .helpers import module_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria os sensores de entrada, se a opção estiver habilitada."""
    if not entry.options.get(OPT_EXPOSE_INPUTS, False):
        return

    coordinator: ControlArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ControlArtInput(coordinator, entry, i) for i in range(INPUT_COUNT)
    ]
    async_add_entities(entities)


class ControlArtInput(CoordinatorEntity[ControlArtCoordinator], BinarySensorEntity):
    """Uma entrada física do módulo exposta como sensor binário."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: ControlArtCoordinator,
        entry: ConfigEntry,
        index: int,
    ) -> None:
        super().__init__(coordinator)
        self._index = index
        self._attr_name = f"Entrada {index + 1}"

        mac = entry.data[CONF_MAC]
        self._attr_unique_id = f"{mac}_input_{index}"
        self._attr_device_info = module_device_info(entry)

    @property
    def is_on(self) -> bool:
        inputs = self.coordinator.state.inputs
        if self._index < len(inputs):
            return inputs[self._index] != 0
        return False
