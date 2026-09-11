import os
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import requests

SCADA_LOGIN_URL = "https://www.scadasolution.co.in/scada/scada-login/"
SCADA_PARKVIEW_URL = "https://www.scadasolution.co.in/scada/scada-parkview/"
SCADA_USERNAME = os.environ.get("SCADA_USER")
SCADA_PASSWORD = os.environ.get("SCADA_PASS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATE_FILE = "turbine_states.json"

def send_telegram_alert(htsc_number, status, running_status_summary):
    message = (
        f"Htsc number : {htsc_number}\n"
        f"Status : {status}\n"
        f"Running status: {running_status_summary}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram API Response for {htsc_number}:", response.text)
    except Exception as e:
        print("Telegram Error:", e)

# Configure Chrome with HD Screen Resolution
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(options=chrome_options)

try:
    print("1. Opening Login Page...")
    driver.get(SCADA_LOGIN_URL)
    time.sleep(4)

    driver.find_element(By.ID, "uname").send_keys(SCADA_USERNAME)
    driver.find_element(By.ID, "password").send_keys(SCADA_PASSWORD)
    driver.find_element(By.NAME, "submit").click()
    print("2. Logged in successfully.")
    
    time.sleep(6)
    
    print("3. Navigating to Parkview Page...")
    driver.get(SCADA_PARKVIEW_URL)
    time.sleep(8)  # Wait for AJAX elements to render
    
    # 4. Extract Overall Running Status Summary from Top Bar
    running_summary = "N/A"
    try:
        summary_els = driver.find_elements(By.XPATH, "//*[contains(text(), 'Running') or contains(text(), 'Stop') or contains(text(), 'Emergency')]")
        summary_parts = []
        for s_el in summary_els:
            txt = s_el.text.strip()
            if any(k in txt for k in ["Running", "Stop", "Emergency", "Pause", "Battery", "Power Off"]):
                if txt not in summary_parts and len(txt) < 150:
                    summary_parts.append(txt.replace("\n", " "))
        if summary_parts:
            running_summary = " | ".join(summary_parts[:1])
    except Exception as e:
        print("Error fetching summary counts:", e)

    current_states = {}
    
    # 5. Search all turbine elements (containing 'SF')
    print("4. Searching Windmill Elements...")
    elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'SF')]") or []
    
    for el in elements:
        try:
            text = el.text.strip()
            # Filter turbine tags like 'SF 042', 'SF 244', etc.
            if text.startswith("SF") and len(text) <= 10:
                htsc_number = text
                
                # Check rendered background colors via CSS
                bg_color = ""
                parent = None
                try:
                    bg_color = el.value_of_css_property("background-color")
                    parent = el.find_element(By.XPATH, "./..")
                    parent_bg = parent.value_of_css_property("background-color")
                    combined_info = f"{bg_color} {parent_bg} {el.get_attribute('style')} {parent.get_attribute('style')}".lower()
                except:
                    combined_info = ""

                # Determine status based on color / text
                status = "running"
                if "230, 0, 0" in combined_info or "red" in combined_info or "e60000" in combined_info:
                    status = "emergency"
                elif "230, 204, 0" in combined_info or "yellow" in combined_info or "e6cc00" in combined_info:
                    status = "stop"
                elif "pause" in combined_info or "7c9fae" in combined_info:
                    status = "pause"
                elif "poweroff" in combined_info or "6ec1fa" in combined_info:
                    status = "poweroff"
                elif "black" in combined_info or "battery" in combined_info:
                    status = "battery"
                elif "green" in combined_info or "0, 138, 0" in combined_info or "008a00" in combined_info:
                    status = "running"

                current_states[htsc_number] = status
        except Exception as el_err:
            continue

    print("Detected Current States from Website:", current_states)
    print("Summary Count extracted:", running_summary)

    # 6. Safe Reading of Previous States File
    previous_states = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    previous_states = loaded_data
        except Exception as read_err:
            print("Could not read previous state file, starting fresh:", read_err)
            previous_states = {}

    print("Previous States loaded:", previous_states)

    # 7. Compare Changes & Send Alert
    if previous_states:
        for htsc, current_status in current_states.items():
            prev_status = previous_states.get(htsc)
            if prev_status and prev_status != current_status:
                print(f"CHANGE DETECTED for {htsc}: {prev_status} -> {current_status}")
                send_telegram_alert(htsc, current_status, running_summary)
            elif prev_status is None and current_status != "running":
                # New windmill detected in non-running state
                send_telegram_alert(htsc, current_status, running_summary)
    else:
        print("First run or no previous states. Initializing state file.")
        # If SF 244 is currently stopped/emergency on first run, alert once
        for htsc, current_status in current_states.items():
            if current_status != "running":
                print(f"Initial non-running status detected for {htsc}: {current_status}")
                send_telegram_alert(htsc, current_status, running_summary)

    # 8. Save updated states safely
    if current_states:
        with open(STATE_FILE, "w") as f:
            json.dump(current_states, f, indent=4)

    print("Monitor execution completed successfully.")

except Exception as e:
    print("An error occurred during execution:", e)
finally:
    driver.quit()
