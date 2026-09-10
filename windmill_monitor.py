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

STATE_FILE = "counts.json"

options = webdriver.ChromeOptions()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

def send_telegram_alert(status_name, count):
    message = f" எச்சரிக்கை: SCADA நிலையில் மாற்றம் ஏற்பட்டுள்ளது!\n நிலவரம்: *{status_name}* \n எண்ணிக்கை: **{count}**"
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

try:
    driver.get(SCADA_URL)
    time.sleep(3)

    driver.find_element(By.ID, "uname").send_keys(SCADA_USERNAME)
    driver.find_element(By.ID, "password").send_keys(SCADA_PASSWORD)
    driver.find_element(By.NAME, "submit").click()
    
    time.sleep(8) # டேஷ்போர்ட் லோட் ஆக
    
    status_elements = driver.find_elements(By.XPATH, "//div[@class='image_menu']//font")
    current_counts = {}
    for elem in status_elements:
        text = elem.text.strip()
        if ":" in text:
            parts = text.split(":")
            status_name = parts[0].strip()
            status_count = int(parts[1].strip())
            current_counts[status_name] = status_count

    # முந்தைய நிலையை ரீட் செய்தல்
    previous_counts = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                previous_counts = json.load(f)
            except:
                pass

    # மாற்றங்களை ஒப்பிடுதல்
    if previous_counts:
        for status, count in current_counts.items():
            prev_count = previous_counts.get(status, 0)
            if status != "Running" and count > prev_count:
                send_telegram_alert(status, count)
            elif status == "Running" and count < prev_count:
                send_telegram_alert("Running Decreased", count)

    # தற்போதைய நிலையை சேமித்தல்
    with open(STATE_FILE, "w") as f:
        json.dump(current_counts, f)

    print("Monitor check completed successfully.")

except Exception as e:
    print("An error occurred:", e)
finally:
    driver.quit()
