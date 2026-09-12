import os
import json
import time
import re
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
        "text": full_message
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
    time.sleep(12)

    # If inside iframe, switch frame
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    if iframes:
        driver.switch_to.frame(0)
        time.sleep(3)

    print("4. Identifying Windmill Numbers...")
    
    # Get all text elements from the body
    all_elements = driver.find_elements(By.XPATH, "//*[text()]")
    sf_names = []
    
    for el in all_elements:
        try:
            txt = el.text.strip()
            # SF பக்கத்தில் குறைந்தபட்சம் 2 இலக்க எண் இருக்க வேண்டும் (Eg: SF 042, SF 101)
            matches = re.findall(r'SF\s*\d+', txt)
            for m in matches:
                clean_name = re.sub(r'\s+', ' ', m)
                if clean_name not in sf_names:
                    sf_names.append(clean_name)
        except:
            continue

    print(f"Total Windmills Found: {len(sf_names)} -> {sf_names}")

    current_data = {}
    actions = ActionChains(driver)

    for htsc_number in sf_names:
        try:
            # Re-find element to avoid stale exception
            fresh_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{htsc_number}')]")
            if not fresh_elements:
                continue
            
            el = fresh_elements[0]

            # Hover using JavaScript & ActionChains
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(1)
            
            # Hover trigger
            actions.move_to_element(el).perform()
            driver.execute_script("var evObj = document.createEvent('MouseEvents'); evObj.initEvent('mouseover', true, false); arguments[0].dispatchEvent(evObj);", el)
            
            time.sleep(3) # Wait for live popup numbers

            status = "-"
            ws = "-"
            kw = "-"
            rrpm = "-"
            grpm = "-"

            # Extract popup values from active popups / tooltips
            try:
                popups = driver.find_elements(By.XPATH, "//*[contains(text(), 'Status') or contains(text(), 'W/S') or contains(text(), 'KW') or contains(text(), 'RRPM')]")
                for pop in popups:
                    if pop.is_displayed():
                        lines = pop.text.split("\n")
                        for line in lines:
                            l_str = line.strip()
                            if "Status" in l_str:
                                status = l_str.split(":")[-1].strip()
                            elif "W/S" in l_str or "w/s" in l_str:
                                ws = l_str.split(":")[-1].strip()
                            elif "KW" in l_str or "kw" in l_str:
                                kw = l_str.split(":")[-1].strip()
                            elif "RRPM" in l_str:
                                rrpm = l_str.split(":")[-1].strip()
                            elif "GRPM" in l_str:
                                grpm = l_str.split(":")[-1].strip()
                        if status != "-" or ws != "-":
                            break
            except Exception as h_err:
                print(f"Hover extract error on {htsc_number}:", h_err)

            # Color fallback if status is missing
            if status == "-":
                try:
                    bg = el.value_of_css_property("background-color")
                    if "230, 0, 0" in bg or "red" in bg:
                        status = "Emergency"
                    elif "230, 204, 0" in bg or "yellow" in bg:
                        status = "stop"
                    else:
                        status = "running"
                except:
                    status = "running"

            current_data[htsc_number] = {
                "status": status,
                "ws": ws,
                "kw": kw,
                "rrpm": rrpm,
                "grpm": grpm
            }
        except Exception as err:
            print(f"Error processing {htsc_number}:", err)
            continue

    print("Detected Current Data:", current_data)

    # Previous State Reading
    previous_states = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    previous_states = loaded_data
        except Exception as read_err:
            print("Fresh start:", read_err)

    # Change Detection
    state_changed = False
    if previous_states:
        for htsc, val in current_data.items():
            prev = previous_states.get(htsc)
            prev_status = prev.get("status") if isinstance(prev, dict) else prev
            if str(prev_status).lower() != str(val["status"]).lower():
                state_changed = True
                print(f"Status change detected for {htsc}: {prev_status} -> {val['status']}")
                break
    else:
        state_changed = True

    # Schedule Check
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    is_scheduled_report = (now_ist.hour in [8, 18]) and (now_ist.minute < 15)

    # Plain text format message
    if (state_changed or is_scheduled_report) and current_data:
        msg_lines = []
        for index, (htsc, val) in enumerate(current_data.items(), start=1):
            msg_lines.append(
                f"{index}. Loc.No   : {htsc}\n"
                f"   Status   : {val['status']}\n"
                f"   w/s      : {val['ws']}\n"
                f"   kw       : {val['kw']}\n"
                f"   RRPM     : {val['rrpm']}\n"
                f"   GRPM     : {val['grpm']}\n"
            )

        full_message = "\n".join(msg_lines)
        print("Sending aggregated Telegram notification...")
        send_telegram_alert(full_message)

    # Save state
    if current_data:
        with open(STATE_FILE, "w") as f:
            json.dump(current_data, f, indent=4)

    print("Monitor execution completed successfully.")

except Exception as e:
    print("An error occurred during execution:")
    traceback.print_exc()
finally:
    driver.quit()
