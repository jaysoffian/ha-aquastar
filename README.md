# Town of Cary Aquastar Integration for Home Assistant

This [integration](https://www.home-assistant.io/getting-started/concepts-terminology/#integrations) reports your [Town of Cary](https://www.carync.gov) water usage from the [Aquastar](https://www.carync.gov/services-publications/water-sewer/water/aquastar) portal into your [Home Assistant](https://www.home-assistant.io) installation.

Aquastar provides hourly water usage data (in gallons) going back 13 months.

## Prerequisites

You need an Aquastar account through the Town of Cary's [Paymentus billing portal](https://ipn.paymentus.com/cp/tcnc).

## Installation

### HACS

1. Install [HACS](https://hacs.xyz), then either:
   1. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jaysoffian&repository=ha-aquastar&category=integration)

   Or:

   1. Open HACS > Integrations
   2. Open triple-dot menu > Custom repositories
   3. Add this repository's URL (`https://github.com/jaysoffian/ha-aquastar`), category "Integration"
2. Install this integration and restart Home Assistant

### Manual

Copy `custom_components/toc_aquastar` to your Home Assistant `custom_components` directory and restart.

## Configuration

### Obtaining your sectoken

1. Log into the Town of Cary billing portal at https://ipn.paymentus.com/cp/tcnc
2. On the landing page, find the **Aquastar** link (usually at the bottom under "More")
3. Right-click the link and copy the URL — it will look like:
   ```
   https://aquastar.townofcary.org/waterconsumption/run?id=0&sectoken=YOUR_TOKEN_HERE
   ```
4. The `sectoken` value is the long hex string after `sectoken=`

This token is tied to your account and does not change across logins.

### Adding the integration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for "Town of Cary Aquastar"
3. Enter your sectoken

## Development

See [docs/development.md](docs/development.md).

## How it works

The integration polls the Aquastar portal for hourly water usage data and imports it as Home Assistant long-term statistics, making it available in the Energy Dashboard.

Data is fetched every 30 minutes. On first setup, up to 13 months of historical data is imported.
