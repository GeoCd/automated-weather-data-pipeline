# main_pipeline.py
# Daily automated pipeline: updates registered and online stations only.
# python main_pipeline.py --mode batch --trainAgain
# ------------------------------------------------------------------------------------------------------------
import csv
import datetime
import time
import logging
import argparse
import pandas as pd
from pathlib import Path
from selenium.common.exceptions import TimeoutException, WebDriverException

import src.workflows.weather_workflow as workflow
from src.scripts.extractor import (
    driver_start,
    kill_selenium_processes,
    showcase_get_table,
    try_parse_date
)

from src.config import WorkflowConfiguration

logger = logging.getLogger(__name__)                                                                                #Logs
config = WorkflowConfiguration()

# ------------------------------------------------------------------------------------------------------------
def load_registered_stations(csv_path: Path) -> list:
    stations = []

    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            status     = row.get('STATUS', 'OFFLINE').strip().upper()
            registered = row.get('Registered', '0').strip()

            if status == 'ONLINE' and registered == '1':
                stations.append({
                    'ciudad':   row['CITY'].strip().lower().replace(' ', '-'),
                    'estacion': row['ICAO'].strip(),
                    'estado':   row['STATE'].strip(),
                    'pais':     row['COUNTRY'].strip()
                })

    return stations


def get_last_extracted_date(station_id: str) -> datetime.date | None:
    station_dir = config.SCRAP_DIR / f"{station_id}_scrapdata"
    dates = []

    if not station_dir.exists():
        return None
    
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
    current_day = last_date + datetime.timedelta(days=1)
    dates = []

    if last_date is None:
        return [f"{yesterday.year}-{yesterday.month}-{yesterday.day}"]
    
    if last_date >= yesterday:
        return []
    
    while current_day <= yesterday:
        dates.append(f"{current_day.year}-{current_day.month}-{current_day.day}")
        current_day += datetime.timedelta(days=1)

    return dates


def extract_with_retry(url, date_str, station_id, max_retries=config.MAX_RETRIES):

    for attempt in range(1, max_retries + 1):
        kill_selenium_processes()

        try:
            showcase_get_table(driver_start(), url, config.CSS_ELEMENT, config.OUT_FORMAT, date_str, station_id)    # Main Extractor
            return 'ok'
        
        except TimeoutException:
            logger.warning(f"[{station_id}] {date_str} attempt {attempt}: TIMEOUT")                                 # Exception Logs

            if attempt == max_retries:
                return 'timeout'
            
        except WebDriverException as e:
            logger.warning(f"[{station_id}] {date_str} attempt {attempt}: WebDriverException: {e}")                 # Exception Logs

            if attempt == max_retries:
                return 'timeout'
            
        except Exception as e:
            logger.error(f"[{station_id}] {date_str} attempt {attempt}: unexpected error: {e}")                     # Exception Logs

            if attempt == max_retries:
                return 'failed'
            
        time.sleep(3)

    return 'failed'

# ------------------------------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------------------------------
def main():

    temp_df_storage     = []
    skipped_stations    = []
    succesful_stations  = []
    failure_stations    = []

    # ----- console parser -----
    argparser   = argparse.ArgumentParser()
    argparser.add_argument("--mode", type=str, default=config.PIPELINE_MODE,choices=["batch", "incremental"])
    argparser.add_argument("--trainAgain", action="store_true")
    args = argparser.parse_args()
    # ----- console parser -----

    today     = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    stations_csv = config.DATA_DIR / "mexico_stations.csv"
    stations     = load_registered_stations(stations_csv)

    logger.info(f"Pipeline started: {today.isoformat()} | Target: {yesterday.isoformat()}")                             #Logs
    logger.info(f"Registered ONLINE stations: {len(stations)}")                                                         #Logs

    for station in stations:
        station_id      = station['estacion']
        url             = config.BASE_URL.format(city=station['ciudad'], station=station_id)
        last_date       = get_last_extracted_date(station_id)
        missing_dates   = get_missing_dates(last_date)

        logger.info(f"--- {station_id} ({station['ciudad'].upper()}) ---")                                              #Logs

        if not missing_dates:
            logger.info(f"[{station_id}] Already up to date. Skipping.")                                                #Logs
            skipped_stations.append(station_id)
            continue

        if len(missing_dates) > config.MAX_MISSING_DAYS:
            logger.warning(f"Too many days. Skipping to avoid detection. Use main_extractor.py to recover.")            #Logs
            failure_stations.append({'station': station_id, 'reason': f'too many missing days ({len(missing_dates)})'})
            continue

        logger.info(f"[{station_id}] Missing {len(missing_dates)} day(s): {missing_dates[0]} to {missing_dates[-1]}")   #Logs

        station_ok = True
        for date_str in missing_dates:
            status = extract_with_retry(url, date_str, station_id)

            if status == 'ok':
                logger.info(f"[{station_id}] {date_str} OK")                                                            #Logs
            else:
                logger.warning(f"[{station_id}] {date_str} -> {status}")                                                #Logs
                failure_stations.append({'station': station_id, 'date': date_str, 'reason': status})
                station_ok = False

        if station_ok:
            df = workflow.run_workflow(id=station_id, mode=args.mode)
            succesful_stations.append(station_id)
            temp_df_storage.append(df)

    final_df = pd.concat(temp_df_storage)
    outputFile = config.DATA_DIR/"mexico_weather.csv"
    final_df.to_csv(outputFile)

    # Debug
    """     
    logger.info(f"SUMMARY | OK: {len(ok)} | Skipped: {len(skipped)} | Failures: {len(failures)}")
    for f in failures:
        logger.warning(f"  FAILED: {f}")
    """

if __name__ == "__main__":
    main()