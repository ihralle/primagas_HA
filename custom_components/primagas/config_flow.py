"""Config flow for PrimaGas."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PrimaGasAuthError, PrimaGasClient, extract_account_id
from .const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class PrimaGasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PrimaGas."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                refresh_token, account = await self._login(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except PrimaGasAuthError as err:
                _LOGGER.warning("PrimaGas login failed: %s", err)
                errors["base"] = "invalid_auth"
            except ClientError as err:
                _LOGGER.warning("PrimaGas connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover
                _LOGGER.exception("Unexpected error during PrimaGas login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(account)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"PrimaGas {account}",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_ACCOUNT_ID: account,
                        CONF_REFRESH_TOKEN: refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}
        username = self._reauth_entry.data[CONF_USERNAME]

        if user_input is not None:
            try:
                refresh_token, account = await self._login(
                    username, user_input[CONF_PASSWORD]
                )
            except PrimaGasAuthError:
                errors["base"] = "invalid_auth"
            except ClientError:
                errors["base"] = "cannot_connect"
            else:
                if account != self._reauth_entry.data[CONF_ACCOUNT_ID]:
                    errors["base"] = "account_mismatch"
                else:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data={
                            **self._reauth_entry.data,
                            CONF_REFRESH_TOKEN: refresh_token,
                        },
                    )
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"username": username},
        )

    async def _login(self, username: str, password: str) -> tuple[str, str]:
        """Run the OAuth flow and return (refresh_token, account_id)."""
        session = async_get_clientsession(self.hass)
        client = PrimaGasClient(session)
        await client.login_with_password(username, password)
        access_token = await client.ensure_access_token()
        account = extract_account_id(access_token)
        if not account:
            raise PrimaGasAuthError("Could not extract account ID from token")
        refresh_token = client.refresh_token
        if not refresh_token:
            raise PrimaGasAuthError("No refresh_token returned by B2C")
        return refresh_token, account
