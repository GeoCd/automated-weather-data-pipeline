# weather-lstm-workflow.py
import os
import csv
import regex as re
import pandas as pd
import numpy as np
from pathlib import Path

from src.config import WorkflowConfiguration
config = WorkflowConfiguration()

def load_station_dict(csv_path: Path) -> dict:
    stationDict = {}
    with open(csv_path, mode='r') as f:
        reader = csv.DictReader(f)
        data = list(reader)
    for row in data:
        station_id = row["ICAO"]
        entry = dict(row)
        del entry["ICAO"]
        stationDict[station_id] = entry
    return stationDict

# ------------------------------------------------------------------------------------------------------------
# Scrap to Raw
# ------------------------------------------------------------------------------------------------------------
def run_scrap_to_raw(Id: str):

    temp_df = []
    stationIdDataDir = config.STATIONS_DIR
    stationDict      = load_station_dict(stationIdDataDir)

    scrapDataFolderDir = config.SCRAP_DIR / f"{Id}_scrapdata"
    tablesNames = [f.name for f in scrapDataFolderDir.iterdir() if f.is_file()]

    for name in tablesNames:
        file      = scrapDataFolderDir / name
        daily_df  = pd.read_csv(file, index_col=0)

        name          = Path(name).stem
        fileNameStruct = name.split("_")
        getDate       = fileNameStruct[-1]
        file_date     = pd.to_datetime(getDate, format='%Y-%m-%d')

        daily_df.insert(loc=0, column='Elevation', value=stationDict[Id]['ELEV'])
        daily_df.insert(loc=0, column='Long_num', value=stationDict[Id]['LONG_NUM'])
        daily_df.insert(loc=0, column='Long', value=stationDict[Id]['LONG'])
        daily_df.insert(loc=0, column='Lat_num', value=stationDict[Id]['LAT_NUM'])
        daily_df.insert(loc=0, column='Lat', value=stationDict[Id]['LAT'])
        daily_df.insert(loc=0, column='City',    value=stationDict[Id]['CITY'].capitalize())
        daily_df.insert(loc=0, column='State',   value=stationDict[Id]['STATE'])
        daily_df.insert(loc=0, column='Country', value=stationDict[Id]['COUNTRY'])
        daily_df.insert(loc=0, column='Code',    value=stationDict[Id]['IATA'])
        daily_df.insert(loc=0, column='Station', value=Id)

        daily_df.insert(loc=0, column='Time_24',
                        value=pd.to_datetime(daily_df['Time'], format='%I:%M %p').dt.strftime('%H:%M'))
        daily_df.insert(loc=0, column='Date',     value=getDate)
        daily_df.insert(loc=0, column='DateTime',
                        value=pd.to_datetime(file_date.strftime('%Y-%m-%d') + ' ' + daily_df['Time_24'],
                                             format='%Y-%m-%d %H:%M'))

        daily_df.drop(labels=['Time_24'], axis=1, inplace=True)

        for label in config.LABELS:
            daily_df[label] = daily_df[label].astype(str).apply(lambda x: re.sub(r"[^0-9\.-]", "", x))
            if label == 'Pressure' or label == 'Precip.':
                daily_df[label] = daily_df[label].astype(float)
            else:
                daily_df[label] = daily_df[label].astype(int)

        temp_df.append(daily_df.reset_index(drop=True))

    history_df = pd.concat(temp_df, ignore_index=True, sort=False)

    history_df.rename(columns={'Temperature': 'Temperature(F)'},   inplace=True)
    history_df.rename(columns={'Dew Point':   'Dew Point(F)'},     inplace=True)
    history_df.rename(columns={'Humidity':    'Humidity(%)'},      inplace=True)
    history_df.rename(columns={'Wind Speed':  'Wind Speed(mph)'},  inplace=True)
    history_df.rename(columns={'Wind Gust':   'Wind Gust(mph)'},   inplace=True)
    history_df.rename(columns={'Pressure':    'Pressure(in)'},     inplace=True)
    history_df.rename(columns={'Precip.':     'Precipitation(in)'},inplace=True)

    outputDir = config.RAW_DIR / f"{Id}_raw.csv"
    history_df.to_csv(outputDir, index=False)

