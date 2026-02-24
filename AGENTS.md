# AGENTS.md

## Project Overview

REVO is a helicopter aviation operations management platform for a charter/shuttle company based in São Paulo, Brazil. It consists of:

- **Streamlit Dashboard** (`salesforceintegration/app.py`): Interactive operational KPI dashboard with charts, maps, and flight data
- **Flight Monitor** (`salesforceintegration/flight_monitor.py`): Automated daemon that monitors flights and weather, sending Telegram alerts
- **Supporting modules**: Salesforce data extraction, weather monitoring (METAR/TAF/SIGMET), ADS-B tracking, empty leg cost calculations, weather image scraping

All Python source lives under `salesforceintegration/`.

## Cursor Cloud specific instructions

### Running the Streamlit Dashboard

```
cd salesforceintegration
streamlit run app.py --server.port 8501 --server.headless true --server.address 0.0.0.0
```

The dashboard loads data from `salesforceintegration/dados_reservas.csv` (or `dados_completos.csv`). Without Salesforce credentials, you can create sample CSV data for local development — see the column schema expected by `app.py`'s `load_data()` function.

### System Dependencies

The following system packages are required for `geopandas` and `selenium` (installed via apt): `gcc`, `libproj-dev`, `proj-data`, `proj-bin`, `libgeos-dev`, `libexpat1`, `fonts-liberation`. Google Chrome (pre-installed in this environment) is used by Selenium instead of Chromium.

### External Services (require secrets)

All external integrations require API credentials not available locally:
- **Salesforce**: `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, `SF_CONSUMER_KEY`, `SF_CONSUMER_SECRET`, `SF_DOMAIN`
- **Telegram**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

Without these, the `flight_monitor.py` and `salesforce_extractor.py` scripts will fail. The Streamlit dashboard works independently with local CSV data.

### No Tests or Linter

This project does not include automated tests or a configured linter. Validation is done by running the Streamlit app and verifying modules import correctly.

### Working Directory

All Python scripts use relative imports and file paths. Always run them from within `salesforceintegration/` (i.e., `cd salesforceintegration` first).
