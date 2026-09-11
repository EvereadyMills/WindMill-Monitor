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

# Credentials Validation
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

    current_states = {}
    
    print("4. Searching Windmill Elements & Hovering for Data...")
    elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'SF')]") or []
    actions = ActionChains(driver)
    
    for el in elements:
        try:
            text = el.text.strip()
            if text.startswith("SF") and len(text) <= 10:
                htsc_number = text
                
                # 1. Detect Status from Background CSS
                try:
                    bg_color = el.value_of_css_property("background-color")
                    parent = el.find_element(By.XPATH, "./..")
                    parent_bg = parent.value_of_css_property("background-color")
                    combined_info = f"{bg_color} {parent_bg} {el.get_attribute('style')} {parent.get_attribute('style')}".lower()
                except:
                    combined_info = ""

                status = "running"
                if "230, 0, 0" in combined_info or "red" in combined_info or "e60000" in combined_info:
                    status = "Emergency"
                elif "230, 204, 0" in combined_info or "yellow" in combined_info or "e6cc00" in combined_info:
                    status = "stop"
                elif "pause" in combined_info or "7c9fae" in combined_info:
                    status = "pause"
                elif "poweroff" in combined_info or "6ec1fa" in combined_info:
                    status = "poweroff"
                elif "black" in combined_info or "battery" in combined_info:
                    status = "Battery"
                elif "green" in combined_info or "0, 138, 0" in combined_info or "008a00" in combined_info:
                    status = "running"

                # 2. Hover to read Tooltip values
                actions.move_to_element(el).perform()
                time.sleep(1)

                ws, kw, rrpm, grpm = "-", "-", "-", "-"
                try:
                    tooltips = driver.find_elements(By.XPATH, "//*[contains(text(), 'W/S') or contains(text(), 'KW')]")
                    for tt in tooltips:
                        if tt.is_displayed():
                            lines = tt.text.split("\n")
                            for line in lines:
                                if "Status:" in line:
                                    status = line.split("Status:")[1].strip()
                                elif "W/S" in line:
                                    ws = line.split(":")[-1].strip()
                                elif "KW" in line:
                                    kw = line.split(":")[-1].strip()
                                elif "RRPM" in line:
                                    rrpm = line.split(":")[-1].strip()
                                elif "GRPM" in line:
                                    grpm = line.split(":")[-1].strip()
                            break
                except Exception as hover_err:
                    print(f"Hover error for {htsc_number}:", hover_err)

                current_states[htsc_number] = {
                    "status": status,
                    "ws": ws,
                    "kw": kw,
                    "rrpm": rrpm,
                    "grpm": grpm
                }
        except Exception:
            continue

    print("Detected Current States:", current_states)

    previous_states = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    previous_states = loaded_data
        except Exception as read_err:
            print("Fresh start:", read_err)

    # Check if status has changed
    state_changed = False

    if previous_states:
        for htsc, data in current_states.items():
            prev = previous_states.get(htsc)
            prev_status = prev.get("status") if isinstance(prev, dict) else prev
            if prev_status != data["status"]:
                state_changed = True
                print(f"Status change detected for {htsc}: {prev_status} -> {data['status']}")
                break
    else:
        state_changed = True

    # IST Time Check for 8:00 AM & 6:00 PM Reports
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    is_scheduled_report = (now_ist.hour in [8, 18]) and (now_ist.minute < 15)

    # Send Notification if Status Changed or Scheduled Report Time reached
    if (state_changed or is_scheduled_report) and current_states:
        msg_lines = ["```text"]
        for index, (htsc, val) in enumerate(current_states.items(), start=1):
            msg_lines.append(
                f"{index}. Loc.No      : {htsc}\n"
                f"   Status        : {val['status']}\n"
                f"   w/s           : {val['ws']}\n"
                f"   kw            : {val['kw']}\n"
                f"   RRPM          : {val['rrpm']}\n"
                f"   GRPM          : {val['grpm']}\n"
            )
        msg_lines.append("```")

        full_message = "\n".join(msg_lines)
        print("Sending aggregated Telegram notification...")
        send_telegram_alert(full_message)

    # Save updated states
    if current_states:
        with open(STATE_FILE, "w") as f:
            json.dump(current_states, f, indent=4)

    print("Monitor execution completed successfully.")

except Exception as e:
    print("An error occurred during execution:")
    traceback.print_exc()
finally:
    driver.quit()
