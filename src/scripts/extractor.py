# extractor.py
# Extraction functions from scrap_table.py
# ------------------------------------------------------------------------------------------------------------
# Libraries
# ------------------------------------------------------------------------------------------------------------
import sys, time
import os
import datetime
from io import StringIO
import pandas as pd
import re
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import psutil
import signal

from src.config import WorkflowConfiguration
config = WorkflowConfiguration()
# ------------------------------------------------------------------------------------------------------------
# Functions
# ------------------------------------------------------------------------------------------------------------

def driver_start():
    selenium_options = Options()
    selenium_options.add_argument("--headless=new")
    selenium_options.add_argument("--disable-gpu")
    selenium_options.add_argument("--window-size=1920,1080")
    selenium_options.page_load_strategy = "eager"
    if sys.platform.startswith('linux'):
        service = Service(executable_path="/usr/bin/chromedriver")
    elif sys.platform.startswith('win32'):
        service = Service(ChromeDriverManager().install())
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 1,
        "profile.default_content_setting_values.cookies": 1,
        "download.prompt_for_download": False,
    }
    selenium_options.add_experimental_option("prefs", prefs)
    funct_driver = webdriver.Chrome(service=service, options=selenium_options)
    return funct_driver


def count_chrome_processes():
    return sum(1 for p in psutil.process_iter(['name']) if p.info['name'] in ('chrome.exe', 'chromedriver.exe'))


def kill_selenium_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] in ('chrome.exe', 'chromedriver.exe'):
                print(f"Killing {proc.info['name']} (PID {proc.info['pid']})")
                os.kill(proc.info['pid'], signal.SIGTERM)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def try_parse_date(s):
    COMMON_FORMATS = [
    '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d',
    '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y',
    '%Y %m %d', '%d %m %Y',
    '%Y%m%d', '%d%m%Y',
    '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'
    ]
    s = s.strip()

    for fmt in COMMON_FORMATS:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.date()
        except ValueError:
            pass

    nums = re.findall(r'\d+', s)
    if len(nums) == 3:
        a, b, c = map(int, nums)
        if a >= 1000:
            y, m, d = a, b, c
        elif c >= 1000:
            y, m, d = c, a, b
        else:
            if a > 31:
                y, m, d = a, b, c
            elif c > 31:
                y, m, d = c, a, b
            else:
                y, m, d = a, b, c
        try:
            return datetime.date(y, m, d)
        except ValueError:
            return None
    return None


def expand_date_range(dates_str_list):
    parsed = []
    bad = []
    for s in dates_str_list:
        d = try_parse_date(s)
        if d is None:
            bad.append(s)
        else:
            parsed.append(d)

    if len(parsed) != 2:
        return None

    start, end = parsed
    if start > end:
        start, end = end, start

    cur = start
    dates = []
    while cur <= end:
        dates.append(cur)
        cur = cur + datetime.timedelta(days=1)

    formated = [f"{d.year}-{d.month}-{d.day}" for d in dates]
    return formated


def showcase_get_table(driver, input_URL: str, input_CSS_ELEMENT, input_OUT_FORMAT, input_DATE: str, input_ID):
    try:
        final_URL = input_URL + '/' + input_DATE
        driver.get(final_URL)
        print(final_URL)
        print("Procesos activos:", count_chrome_processes())

        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(.,'Accept') or contains(.,'Aceptar')]")))
            btn.click()
        except Exception:
            pass

        try:
            table_element = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, input_CSS_ELEMENT)))
        except WebDriverException as e:
            with open("error_page.html", "w") as f:
                f.write(driver.page_source)
            print(f"{e}: Saved page source to error_page.html for inspection.")
            return None

        html_table = table_element.get_attribute("outerHTML")
        dfs = pd.read_html(StringIO(html_table))
        if not dfs:
            raise SystemExit("Cannot parse. Check HTML.")
        else:
            df = pd.concat(dfs, axis=1)
            df = df.dropna(how='all')

            scrapDir = config.SCRAP_DIR / f"{input_ID}_scrapdata"
            print(f"SUBTRACTION SUCCESSFUL: {len(df)} rows x {len(df.columns)} columns -> {input_ID}_{input_DATE}.{input_OUT_FORMAT} in {scrapDir}")

            if not scrapDir.is_dir():
                os.makedirs(scrapDir, exist_ok=True)
                print(f"Created Folder for Scraped Data")

            if input_OUT_FORMAT == 'CSV':
                file_path = scrapDir / f"{input_ID}_{input_DATE}.csv"
                if not os.path.exists(file_path):
                    df.to_csv(file_path, index=True)
                else:
                    print(f"{file_path} exists, will not be overwritten.")

            elif input_OUT_FORMAT in ['EXCEL', 'XLSX', 'XLS']:
                file_path = scrapDir / f"{input_ID}_{input_DATE}.xlsx"
                if not os.path.exists(file_path):
                    df.to_excel(file_path, index=True)
                else:
                    print(f"{file_path} exists, will not be overwritten.")

            elif input_OUT_FORMAT == 'XML':
                file_path = scrapDir / f"{input_ID}_{input_DATE}.xml"
                if not os.path.exists(file_path):
                    df.to_xml(file_path, index=True)
                else:
                    print(f"{file_path} exists, will not be overwritten.")

            else:
                file_path = scrapDir / f"{input_ID}_{input_DATE}.csv"
                if not os.path.exists(file_path):
                    print('Not Supported Output Format. Creating a csv document.')
                    df.to_csv(file_path, index=True)
                else:
                    print(f"{file_path} exists, will not be overwritten.")

            while len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                driver.close()
            driver.switch_to.window(driver.window_handles[0])

            try:
                driver.execute_cdp_cmd("Network.clearBrowserCache", {})
            except Exception:
                pass
    finally:
        driver.quit()


def showcase_get_table_mode(mode, URL, CSS_ELEMENT, OUT_FORMAT, DATES, ID):
    if mode == 'SINGLE':
        kill_selenium_processes()
        start_process_counter = time.perf_counter()
        showcase_get_table(driver_start(), URL, CSS_ELEMENT, OUT_FORMAT, DATES[0], ID)
        end_process_counter = time.perf_counter()
        print(f"Execution time: {end_process_counter - start_process_counter:.6f} seconds")

    elif mode == 'MULTIPLE':
        temp_formated = expand_date_range(DATES)
        for current_date in temp_formated:
            kill_selenium_processes()
            start_process_counter = time.perf_counter()
            showcase_get_table(driver_start(), URL, CSS_ELEMENT, OUT_FORMAT, current_date, ID)
            end_process_counter = time.perf_counter()
            print(f"Execution time: {end_process_counter - start_process_counter:.6f} seconds")

    elif mode == 'SELECT':
        for current_date in DATES:
            kill_selenium_processes()
            start_process_counter = time.perf_counter()
            showcase_get_table(driver_start(), URL, CSS_ELEMENT, OUT_FORMAT, current_date, ID)
            end_process_counter = time.perf_counter()
            print(f"Execution time: {end_process_counter - start_process_counter:.6f} seconds")

    kill_selenium_processes()