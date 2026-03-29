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

### Water cost estimates

The integration also computes estimated utility costs using Town of Cary's single-family residential rates (inside corporate limits, 1" or smaller meter). This includes:

- **Tiered water charges** ($5.46 / $6.13 / $7.74 per 1,000 gallons)
- **Flat sewer charge** ($11.69 per 1,000 gallons)

The rate schedule is hard-coded since it rarely changes — typically once per year on July 1.

Tiered rates are applied based on cumulative usage within each billing cycle. By default the billing cycle aligns with calendar months (day 1). If your billing cycle starts on a different day, go to **Settings > Devices & Services > Aquastar** and configure the **Billing cycle start day** in the integration options. Note that Town of Cary's actual meter read dates vary by a few days from month to month depending on the read route schedule, so the billing cycle day is an approximation. Check a few recent bills to find the most typical start day.

### Correcting costs after a rate update

If the rates in the code are updated after the new rates have already taken effect (e.g. you update in September for rates that changed July 1), previously recorded cost statistics will be based on the old rates. To recalculate:

1. Update `rates.py` with the new rate schedule
2. Restart Home Assistant
3. Go to **Developer Tools → Statistics**
4. Find and delete the `toc_aquastar:{meter_number}_water_cost` statistic
5. Within 30 minutes, the integration will automatically rebuild all cost statistics using the corrected rates

Consumption data is not affected by this process.
