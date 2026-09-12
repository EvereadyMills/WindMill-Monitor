import os
import json
import time
import traceback
import requests
from datetime import datetime
import pytz
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains

SCADA_LOGIN_URL = "https://www.scadasolution.co.in/scada/scada-login/"
SCADA_PARKVIEW_URL = "https://www.scadasolution.co.in/scada/scada-parkview/"

SCADA_USERNAME = os.environ.get("SCADA_USER")
SCADA_PASSWORD = os.environ.get("SCADA_PASS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATE_FILE = "turbine_states.json"

if not SCADA_USERNAME or not SCADA_PASSWORD:
    print("❌ ERROR: SCADA_USER or SCADA_PASS is missing in Environment Variables!")
    exit(1)

def send_telegram_alert(full_message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram token/chat_id missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": full_message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        print("Telegram API Response:", response.text)
    except Exception as e:
        print("Telegram Error:", e)

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

    uname_field = driver.find_element(By.ID, "uname")
    uname_field.clear()
    uname_field.send_keys(str(SCADA_USERNAME))

    pass_field = driver.find_element(By.ID, "password")
    pass_field.clear()
    pass_field.send_keys(str(SCADA_PASSWORD))

    driver.find_element(By.NAME, "submit").click()
    print("2. Logged in successfully.")
    
    time.sleep(6)
    
    print("3. Navigating to Parkview Page...")
    driver.get(SCADA_PARKVIEW_URL)
    time.sleep(8)

    current_data = {}
    
    print("4. Searching Windmill Elements & Fetching Live Popup Data...")
    elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'SF')]") or []
    actions = ActionChains(driver)

    for el in elements:
        try:
            text = el.text.strip()
            if text.startswith("SF") and len(text) <= 10:
                htsc_number = text

                # 1. ActionChains Hover on SF element
                actions.move_to_element(el).perform()
                time.sleep(1.5)  # Live data refresh aaga small wait

                status = "-"
                ws = "-"
                kw = "-"
                rrpm = "-"
                grpm = "-"

                # 2. Extract Data from Dark Grey Popup Box
                try:
                    # Finds elements containing SCADA parameters
                    popup_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Status:') or contains(text(), 'W/S') or contains(text(), 'KW')]")
                    
                    for pop in popup_elements:
                        if pop.is_displayed():
                            lines = pop.text.split("\n")
                            for line in lines:
                                l_str = line.strip()
                                if "Status:" in l_str or "Status :" in l_str:
                                    status = l_str.split(":")[-1].strip()
                                elif "W/S" in l_str or "w/s" in l_str:
                                    ws = l_str.split(":")[-1].strip()
                                elif "KW" in l_str or "kw" in l_str:
                                    kw = l_str.split(":")[-1].strip()
                                elif "RRPM" in l_str:
                                    rrpm = l_str.split(":")[-1].strip()
                                elif "GRPM" in l_str:
                                    grpm = l_str.split(":")[-1].strip()
                            break
                except Exception as hover_err:
                    print(f"Hover extract error for {htsc_number}:", hover_err)

                # Fallback: Color-based status detection if popup status is missing
                if status == "-":
                    try:
                        bg_color = el.value_of_css_property("background-color")
                        parent = el.find_element(By.XPATH, "./..")
                        parent_bg = parent.value_of_css_property("background-color")
                        combined = f"{bg_color} {parent_bg} {el.get_attribute('style')} {parent.get_attribute('style')}".lower()

                        if "230, 0, 0" in combined or "red" in combined or "e60000" in combined:
                            status = "Emergency"
                        elif "230, 204, 0" in combined or "yellow" in combined or "e6cc00" in combined:
                            status = "stop"
                        elif "pause" in combined or "7c9fae" in combined:
                            status = "pause"
                        elif "poweroff" in combined or "6ec1fa" in combined:
                            status = "poweroff"
                        elif "black" in combined or "battery" in combined:
                            status = "Battery"
                        else:
                            status = "Running"
                    except:
                        status = "Running"

                current_data[htsc_number] = {
                    "status": status,
                    "ws": ws,
                    "kw": kw,
                    "rrpm": rrpm,
                    "grpm": grpm
                }
        except Exception:
            continue

    print("Detected Current Data:", current_data)

    # Read Previous Turbine States
    previous_states = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    previous_states = loaded_data
        except Exception as read_err:
            print("Fresh start:", read_err)

    # State Change Check
    state_changed = False
    if previous_states:
        for htsc, val in current_data.items():
            prev = previous_states.get(htsc)
            prev_status = prev.get("status") if isinstance(prev, dict) else prev
            if prev_status != val["status"]:
                state_changed = True
                print(f"Status change detected for {htsc}: {prev_status} -> {val['status']}")
                break
    else:
        state_changed = True

    # Check 8:00 AM and 6:00 PM IST Schedule Time
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    is_scheduled_report = (now_ist.hour in [8, 18]) and (now_ist.minute < 15)

    # Send Aggregated Telegram Message in Required Format
    if (state_changed or is_scheduled_report) and current_data:
        msg_lines = ["```text"]
        for index, (htsc, val) in enumerate(current_data.items(), start=1):
            msg_lines.append(
                f"{index}. Loc.No   : {htsc}\n"
                f"   Status   : {val['status']}\n"
                f"   w/s      : {val['ws']}\n"
                f"   kw       : {val['kw']}\n"
                f"   RRPM     : {val['rrpm']}\n"
                f"   GRPM     : {val['grpm']}\n"
            )
        msg_lines.append("```")

        full_message = "\n".join(msg_lines)
        print("Sending aggregated Telegram notification...")
        send_telegram_alert(full_message)

    # Save Current State Cache
    if current_data:
        with open(STATE_FILE, "w") as f:
            json.dump(current_data, f, indent=4)

    print("Monitor execution completed successfully.")

except Exception as e:
    print("An error occurred during execution:")
    traceback.print_exc()
finally:
    driver.quit()
