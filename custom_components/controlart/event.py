"""Plataforma event: teclas dos keypads CAN Bus.

Cada tecla de cada keypad vira uma entidade de evento. Os eventos
(click, double_click, long_click, press, release) podem ser usados
diretamente como gatilho de automações/cenas no Home Assistant.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MAC,
    DOMAIN,
    KEYPAD_EVENT_TYPES,
    KEYPAD_KEYS,
    OPT_KEYPADS,
    SIGNAL_KEYPAD,
)
from .coordinator import ControlArtCoordinator
from .helpers import module_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria as entidades de evento para cada tecla de keypad."""
    coordinator: ControlArtCoordinator = hass.data[DOMAIN][entry.entry_id]
    keypads: dict[str, Any] = entry.options.get(OPT_KEYPADS, {})

    entities: list[EventEntity] = []
    for dev_id, conf in keypads.items():
        typ = int(conf.get("type", 2))
        key_count = KEYPAD_KEYS.get(typ, 4)
        kp_name = (conf.get("name") or "").strip() or f"Teclado {dev_id}"
        for key in range(key_count):
            entities.append(
                KeypadKeyEvent(coordinator, entry, dev_id, typ, key, kp_name)
            )
    async_add_entities(entities)


class KeypadKeyEvent(EventEntity):
    """Uma tecla de keypad CAN Bus exposta como entidade de evento."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(KEYPAD_EVENT_TYPES)

    def __init__(
        self,
        coordinator: ControlArtCoordinator,
        entry: ConfigEntry,
        dev_id: str,
        keypad_type: int,
        key: int,
        keypad_name: str,
    ) -> None:
        self._entry = entry
        self._dev_id = dev_id
        self._key = key
        self._attr_name = f"{keypad_name} tecla {key + 1}"

        mac = entry.data[CONF_MAC]
        self._attr_unique_id = f"{mac}_keypad_{dev_id}_key_{key}"

        # O keypad é um sub-dispositivo, ligado ao módulo via via_device.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{mac}_keypad_{dev_id}")},
            name=keypad_name,
            manufacturer="ControlArt",
            model=f"Keypad CAN Bus ({KEYPAD_KEYS.get(keypad_type, 4)} teclas)",
            via_device=(DOMAIN, mac),
        )

    async def async_added_to_hass(self) -> None:
        """Assina o sinal de eventos de keypad."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_KEYPAD}_{self._entry.entry_id}",
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, dev_id: str, key: int, evt_name: str) -> None:
        """Filtra e dispara o evento desta tecla."""
        if dev_id != self._dev_id or key != self._key:
            return
        if evt_name not in self._attr_event_types:
            return
        self._trigger_event(evt_name)
        self.async_write_ha_state()
