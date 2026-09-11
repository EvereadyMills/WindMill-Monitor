import os
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import requests

SCADA_LOGIN_URL = "https://www.scadasolution.co.in/scada/scada-login/"
SCADA_PARKVIEW_URL = "https://www.scadasolution.co.in/scada/scada-parkview/"
SCADA_USERNAME = os.environ.get("SCADA_USER")
SCADA_PASSWORD = os.environ.get("SCADA_PASS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATE_FILE = "turbine_states.json"

def send_telegram_alert(htsc_number, status):
    message = f"⚠️ Alert: Status changed!\nHTSC Number : {htsc_number}\nStatus : {status}"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        print("Telegram Response:", response.text)
    except Exception as e:
        print("Telegram Error:", e)

options = webdriver.ChromeOptions()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

try:
    # 1. Login
    driver.get(SCADA_LOGIN_URL)
    time.sleep(3)

    driver.find_element(By.ID, "uname").send_keys(SCADA_USERNAME)
    driver.find_element(By.ID, "password").send_keys(SCADA_PASSWORD)
    driver.find_element(By.NAME, "submit").click()
    
    time.sleep(5)
    
    # 2. Go to Parkview page
    driver.get(SCADA_PARKVIEW_URL)
    time.sleep(6)
    
    current_states = {}
    # Find all turbine elements by looking for text starting with 'SF'
    elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'SF')]")
    
    if elements:
        for el in elements:
            try:
                text = el.text.strip()
                if text.startswith("SF") and len(text) < 15:
                    htsc_number = text
                    
                    # Check background color or attributes of the element or its parent to determine status
                    class_attr = el.get_attribute("class") or ""
                    parent_el = el.find_element(By.XPATH, "./..")
                    parent_class = parent_el.get_attribute("class") or ""
                    parent_style = parent_el.get_attribute("style") or ""
                    
                    combined_info = (class_attr + " " + parent_class + " " + parent_style).lower()
                    
                    # Default status is running, but if it indicates stop/emergency/red/etc.
                    status = "running"
                    if any(keyword in combined_info for keyword in ["stop", "emergency", "pause", "fault", "trip", "off", "red", "danger"]):
                        status = "stop"
                    elif "green" in combined_info or "run" in combined_info:
                        status = "running"
                    
                    current_states[htsc_number] = status
            except:
                continue

    print("Scraped Current States:", current_states)

    # Read previous state
    previous_states = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                previous_states = json.load(f)
            except:
                pass

    print("Previous States from file:", previous_states)

    # Compare changes and send alert
    if previous_states:
        for htsc, current_status in current_states.items():
            prev_status = previous_states.get(htsc)
            if prev_status and prev_status != current_status:
                if current_status in ["pause", "stop", "emergency", "battery", "poweroff"]:
                    send_telegram_alert(htsc, current_status)
    else:
        print("No previous states found for comparison (First run initialization).")

    # Save current state
    with open(STATE_FILE, "w") as f:
        json.dump(current_states, f, indent=4)

    print("Monitor check completed successfully.")

except Exception as e:
    print("An error occurred:", e)
finally:
    driver.quit()
