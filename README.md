# PrimaGas Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)
![Version](https://img.shields.io/badge/version-0.1.0-green)

A custom Home Assistant integration for monitoring your PrimaGas LPG tank via
the [kunden.primagas.de](https://kunden.primagas.de) customer portal.

---

## Features

- 🔋 **Fill level** – current tank fill level in percent
- 🪣 **Current volume** – current gas volume in liters
- 📦 **Tank capacity** – total tank capacity in liters
- 📅 **Predicted delivery date** – forecasted next delivery date
- 📅 **Predicted runout date** – forecasted date when tank runs empty
- 📆 **Stock remaining** – days of gas remaining
- 🚚 **Recommended refill volume** – suggested delivery volume in liters

---

## Requirements

- Home Assistant **2024.1** or newer
- A valid account at [kunden.primagas.de](https://kunden.primagas.de)
- Python package `aiohttp` (included in Home Assistant)
- Python package `yarl` (included in Home Assistant)

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add this repository URL and select category **Integration**
5. Click **Download**
6. Restart Home Assistant

### Manual

1. Copy the `custom_components/primagas` folder into your
   `config/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **PrimaGas**
3. Enter your **e-mail address** and **password** from kunden.primagas.de
4. Click **Submit**

The integration will automatically discover your account ID and set up all
sensor entities.

---

## Sensors

| Entity | Unit | Description |
|---|---|---|
| `sensor.primagas_level_percentage` | `%` | Current fill level |
| `sensor.primagas_filling_volume` | `L` | Current gas volume |
| `sensor.primagas_capacity` | `L` | Total tank capacity |
| `sensor.primagas_stock_left_days` | `d` | Days of gas remaining |
| `sensor.primagas_predicted_delivery_date` | timestamp | Forecasted delivery |
| `sensor.primagas_predicted_runout_date` | timestamp | Forecasted runout |
| `sensor.primagas_replenishment_volume` | `L` | Recommended refill volume |

> **Note:** `capacity` and `predicted_runout_date` are disabled by default.
> Enable them in the entity settings if needed.

---

## Authentication

This integration uses the **Azure AD B2C OAuth2 Authorization Code + PKCE**
flow to authenticate against the PrimaGas customer portal [1].

- The **refresh token** is stored securely in the Home Assistant config entry
  and rotated automatically on every token refresh [5]
- If the session expires or the password changes, Home Assistant will
  automatically trigger a **re-authentication flow**
- No passwords are stored — only the rotating refresh token [3]

---

## Update Interval

Tank data is polled from the SHV Energy API at a regular interval defined in
`const.py`. The default is set to a reasonable polling frequency to avoid
excessive API calls.

---

## Disclaimer
This integration is not affiliated with or endorsed by PrimaGas or SHV
Energy. It uses the same API as the official customer portal. Use at your
own risk. The API may change at any time without notice.

---

## Troubleshooting

### Login fails with `invalid_auth`
- Double-check your e-mail and password at
  [kunden.primagas.de](https://kunden.primagas.de)
- Make sure your account is not locked

### `confirmed returned 400`
- This indicates an issue with the Azure B2C login flow
- Try removing and re-adding the integration
- Check the Home Assistant logs for detailed debug output

### `Token endpoint returned empty body`
- The refresh token has expired or been revoked
- Re-authenticate via **Settings → Devices & Services → PrimaGas → Re-authenticate**

### Enable debug logging

Add the following to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.primagas: debug
