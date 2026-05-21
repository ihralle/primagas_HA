"""Async PrimaGas API client.
Handles Azure AD B2C OAuth2 (Authorization Code + PKCE), automatic access-
token refresh and the calls to the SHV Energy data API.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
import urllib.parse
from typing import Any

import aiohttp
import yarl

from .const import (
    APIM_SUBSCRIPTION_KEY,
    B2C_BASE_URL,
    B2C_CLIENT_ID,
    B2C_POLICY,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    BUSINESS_UNIT,
    SHV_API_BASE,
    TOKEN_REFRESH_MARGIN,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class PrimaGasAuthError(Exception):
    """Login failed (wrong credentials, locked account, layout change)."""


class PrimaGasApiError(Exception):
    """A call to the SHV data API failed."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def extract_account_id(access_token: str) -> str | None:
    """Read the account ID from the group_scopes claim of the access token.
    Format observed: "owner:/business-units/DE-PG/accounts/XXXXXX".
    """
    try:
        claims = _decode_jwt_claims(access_token)
    except Exception:
        return None
    for scope in claims.get("group_scopes", []):
        m = re.search(r"/accounts/(\d+)", scope)
        if m:
            return m.group(1)
    return None


def _extract_name_value(header: str) -> str:
    """Extract the 'name=value' part from a Set-Cookie header.

    Correctly handles quoted values that contain ';' characters.
    Azure B2C CSRF tokens are known to contain literal semicolons
    inside DQUOTE-wrapped cookie values.
    """
    result = []
    in_quotes = False
    for ch in header:
        if ch == '"':
            in_quotes = not in_quotes
            result.append(ch)
        elif ch == ";" and not in_quotes:
            # First unquoted semicolon = end of name=value part
            break
        else:
            result.append(ch)
    return "".join(result).strip()


def _parse_set_cookie_headers(
    set_cookie_headers: list[str],
) -> list[tuple[str, str]]:
    """Extract (name, raw-value) pairs directly from Set-Cookie headers.

    Intentionally bypasses SimpleCookie/http.cookies to avoid any
    re-quoting or decoding of the raw bytes the server sent.
    Azure B2C's CSRF check compares the cookie value byte-for-byte
    against the X-CSRF-TOKEN header — any mutation causes 400.

    Uses _extract_name_value to correctly handle quoted values
    containing ';' characters (observed in B2C CSRF tokens).
    """
    pairs: list[tuple[str, str]] = []
    seen: dict[str, int] = {}

    for header in set_cookie_headers:
        name_value = _extract_name_value(header)
        if "=" not in name_value:
            continue
        name, _, value = name_value.partition("=")
        name = name.strip()
        # Strip surrounding DQUOTE wrapper if present —
        # the Cookie header must send the raw value without quotes
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        if name in seen:
            pairs[seen[name]] = (name, value)
        else:
            seen[name] = len(pairs)
            pairs.append((name, value))

    return pairs


