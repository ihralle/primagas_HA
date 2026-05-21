"""Constants for the PrimaGas integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "primagas"

# --------------------------------------------------------------------------- #
# Azure AD B2C / OAuth2 (extracted from kunden.primagas.de HAR analysis)
# --------------------------------------------------------------------------- #
B2C_TENANT = "depgprodaadb2c"
B2C_HOST = "login.primagas.de"
B2C_POLICY = "B2C_1A_SignInOrSignUp"
B2C_CLIENT_ID = "15f4b687-8555-413c-bafd-acb38cff6837"
B2C_REDIRECT_URI = "https://kunden.primagas.de/api/auth/callback/azureadb2c"
B2C_BASE_URL = (
    f"https://{B2C_HOST}/{B2C_TENANT}.onmicrosoft.com/{B2C_POLICY}"
)
B2C_SCOPE = (
    "offline_access openid profile "
    "https://depgprodaadb2c.onmicrosoft.com/customer-portal/customer-portal-api "
    "https://depgprodaadb2c.onmicrosoft.com/customer-portal/customer-portal-identity-api "
    "https://depgprodaadb2c.onmicrosoft.com/customer-portal/customer-portal-sitecore"
)

# --------------------------------------------------------------------------- #
# SHV Energy data API
# --------------------------------------------------------------------------- #
SHV_API_BASE = "https://api.shvenergy.com"
# Public APIM subscription key embedded in the frontend JS — identical for all
# users of the customer portal. Not a secret.
APIM_SUBSCRIPTION_KEY = "127cab3c995c46debf6ede4612576c26"
BUSINESS_UNIT = "DE-PG"

# --------------------------------------------------------------------------- #
# HTTP / behaviour
# --------------------------------------------------------------------------- #
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Telemetry sends one reading per day; polling every 6h is plenty.
UPDATE_INTERVAL = timedelta(hours=6)

# Refresh access token when it has less than this much life left
TOKEN_REFRESH_MARGIN = timedelta(minutes=2)

# --------------------------------------------------------------------------- #
# ConfigEntry / storage keys
# --------------------------------------------------------------------------- #
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCOUNT_ID = "account_id"
CONF_USERNAME = "username"  # stored only for display in the UI