# ------------------------------------------------------------------------------------------------------------
# Raw to Clean
# ------------------------------------------------------------------------------------------------------------
def load_raw_data(csvPath: str = None) -> pd.DataFrame:
    path = csvPath or config.RAW_CSV
    df = pd.read_csv(path)
    df["DateTime"] = pd.to_datetime(df["DateTime"])
    df = df.set_index("DateTime").sort_index()
    return df


def remove_outliers(df: pd.DataFrame) -> pd.DataFrame:
    df = df[(df["Temperature(F)"] >= config.TEMP_MIN) & (df["Temperature(F)"] <= config.TEMP_MAX)]
    df = df[(df["Pressure(in)"]   >= config.PRES_MIN) & (df["Pressure(in)"]   <= config.PRES_MAX)]
    df = df[(df["Humidity(%)"]    >= config.HUM_MIN)  & (df["Humidity(%)"]    <= config.HUM_MAX)]
    df = df[df["Wind Speed(mph)"] <= config.WIND_MAX]
    df.drop(labels=['Precipitation(in)'], axis=1, inplace=True)
    return df


def resample_hourly(df: pd.DataFrame, Id: str) -> pd.DataFrame:
    stationIdDataDir = config.DATA_DIR / "mexico_stations.csv"
    stationDict      = load_station_dict(stationIdDataDir)

    numeric   = df.select_dtypes(include="number")
    resampled = numeric.resample("h").mean()
    resampled = resampled.interpolate(method="time", limit=6)

    cat_cols  = ['Wind', 'Condition']
    existing  = [c for c in cat_cols if c in df.columns]
    if existing:
        categorical = df[existing].resample("h").agg(
            lambda x: x.dropna().mode().iloc[0] if len(x.dropna()) > 0 else np.nan
        )
        categorical = categorical.ffill(limit=6)
        resampled = pd.concat([resampled, categorical], axis=1)

    resampled.insert(loc=0, column='City',    value=stationDict[Id]['CITY'].capitalize())
    resampled.insert(loc=0, column='State',   value=stationDict[Id]['STATE'])
    resampled.insert(loc=0, column='Country', value=stationDict[Id]['COUNTRY'])
    resampled.insert(loc=0, column='Code',    value=stationDict[Id]['IATA'])
    resampled.insert(loc=0, column='Station', value=Id)

    return resampled


def append_new_clean(existingPath: str, newCsvPath: str, Id: str) -> pd.DataFrame:
    existing = pd.read_csv(existingPath, index_col="DateTime", parse_dates=True)
    newRaw   = load_raw_data(newCsvPath)
    newRaw   = remove_outliers(newRaw)
    newRaw   = resample_hourly(newRaw, Id)   # bug fix: Id was missing here
    combined = pd.concat([existing, newRaw])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined

# ------------------------------------------------------------------------------------------------------------
# Single station workflow
# ------------------------------------------------------------------------------------------------------------
def run_workflow(id: str, mode: str = None) -> pd.DataFrame:

    if not config.RAW_DIR.is_dir():
        os.makedirs(config.RAW_DIR, exist_ok=True)
        print(f"Created Folder for Raw Dataset")

    if not config.CLEAN_DIR.is_dir():
        os.makedirs(config.CLEAN_DIR, exist_ok=True)
        print(f"Created Folder for Clean Dataset")

    mode = mode or config.PIPELINE_MODE

    run_scrap_to_raw(id)

    cleanInput = config.CLEAN_DIR / f"{id}_clean.csv"
    rawInput   = config.RAW_DIR   / f"{id}_raw.csv"

    if mode == "incremental" and cleanInput.exists():
        print("Mode: incremental")
        df = append_new_clean(cleanInput, rawInput, id)
    else:
        print("Mode: batch")
        df     = load_raw_data(rawInput)
        rawLen = len(df)
        df     = remove_outliers(df)
        df     = resample_hourly(df, id)
        df     = df.dropna()
        print(f"Rows: {rawLen} raw -> {len(df)} after cleaning and resampling")

    cleanOutput = config.CLEAN_DIR / f"{id}_clean.csv"
    df.to_csv(cleanOutput)
    print(f"Clean data saved: {cleanOutput}")

    return df