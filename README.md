# Automated Weather Data Pipeline - Mexico

This is the production system behind the [MMMX Weather Dataset](https://www.kaggle.com/datasets/jorgeaconde/historical-weather-mexico-stations) and [MMMX Weather Analysis](https://github.com/GeoCd/MMMX-station-weather-analysis) projects. While that one is exploratory, this one runs daily, extracts real observations from weather stations across Mexico, cleans and resamples them, pushes everything to a embbeded repo and then updates everything to Kaggle automatically.

---

## Architecture

```
src/
├── config/
│   └── main_config.py        # paths, thresholds, pipeline mode
├── scripts/
│   └── extractor.py          # selenium scraper core
└── workflows/
    ├── weather_workflow.py   # scrap -> raw -> clean pipeline
    └── lstm_model.py         # model training per station

mx-weather-datasets/          # submodule -> Github Repo -> Kaggle dataset
scraped/                      # raw daily CSVs per station
models/                       # model output after training in notebooks
notebooks/                    # analysis and experiments
main_pipeline.py              # daily automated entry point
main_extractor.py             # manual extraction and station registration
```

Data flows in one direction:

```
Data Provider -> scraper -> scraped/{STATION}_scrapdata/
              -> weather_workflow -> raw-data/ -> clean-data/ -> mexico_weather.csv
              -> git push -> Kaggle
```

---

## Station Coverage

Stations are managed in `mx-weather-datasets/mexico_stations.csv` with two control columns:

| Column | Values | Description |
|---|---|---|
| Status | ONLINE / OFFLINE | Whether the station is currently reporting |
| Registered | 1 / 0 | Whether local data folders exist for this station |

The pipeline only processes stations where `Status=ONLINE` and `Registered=1`. Currently active stations include MMMX (Mexico City), with coverage expanding as more stations are registered.

---

## Pipeline

The CI/CD workflow runs daily around **00:01 CDMX (06:01 UTC)** via GitHub Actions.

Each run:
1. Checks the last extracted date per station
2. Skips stations with more than 5 missing days (use `main_extractor.py` to recover those)
3. Extracts missing observations from the data provider
4. Runs the transformation and cleaning workflow
5. Commits updated datasets back to the repo

The commit history in GitHub Actions doubles as an execution log. If a run fails, GitHub sends an automatic notification.

---

## Dataset

The cleaned dataset is available on Kaggle or in mx-weather-datasets, both update daily. Each station produces a CSV with hourly resampled observations:

| Column | Unit |
|---|---|
| DateTime | UTC |
| Station | ICAO code |
| Code | Country code |
| City / State / Country | - |
| Lat_num | Num |
| Long_num | Num |
| Elevation | Num |
| Temperature | °F |
| Dew Point | °F |
| Humidity | % |
| Wind Speed | mph |
| Wind Gust | mph |
| Pressure | inHg |
| Wind | - |
| Condition | - |
---

## Local Setup

To add a new station or recover missing data, use `main_extractor.py` directly.

**Register a new station and extract from a specific date:**
```bash
python main_extractor.py --id MMMY --register new --method fill --start 2024-01-01
```

**Continue extraction from the last available date:**
```bash
python main_extractor.py --id MMMX --register existing --method refill
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

Requires Chrome and Chromedriver installed locally. On Linux, Chromedriver is expected at `/usr/bin/chromedriver`. On Windows, `webdriver-manager` handles it automatically.
For best results and avoid zombie processes, a run on Linux is recommended.