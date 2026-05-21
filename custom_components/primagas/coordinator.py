"""DataUpdateCoordinator for PrimaGas."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PrimaGasApiError, PrimaGasAuthError, PrimaGasClient
from .const import CONF_ACCOUNT_ID, CONF_REFRESH_TOKEN, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class PrimaGasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls SHV Energy API and stores tank state."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: PrimaGasClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.entry = entry
        self.account: str = entry.data[CONF_ACCOUNT_ID]

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            assets = await self.client.get_assets(self.account)
        except PrimaGasAuthError as err:
            # Refresh token is invalid (revoked, expired, password changed) –
            # trigger the reauth flow.
            raise ConfigEntryAuthFailed(str(err)) from err
        except PrimaGasApiError as err:
            raise UpdateFailed(str(err)) from err

        # Persist the rotated refresh_token after every successful update so
        # we never lose it across restarts.
        new_refresh = self.client.refresh_token
        if new_refresh and new_refresh != self.entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_REFRESH_TOKEN: new_refresh},
            )
            _LOGGER.debug("Stored rotated refresh_token for account %s", self.account)

        return {"assets": assets.get("assets", [])}
