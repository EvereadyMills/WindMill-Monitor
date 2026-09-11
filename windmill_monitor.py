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

def send_telegram_alert(htsc_number, status, summary_counts):
    message = f"Htsc number : {htsc_number}\nStatus : {status}\nRunning status: {summary_counts}"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram Response for {htsc_number}:", response.text)
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
    
    # Extract overall counts from the top menu bar (Running, Pause, Stop, Emergency, etc.)
    summary_counts = "N/A"
    try:
        menu_element = driver.find_element(By.CLASS_NAME, "s_menu")
        summary_counts = menu_element.text.strip().replace("\n", " | ")
    except:
        try:
            # Fallback if class name differs
            menu_element = driver.find_element(By.XPATH, "//div[contains(@style, 'height:30px')]")
            summary_counts = menu_element.text.strip().replace("\n", " | ")
        except:
            pass

    current_states = {}
    elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'SF')]")
    
    for el in elements:
        try:
            text = el.text.strip()
            if text.startswith("SF") and len(text) < 15:
                htsc_number = text
                
                style_attr = el.get_attribute("style") or ""
                parent_el = el.find_element(By.XPATH, "./..")
                parent_style = parent_el.get_attribute("style") or ""
                
                combined_style = (style_attr + " " + parent_style).lower()
                
                # Identify status based on color codes
                status = "running"
                if "e60000" in combined_style or "red" in combined_style or "emergency" in combined_style:
                    status = "emergency"
                elif "e6cc00" in combined_style or "stop" in combined_style or "yellow" in combined_style:
                    status = "stop"
                elif "7c9fae" in combined_style or "pause" in combined_style:
                    status = "pause"
                elif "6ec1fa" in combined_style or "power off" in combined_style or "poweroff" in combined_style:
                    status = "poweroff"
                elif "black" in combined_style or "battery" in combined_style:
                    status = "battery"
                elif "008a00" in combined_style or "green" in combined_style or "run" in combined_style:
                    status = "running"
                    
                current_states[htsc_number] = status
        except:
            continue

    print("Detected Current States:", current_states)
    print("Summary Counts:", summary_counts)

    # Read previous state
    previous_states = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                previous_states = json.load(f)
            except:
                pass

    # Compare and send alert for ANY status change
        # நேரடியாக எல்லா விண்டுமில் ஸ்டேட்டஸையும் மெசேஜ் அனுப்பச் சொல்கிறோம் (டெஸ்டிங்கிற்காக மட்டும்)
    for htsc, current_status in current_states.items():
        if current_status != "running": # Running தவிர மற்ற பிரச்சனை இருந்தால் மட்டும் மெசேஜ் வரும்
            print(f"Alert condition met for {htsc}. Sending alert.")
            send_telegram_alert(htsc, current_status, summary_counts)

    else:
        print("No previous states found. Initializing states.")

    # Save current state
    with open(STATE_FILE, "w") as f:
        json.dump(current_states, f, indent=4)

    print("Monitor check completed successfully.")

except Exception as e:
    print("An error occurred:", e)
finally:
    driver.quit()