class PrimaGasClient:
    """Stateful PrimaGas client. One instance per ConfigEntry."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        refresh_token: str | None = None,
    ) -> None:
        self._session = session
        self._refresh_token: str | None = refresh_token
        self._access_token: str | None = None
        self._access_token_expiry: float = 0.0  # epoch seconds

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def refresh_token(self) -> str | None:
        """Current refresh token — caller must persist it after each call."""
        return self._refresh_token

    async def login_with_password(self, username: str, password: str) -> None:
        """Initial login via Authorization Code + PKCE.

        Stores both access and refresh tokens on the client.
        Raises PrimaGasAuthError on credential or flow problems.
        """
        verifier = _b64url(secrets.token_bytes(64))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

        # ------------------------------------------------------------------ #
        # 1. /authorize – capture CSRF cookie and transId.
        # ------------------------------------------------------------------ #
        params = {
            "client_id": B2C_CLIENT_ID,
            "scope": B2C_SCOPE,
            "response_type": "code",
            "redirect_uri": B2C_REDIRECT_URI,
            "business_unit": BUSINESS_UNIT,
            "logoutDomain": "https://kunden.primagas.de",
            "ui_locales": "de-DE",
            "enableNewRegistration": "0",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        # Build the authorize URL with strict encoding (matching what browsers
        # and requests do): ':' and '/' in scope values get %3A/%2F-encoded.
        # If we let yarl handle this, the Referer on the next POST contains a
        # literal "https://" inside the query string, which the AFD WAF in
        # front of B2C rejects as a suspected URL-injection (400 Bad Request).
        authorize_url_str = (
            f"{B2C_BASE_URL}/oauth2/v2.0/authorize?"
            + urllib.parse.urlencode(params)
        )
        authorize_url = yarl.URL(authorize_url_str, encoded=True)

        # DummyCookieJar: Cookie-Verwaltung komplett deaktiviert.
        # Wir lesen Set-Cookie-Header direkt mit _parse_set_cookie_headers()
        # aus, um jegliche Veränderung der Raw-Werte durch SimpleCookie/aiohttp
        # zu vermeiden. Azure B2C vergleicht den CSRF-Cookie-Wert byte-genau
        # mit dem X-CSRF-TOKEN Header — jede Veränderung führt zu 400.
        async with aiohttp.ClientSession(
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as flow:

            async with flow.get(authorize_url) as resp:
                resp.raise_for_status()
                html = await resp.text()
                cookie_pairs = _parse_set_cookie_headers(
                    resp.headers.getall("Set-Cookie", [])
                )

            # IMPORTANT: use our string version as Referer, not str(resp.url)
            # yarl re-canonicalises URLs and would decode %3A/%2F back to
            # literal ':' '/' inside the query string → WAF rejects it.
            referer = authorize_url_str

            csrf_token = next(
                (v for k, v in cookie_pairs if k == "x-ms-cpim-csrf"), None
            )

            _LOGGER.debug(
                "authorize → cookies collected: %s",
                [k for k, _ in cookie_pairs],
            )

            if not csrf_token:
                raise PrimaGasAuthError(
                    "x-ms-cpim-csrf cookie missing — B2C layout may have changed"
                )

            m = re.search(r'"transId"\s*:\s*"([^"]+)"', html)
            if not m:
                raise PrimaGasAuthError(
                    "transId not found in authorize response"
                )
            trans_id = m.group(1)

            _LOGGER.debug(
                "extracted csrf=%s… trans_id=%s",
                csrf_token[:8], trans_id[:60],
            )

            # ---------------------------------------------------------------- #
            # 2. /SelfAsserted – send credentials.
            # ---------------------------------------------------------------- #
            # Encode body manually so Content-Type has no ";charset=utf-8"
            # suffix that aiohttp appends automatically (some B2C policies
            # reject it).
            form_body = urllib.parse.urlencode({
                "request_type": "RESPONSE",
                "signInName": username,
                "password": password,
            })

            post_url = yarl.URL(
                f"{B2C_BASE_URL}/SelfAsserted"
                f"?tx={urllib.parse.quote(trans_id, safe='')}"
                f"&p={B2C_POLICY}",
                encoded=True,
            )

            # Raw cookie values direkt verwenden – kein Requoting
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_pairs)

            _LOGGER.debug(
                "SelfAsserted → sending cookies: %s | csrf: %s…",
                [k for k, _ in cookie_pairs],
                csrf_token[:8],
            )

            async with flow.post(
                post_url,
                headers={
                    "X-CSRF-TOKEN": csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": referer,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Cookie": cookie_header,
                },
                data=form_body,
            ) as sa_resp:
                status = sa_resp.status
                ct = sa_resp.headers.get("Content-Type", "")
                text = await sa_resp.text()

                if status != 200 or "json" not in ct.lower():
                    resp_headers = {
                        k: v for k, v in sa_resp.headers.items()
                        if k.lower() != "set-cookie"
                    }
                    _LOGGER.warning(
                        "PrimaGas SelfAsserted FAILED\n"
                        "  POST URL       : %s\n"
                        "  Referer sent   : %s\n"
                        "  CSRF (first 8) : %s…  (len=%d)\n"
                        "  Cookie header  : %s\n"
                        "  Resp status    : %s\n"
                        "  Resp headers   : %s\n"
                        "  Resp body      : %s",
                        post_url, referer,
                        csrf_token[:8], len(csrf_token),
                        [k for k, _ in cookie_pairs],
                        status, resp_headers, text[:500],
                    )
                    try:
                        body = json.loads(text)
                    except ValueError as exc:
                        raise PrimaGasAuthError(
                            f"SelfAsserted returned non-JSON "
                            f"(status={status}, ct={ct!r}): {text[:200]}"
                        ) from exc
                else:
                    try:
                        body = json.loads(text)
                    except ValueError as exc:
                        raise PrimaGasAuthError(
                            f"SelfAsserted returned non-JSON "
                            f"(status={status}, ct={ct!r}): {text[:200]}"
                        ) from exc

                if str(body.get("status")) != "200":
                    raise PrimaGasAuthError(
                        f"Login rejected: "
                        f"{body.get('status')} {body.get('message')}"
                    )

                # Neue/rotierte Cookies aus SelfAsserted direkt auslesen
                new_cookies = _parse_set_cookie_headers(
                    sa_resp.headers.getall("Set-Cookie", [])
                )

            # Cookies zusammenführen – neue überschreiben alte
            for k, v in new_cookies:
                cookie_pairs = [(kk, vv) for kk, vv in cookie_pairs if kk != k]
                cookie_pairs.append((k, v))
                if k == "x-ms-cpim-csrf":
                    csrf_token = v

            _LOGGER.debug(
                "SelfAsserted → new/updated cookies: %s",
                [k for k, _ in new_cookies],
            )

            # ---------------------------------------------------------------- #
            # 3. /confirmed – grab the auth code from Location header.
            # ---------------------------------------------------------------- #
            confirmed_params = {
                "rememberMe": "false",
                "csrf_token": csrf_token,
                "tx": trans_id,
                "p": B2C_POLICY,
            }
            confirmed_url_str = (
                f"{B2C_BASE_URL}/api/CombinedSigninAndSignup/confirmed?"
                + urllib.parse.urlencode(confirmed_params)
            )
            confirmed_url = yarl.URL(confirmed_url_str, encoded=True)

            # Neu aufgebauter Cookie-Header mit ggf. rotierten Cookies
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_pairs)

            async with flow.get(
                confirmed_url,
                headers={
                    "Referer": referer,
                    "Cookie": cookie_header,
                },
                allow_redirects=False,
            ) as resp:
                c_status = resp.status
                c_text = await resp.text()
                if c_status != 302:
                    resp_headers = {
                        k: v for k, v in resp.headers.items()
                        if k.lower() != "set-cookie"
                    }
                    _LOGGER.warning(
                        "PrimaGas /confirmed FAILED\n"
                        "  URL            : %s\n"
                        "  Referer sent   : %s\n"
                        "  CSRF (url)     : %s…  (len=%d)\n"
                        "  Cookies sent   : %s\n"
                        "  New from SA    : %s\n"
                        "  Resp status    : %s\n"
                        "  Resp headers   : %s\n"
                        "  Resp body      : %s",
                        confirmed_url, referer,
                        csrf_token[:8], len(csrf_token),
                        [k for k, _ in cookie_pairs],
                        [k for k, _ in new_cookies],
                        c_status, resp_headers, c_text[:500],
                    )
                    raise PrimaGasAuthError(
                        f"confirmed returned {c_status}, expected 302: "
                        f"{c_text[:200]}"
                    )
                location = resp.headers.get("Location", "")

            parsed = urllib.parse.urlparse(location)
            code = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
            if not code:
                raise PrimaGasAuthError(
                    f"No 'code' in confirmed redirect: {location}"
                )

            # ---------------------------------------------------------------- #
            # 4. /token – swap code for tokens.
            # ---------------------------------------------------------------- #
            await self._token_request({
                "grant_type": "authorization_code",
                "client_id": B2C_CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": B2C_REDIRECT_URI,
            })
    async def ensure_access_token(self) -> str:
        """Return a non-expired access token, refreshing if needed."""
        if (
            self._access_token
            and self._access_token_expiry - time.time()
            > TOKEN_REFRESH_MARGIN.total_seconds()
        ):
            return self._access_token
        if not self._refresh_token:
            raise PrimaGasAuthError(
                "No refresh token available — re-authentication required"
            )
        await self._do_refresh()
        return self._access_token  # type: ignore[return-value]

    async def get_assets(
        self, account: str, delivery_point: str | None = None
    ) -> dict[str, Any]:
        """Return tank assets including forecast."""
        dp = delivery_point or f"{account}_T_1"
        url = (
            f"{SHV_API_BASE}/assets-api/v1/business-units/{BUSINESS_UNIT}"
            f"/accounts/{account}/delivery-points/{dp}/assets"
        )
        return await self._api_get(url)

    async def get_delivery_points(self, account: str) -> dict[str, Any]:
        """Return the list of delivery points for the account."""
        url = (
            f"{SHV_API_BASE}/customer-portals-api/v1/business-units/{BUSINESS_UNIT}"
            f"/accounts/{account}/delivery-points"
        )
        return await self._api_get(url)

    async def get_customer(self, account: str) -> dict[str, Any]:
        """Return master data for the customer."""
        url = (
            f"{SHV_API_BASE}/customers-api/v1/business-units/{BUSINESS_UNIT}"
            f"/accounts/{account}"
        )
        return await self._api_get(url)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _do_refresh(self) -> None:
        await self._token_request({
            "grant_type": "refresh_token",
            "client_id": B2C_CLIENT_ID,
            "refresh_token": self._refresh_token,
            "scope": B2C_SCOPE,
        })

    async def _token_request(self, data: dict[str, str]) -> None:
        async with self._session.post(
            f"{B2C_BASE_URL}/oauth2/v2.0/token",
            data=data,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            text = await resp.text()

            _LOGGER.debug(
                "Token endpoint: status=%s ct=%s",
                resp.status,
                resp.headers.get("Content-Type", ""),
            )

            if resp.status != 200:
                raise PrimaGasAuthError(
                    f"Token endpoint returned {resp.status}: {text[:300]}"
                )

            if not text or not text.strip():
                raise PrimaGasAuthError(
                    f"Token endpoint returned empty body (status={resp.status})"
                )

            try:
                tokens = json.loads(text)
            except json.JSONDecodeError as exc:
                raise PrimaGasAuthError(
                    f"Token endpoint returned invalid JSON "
                    f"(status={resp.status}): {text[:300]}"
                ) from exc

        if "access_token" not in tokens:
            raise PrimaGasAuthError(
                f"Token response missing access_token. Keys: {list(tokens.keys())}"
            )

        self._access_token = tokens["access_token"]
        self._access_token_expiry = (
            time.time() + int(tokens.get("expires_in", 600))
        )
        if "refresh_token" in tokens:
            self._refresh_token = tokens["refresh_token"]

        _LOGGER.debug(
            "Got new access_token (expires in %ss), refresh_token rotated: %s",
            tokens.get("expires_in"),
            "refresh_token" in tokens,
        )

    async def _api_get(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = await self.ensure_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Key": APIM_SUBSCRIPTION_KEY,
            "cp-client": "web",
            "Origin": "https://kunden.primagas.de",
            "Referer": "https://kunden.primagas.de/",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        async with self._session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 401:
                # Force a refresh on the next call and let the coordinator
                # retry.
                self._access_token = None
                raise PrimaGasApiError(f"401 Unauthorized for {url}")
            if resp.status != 200:
                text = await resp.text()
                raise PrimaGasApiError(
                    f"{resp.status} from {url}: {text[:300]}"
                )
            return await resp.json(content_type=None)