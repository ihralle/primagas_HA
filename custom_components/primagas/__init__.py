"""The PrimaGas integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PrimaGasApiError, PrimaGasAuthError, PrimaGasClient
from .const import CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import PrimaGasCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PrimaGas from a config entry."""
    session = async_get_clientsession(hass)
    client = PrimaGasClient(session, refresh_token=entry.data[CONF_REFRESH_TOKEN])

    coordinator = PrimaGasCoordinator(hass, client, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except PrimaGasAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except PrimaGasApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
