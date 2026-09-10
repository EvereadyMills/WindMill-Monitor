import os
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import requests

SCADA_URL = "https://www.scadasolution.co.in/scada/scada-login/"
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
        requests.post(url, json=payload)
    except Exception as e:
        print("Telegram Error:", e)

options = webdriver.ChromeOptions()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

try:
    driver.get(SCADA_URL)
    time.sleep(3)

    driver.find_element(By.ID, "uname").send_keys(SCADA_USERNAME)
    driver.find_element(By.ID, "password").send_keys(SCADA_PASSWORD)
    driver.find_element(By.NAME, "submit").click()
    
    time.sleep(8) # Wait for dashboard to load
    
    # Continuous monitoring loop running every 10 seconds
    while True:
        try:
            driver.refresh() # Refresh the page
            time.sleep(4)    # Wait for data to load
            
            current_states = {}
            turbine_rows = driver.find_elements(By.XPATH, "//table//tr[position()>1]")
            
            for row in turbine_rows:
                try:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) >= 2:
                        htsc_number = cols[0].text.strip()
                        status = cols[1].text.strip().lower()
                        if htsc_number:
                            current_states[htsc_number] = status
                except:
                    continue

            # Read previous state
            previous_states = {}
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    try:
                        previous_states = json.load(f)
                    except:
                        pass

            # Compare changes and send alert
            if previous_states:
                for htsc, current_status in current_states.items():
                    prev_status = previous_states.get(htsc)
                    if prev_status and prev_status != current_status:
                        if current_status in ["pause", "stop", "emergency", "battery", "poweroff"]:
                            send_telegram_alert(htsc, current_status)

            # Save current state
            with open(STATE_FILE, "w") as f:
                json.dump(current_states, f)

            print("Check completed. Waiting 10 seconds...")
            
        except Exception as inner_e:
            print("Loop error:", inner_e)

        time.sleep(10) # Wait precisely 10 seconds

except Exception as e:
    print("An error occurred:", e)
finally:
    driver.quit()
