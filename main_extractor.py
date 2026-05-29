# main_extractor.py
# python main_extractor.py --id MMMX --register new --method fill --start 2024-01-01
# python main_extractor.py --id MMMX --register existing --method refill
# ------------------------------------------------------------------------------------------------------------
import csv
import argparse
import datetime
import time
import logging
from pathlib import Path

from src.scripts.extractor import (
    driver_start,
    kill_selenium_processes,
    showcase_get_table,
    try_parse_date
)
from src.config import WorkflowConfiguration

config = WorkflowConfiguration()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------------------------
# CSV helpers
# ------------------------------------------------------------------------------------------------------------
def load_station_row(csv_path: Path, station_id: str) -> dict | None:
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['ICAO'].strip() == station_id:
                return row
    return None


def update_station_csv(csv_path: Path, station_id: str, field: str, value: str):
    rows = []
    fieldnames = None
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row['ICAO'].strip() == station_id:
                row[field] = value
            rows.append(row)

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"[{station_id}] CSV updated: {field} = {value}")


def ensure_csv_columns(csv_path: Path):
    """Adds Status and Registered columns if they don't exist yet."""
    rows = []
    fieldnames = None
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    changed = False
    if 'STATUS' not in fieldnames:
        fieldnames.append('STATUS')
        for row in rows:
            row['STATUS'] = 'ONLINE'
        changed = True
    if 'Registered' not in fieldnames:
        fieldnames.append('Registered')
        for row in rows:
            row['Registered'] = '0'
        changed = True

    if changed:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"CSV columns updated: added Status and/or Registered.")

def register_new(station_id: str, csv_path: Path):
    """Creates scraped subfolder and marks Registered=1 in CSV."""
    station_dir = config.SCRAP_DIR / f"{station_id}_scrapdata"
    if not station_dir.exists():
        station_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[{station_id}] Created folder: {station_dir}")
    else:
        logger.info(f"[{station_id}] Folder already exists: {station_dir}")
    update_station_csv(csv_path, station_id, 'Registered', '1')


def register_existing(station_id: str, csv_path: Path):
    """Checks if folder exists, then marks Registered=1 in CSV."""
    station_dir = config.SCRAP_DIR / f"{station_id}_scrapdata"
    if not station_dir.exists():
        logger.warning(f"[{station_id}] Folder not found at {station_dir}. Use --register new instead.")
        return False
    update_station_csv(csv_path, station_id, 'Registered', '1')
    return True


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


def build_date_list(start: datetime.date, end: datetime.date) -> list:
    dates = []
    cur = start
    while cur <= end:
        dates.append(f"{cur.year}-{cur.month}-{cur.day}")
        cur += datetime.timedelta(days=1)
    return dates

# ------------------------------------------------------------------------------------------------------------
# Extraction
# ------------------------------------------------------------------------------------------------------------
def extract_with_retry(url, date_str, station_id, max_retries=config.MAX_RETRIES):
    from selenium.common.exceptions import TimeoutException, WebDriverException
    for attempt in range(1, max_retries + 1):
        kill_selenium_processes()
        try:
            result = showcase_get_table(
                driver_start(), url, config.CSS_ELEMENT, config.OUT_FORMAT, date_str, station_id
            )
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
    parser = argparse.ArgumentParser(description="Manual robust extractor for weather stations.")
    parser.add_argument("--id",       type=str, required=True,  help="Station ID (e.g. MMMX)")
    parser.add_argument("--register", type=str, choices=["new", "existing"], default=None,
                        help="new: creates folder and registers. existing: verifies folder and registers.")
    parser.add_argument("--method",   type=str, choices=["fill", "refill"], required=True,
                        help="fill: extract from --start date to yesterday. refill: from last available date to yesterday.")
    parser.add_argument("--start",    type=str, default=None,
                        help="Start date for --method fill (format YYYY-MM-DD)")
    args = parser.parse_args()

    station_id = args.id.strip().upper()
    csv_path   = config.DATA_DIR / "mexico_stations.csv"

    # Ensure CSV has Status and Registered columns
    ensure_csv_columns(csv_path)

    # Verify station exists in CSV
    station_row = load_station_row(csv_path, station_id)
    if station_row is None:
        logger.error(f"Station {station_id} not found in {csv_path}. Aborting.")
        return

    city = station_row['CITY'].strip().lower().replace(' ', '-')
    url  = config.BASE_URL.format(city=city, station=station_id)

    if args.register == 'new':
        register_new(station_id, csv_path)
    elif args.register == 'existing':
        if not register_existing(station_id, csv_path):
            return

    # Build date list
    yesterday = datetime.date.today() - datetime.timedelta(days=1)

    if args.method == 'fill':
        if not args.start:
            logger.error("--method fill requires --start YYYY-MM-DD")
            return
        start_date = try_parse_date(args.start)
        if start_date is None:
            logger.error(f"Could not parse start date: {args.start}")
            return
        dates = build_date_list(start_date, yesterday)

    elif args.method == 'refill':
        last_date = get_last_extracted_date(station_id)
        if last_date is None:
            logger.warning(f"[{station_id}] No existing data found. Defaulting to yesterday only.")
            dates = [f"{yesterday.year}-{yesterday.month}-{yesterday.day}"]
        elif last_date >= yesterday:
            logger.info(f"[{station_id}] Already up to date.")
            return
        else:
            start_date = last_date + datetime.timedelta(days=1)
            dates = build_date_list(start_date, yesterday)

    logger.info(f"[{station_id}] Extracting {len(dates)} day(s): {dates[0]} to {dates[-1]}")

    ok_count      = 0
    failed_dates  = []

    for date_str in dates:
        start = time.perf_counter()
        status = extract_with_retry(url, date_str, station_id)
        elapsed = time.perf_counter() - start

        if status == 'ok':
            logger.info(f"[{station_id}] {date_str} OK ({elapsed:.1f}s)")
            ok_count += 1
        else:
            logger.warning(f"[{station_id}] {date_str} -> {status} ({elapsed:.1f}s)")
            failed_dates.append((date_str, status))

    # Debug
    """     
    logger.info(f"{'='*50}")
    logger.info(f"[{station_id}] DONE | OK: {ok_count} | Failed: {len(failed_dates)}")
    for date_str, reason in failed_dates:
        logger.warning(f"  {date_str} -> {reason}")
    logger.info(f"{'='*50}") 
    """


if __name__ == "__main__":
    main()