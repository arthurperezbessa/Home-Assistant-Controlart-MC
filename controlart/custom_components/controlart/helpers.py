"""Funções auxiliares da integração ControlArt."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CHANNEL_ROLE_COVER,
    CONF_FIRMWARE,
    CONF_MAC,
    DIMMER_OUTPUT_COUNT,
    DOMAIN,
    MODEL_NAMES,
    MODULE_RELAY,
    MOTOR_CHANNEL_COUNT,
)


def eligible_light_outputs(
    module_type: str, channels: dict[str, str]
) -> list[int]:
    """Retorna os índices de saída que podem virar luzes.

    No módulo relé, os canais 0..4 marcados como cortina consomem dois relés
    cada (2*CH e 2*CH+1) e portanto são excluídos das luzes.
    """
    if module_type != MODULE_RELAY:
        return list(range(DIMMER_OUTPUT_COUNT))

    outputs: list[int] = []
    for ch in range(MOTOR_CHANNEL_COUNT):
        if channels.get(str(ch)) == CHANNEL_ROLE_COVER:
            continue
        outputs.extend((2 * ch, 2 * ch + 1))
    return sorted(outputs)


def cover_channels(channels: dict[str, str]) -> list[int]:
    """Retorna os canais 0..4 configurados como cortina/motor."""
    return [
        ch
        for ch in range(MOTOR_CHANNEL_COUNT)
        if channels.get(str(ch)) == CHANNEL_ROLE_COVER
    ]


def module_device_info(entry) -> DeviceInfo:
    """DeviceInfo do módulo (relé ou dimmer)."""
    mac = entry.data[CONF_MAC]
    return DeviceInfo(
        identifiers={(DOMAIN, mac)},
        name=entry.title,
        manufacturer="ControlArt",
        model=MODEL_NAMES[entry.data["module_type"]],
        sw_version=entry.data.get(CONF_FIRMWARE),
    )
