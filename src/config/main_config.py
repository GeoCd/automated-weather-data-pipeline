import os
import logging
from pathlib import Path
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@dataclass
class WorkflowConfiguration:

    # Paths
    ROOT_DIR:           Path =  Path(os.getcwd())
    SCRAP_DIR:          Path = ROOT_DIR / "scraped"

    DATA_DIR:           Path = ROOT_DIR / "mx-weather-datasets"
    RAW_DIR:            Path = DATA_DIR / "raw-data"
    CLEAN_DIR:          Path = DATA_DIR / "clean-data"
    STATIONS_DIR:       Path = DATA_DIR / "mexico_stations.csv"

    # Model
    MODEL_DIR:          Path = ROOT_DIR / "models"

    # LSTM
    LOOK_BACK:          int = 24     # hours
    EPOCHS:             int = 50
    BATCH_SIZE:         int = 64
    PATIENCE:           int = 5

    # Scraping Config
    BASE_URL:           str = "https://www.wunderground.com/history/daily/mx/{city}/{station}/date"
    CSS_ELEMENT:        str = "table[mat-table].mat-mdc-table[aria-labelledby='History observation']"
    OUT_FORMAT:         str = "CSV"       
    MAX_RETRIES:        int = 2
    MAX_MISSING_DAYS:   int = 5

    # Data for Training & Analysis
    LABELS:             list[str] = field(default_factory=lambda:   [
                                                                    'Temperature',
                                                                    'Dew Point',
                                                                    'Humidity',
                                                                    'Wind Speed',
                                                                    'Wind Gust',
                                                                    'Pressure',
                                                                    'Precip.'
                                                                    ])

    # Cleaning thresholds
    TEMP_MIN:           int = 20      # °F
    TEMP_MAX:           int = 100     # °F
    PRES_MIN:           int = 22      # inHg
    PRES_MAX:           int = 26      # inHg
    HUM_MIN:            int = 0       # %
    HUM_MAX:            int = 100     # %
    WIND_MAX:           int = 80      # mph

    PIPELINE_MODE:      str = "batch"