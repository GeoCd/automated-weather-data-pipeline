# main_pipeline.py
# Daily automated pipeline: updates registered and online stations only, runs on GitHub Actions at 06:01 UTC or 00:01 CDMX.
# python main_pipeline.py --mode batch --trainAgain
# ------------------------------------------------------------------------------------------------------------
import csv
import datetime
import time
import logging
import argparse
from pathlib import Path

import src.workflows.lstm_model as lstm_model
import src.workflows.weather_workflow as workflow
from src.scripts.extractor import (
    driver_start,
    kill_selenium_processes,
    showcase_get_table,
    try_parse_date
)
from src.config import WorkflowConfiguration
config = WorkflowConfiguration()

logger = logging.getLogger(__name__)

def load_registered_stations(csv_path: Path) -> list:
    stations = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            status     = row.get('Status',     'OFFLINE').strip().upper()
            registered = row.get('Registered', '0').strip()
            if status == 'ONLINE' and registered == '1':
                stations.append({
                    'ciudad':   row['Ciudad'].strip().lower().replace(' ', '-'),
                    'estacion': row['Estacion'].strip(),
                    'estado':   row['Estado'].strip(),
                    'pais':     row['Pais'].strip()
                })
    return stations


def get_last_extracted_date(station_id: str) -> datetime.date | None:
    station_dir = config.SCRAP_DIR / f"{station_id}_scrapdata"
    if not station_dir.exists():
        return None
    dates = []
    for f in station_dir.iterdir():
        if f.suffix != '.csv':
            continue
        parts = f.stem.split('_')
        if len(parts) < 2:
            continue
        parsed = try_parse_date(parts[-1])
        if parsed:
            dates.append(parsed)
    return max(dates) if dates else None


def get_missing_dates(last_date: datetime.date | None) -> list:
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    if last_date is None:
        return [f"{yesterday.year}-{yesterday.month}-{yesterday.day}"]
    if last_date >= yesterday:
        return []
    cur = last_date + datetime.timedelta(days=1)
    dates = []
    while cur <= yesterday:
        dates.append(f"{cur.year}-{cur.month}-{cur.day}")
        cur += datetime.timedelta(days=1)
    return dates


def extract_with_retry(url, date_str, station_id, max_retries=config.MAX_RETRIES):
    from selenium.common.exceptions import TimeoutException, WebDriverException
    for attempt in range(1, max_retries + 1):
        kill_selenium_processes()
        try:
            showcase_get_table(driver_start(), url, config.CSS_ELEMENT, config.OUT_FORMAT, date_str, station_id)
            return 'ok'
        except TimeoutException:
            logger.warning(f"[{station_id}] {date_str} attempt {attempt}: TIMEOUT")
            if attempt == max_retries:
                return 'timeout'
        except WebDriverException as e:
            logger.warning(f"[{station_id}] {date_str} attempt {attempt}: WebDriverException: {e}")
            if attempt == max_retries:
                return 'timeout'
        except Exception as e:
            logger.error(f"[{station_id}] {date_str} attempt {attempt}: unexpected error: {e}")
            if attempt == max_retries:
                return 'failed'
        time.sleep(3)
    return 'failed'

# ------------------------------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------------------------------
def main():
    
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--mode", type=str, default=config.PIPELINE_MODE,choices=["batch", "incremental"])
    argparser.add_argument("--trainAgain", action="store_true")
    args = argparser.parse_args()

    today     = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    logger.info(f"Pipeline started: {today.isoformat()} | Target: {yesterday.isoformat()}")

    stations_csv = config.DATA_DIR / "mexico_stations.csv"
    stations     = load_registered_stations(stations_csv)
    logger.info(f"Registered ONLINE stations: {len(stations)}")

    skipped  = []
    ok       = []
    failures = []

    for station in stations:
        station_id = station['estacion']
        url        = config.BASE_URL.format(city=station['ciudad'], station=station_id)

        logger.info(f"--- {station_id} ({station['ciudad'].upper()}) ---")

        last_date     = get_last_extracted_date(station_id)
        missing_dates = get_missing_dates(last_date)

        if not missing_dates:
            logger.info(f"[{station_id}] Already up to date. Skipping.")
            skipped.append(station_id)
            continue

        if len(missing_dates) > config.MAX_MISSING_DAYS:
            logger.warning(f"[{station_id}] Missing {len(missing_dates)} days (>{config.MAX_MISSING_DAYS}). Skipping to avoid detection. Use main_extractor.py to recover.")
            failures.append({'station': station_id, 'reason': f'too many missing days ({len(missing_dates)})'})
            continue

        logger.info(f"[{station_id}] Missing {len(missing_dates)} day(s): {missing_dates[0]} to {missing_dates[-1]}")

        station_ok = True
        for date_str in missing_dates:
            status = extract_with_retry(url, date_str, station_id)
            if status == 'ok':
                logger.info(f"[{station_id}] {date_str} OK")
            else:
                logger.warning(f"[{station_id}] {date_str} -> {status}")
                failures.append({'station': station_id, 'date': date_str, 'reason': status})
                station_ok = False

        if station_ok:
            # Transform and update clean CSV
            df = workflow.run_workflow(id=station_id, mode=args.mode)
            ok.append(station_id)
            lstm_model.run_model(df, station_id, trainAgain=args.trainAgain)

    # Debug
    """     
    logger.info(f"SUMMARY | OK: {len(ok)} | Skipped: {len(skipped)} | Failures: {len(failures)}")
    for f in failures:
        logger.warning(f"  FAILED: {f}")
    """


if __name__ == "__main__":
    main()