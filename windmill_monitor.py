import os
import json
import time
import re
import traceback
import requests
from datetime import datetime, timedelta
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

raw_master_data = os.environ.get("MASTER_DATA_JSON")
MASTER_DATA = {}
if raw_master_data:
    try:
        MASTER_DATA = json.loads(raw_master_data)
    except Exception as e:
        print("❌ Error parsing MASTER_DATA_JSON:", e)

STATE_FILE = "turbine_states.json"

if not SCADA_USERNAME or not SCADA_PASSWORD:
    print("❌ ERROR: SCADA_USER or SCADA_PASS is missing in Environment Variables!")
    exit(1)

REPORT_LOG_FILE = "report_log.json"   # remembers which PDF / reports were already sent today

# Status change alert is sent ONLY when the new status is one of these
ALERT_STATUSES = {"running", "power off", "emergency"}


def load_json_file(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"Could not read {path}, starting fresh:", e)
    return {}


def save_json_file(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def send_telegram_alert(full_message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram token/chat_id missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": full_message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=30)
        print("Telegram API Response:", response.text)
        return response.status_code == 200
    except Exception as e:
        print("Telegram Error:", e)
        return False


# ---------------- DGR PDF SENDING FUNCTION ----------------
# Returns True only when the PDF actually reached Telegram.
def send_yesterday_dgr_pdf(session):
    ist = pytz.timezone('Asia/Kolkata')
    yesterday = (datetime.now(ist) - timedelta(days=1)).strftime("%Y-%m-%d")

    url = "https://www.scadasolution.co.in/scada/garden/PdfOut/"

    payload = {
        'pos1': '1',
        'pos2': yesterday,
        'pos3': yesterday,
        'pos4': '4',
        'pos5': '5',
        'pos6': 'ALL-TURBINES',
        'pos7': '1~SF 042~Tamilnadu~Theni~4~850~Renom',
        'pos8': '0',
        'pos9': '0',
        'pdfsub': ''
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.scadasolution.co.in/scada/garden/reports/'
    }
    pdf_filename = f"DGR_Report_{yesterday}.pdf"

    try:
        print(f"📄 Fetching DGR PDF for date: {yesterday}...")
        response = session.post(url, data=payload, headers=headers, timeout=60)
        content = response.content or b""

        # A real PDF always starts with "%PDF" - an HTML error/login page does not
        if response.status_code != 200 or b"%PDF" not in content[:1024]:
            print(f"❌ PDF not ready / invalid response (HTTP {response.status_code}, {len(content)} bytes)")
            return False

        with open(pdf_filename, "wb") as f:
            f.write(content)

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(pdf_filename, "rb") as pdf_file:
            files = {"document": pdf_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": f"📄 <b>ALL-TURBINES Date Report ({yesterday})</b>",
                "parse_mode": "HTML"
            }
            res = requests.post(telegram_url, data=data, files=files, timeout=60)

        if res.status_code == 200:
            print(f"✅ Successfully sent DGR PDF for {yesterday} to Telegram!")
            return True
        print(f"❌ Failed to send PDF to Telegram: {res.text}")
        return False
    except Exception as e:
        print(f"❌ Error while fetching/sending PDF: {e}")
        return False
    finally:
        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)
# ---------------------------------------------------------

def normalize_status(raw_status, bg_color=""):
    s = str(raw_status).strip().lower()
    
    if "emerg" in s:
        return "Emergency"
    elif "pause" in s:
        return "Pause"
    elif "stop" in s:
        return "Stop"
    elif "batt" in s:
        return "Battery"
    elif "power" in s or "off" in s:
        return "Power Off"
    elif "disp" in s or ("connect" in s and "connectivity" not in s):
        return "Display Connected"
    elif "run" in s:
        return "Running"
        
    bg = bg_color.lower()
    if "230, 0, 0" in bg or "255, 0, 0" in bg or "red" in bg:
        return "Emergency"
    elif "230, 204, 0" in bg or "yellow" in bg or "orange" in bg:
        return "Stop"
    elif "135, 206" in bg or "100, 149" in bg or "cyan" in bg or "lightblue" in bg or "sky" in bg or "110, 180" in bg:
        return "Power Off"
    elif "0, 0, 255" in bg or "blue" in bg:
        return "Pause"
    elif "0, 128, 0" in bg or "green" in bg:
        return "Running"
        
    return "Emergency" if s == "0" else raw_status

def format_clean_message(data):
    sorted_keys = sorted(data.keys(), key=lambda k: MASTER_DATA.get(k, {}).get("order", 99))
    
    current_location = ""
    lines = []

    for key in sorted_keys:
        item = data[key]
        loc = item.get("location", "-")
        order = item.get("order", "-")

        if loc != current_location:
            current_location = loc
            lines.append(f"📍 <b>Location: {current_location}</b>\n")

        lines.append(f"{order}. Loc.No  : <b>{item['name']}</b>")
        lines.append(f"   HTSC.No : {item['htsc']}")
        lines.append(f"   Status  : {item['status']}")
        lines.append(f"   w/s     : {item['ws']}")
        lines.append(f"   kw      : {item['kw']}")
        lines.append(f"   RRPM    : {item['rrpm']}")
        lines.append(f"   GRPM    : {item['grpm']}\n")

    return "\n".join(lines)

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

    # Session Transfer from Selenium to Requests
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie['name'], cookie['value'])

    # Time Calculation
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    today_str = now_ist.strftime("%Y-%m-%d")
    report_log = load_json_file(REPORT_LOG_FILE)

    # ⏰ 1. Yesterday's DGR PDF - MORNING ONLY, once per day.
    #    First run between 8:00 AM and 11:59 AM IST (works even if GitHub starts late).
    #    If it fails, the next morning run tries again.
    if 8 <= now_ist.hour < 12 and report_log.get("pdf_date") != today_str:
        print("⏰ Today's DGR PDF not sent yet. Sending now...")
        if send_yesterday_dgr_pdf(session):
            report_log["pdf_date"] = today_str
            save_json_file(REPORT_LOG_FILE, report_log)
        time.sleep(3)  # let the PDF request finish before Selenium continues

    print("3. Navigating to Parkview Page...")
    driver.get(SCADA_PARKVIEW_URL)
    time.sleep(12)

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    if iframes:
        driver.switch_to.frame(0)
        time.sleep(3)

    print("4. Identifying Windmill Numbers...")
    
    body_text = driver.find_element(By.TAG_NAME, "body").text
    sf_names = list(set(re.findall(r'SF\s*\d+', body_text)))
    sf_names = [re.sub(r'\s+', ' ', name) for name in sf_names]

    print(f"Total Windmills Found: {len(sf_names)} -> {sf_names}")

    current_data = {}
    actions = ActionChains(driver)

    for htsc_number in sf_names:
        status = "-"
        ws = "-"
        kw = "-"
        rrpm = "-"
        grpm = "-"
        bg_color = ""

        master_info = MASTER_DATA.get(htsc_number, {"location": "-", "htsc": "-", "order": 99})

        for attempt in range(3):
            try:
                elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{htsc_number}')]")
                if not elements:
                    break
                
                el = elements[0]
                try:
                    bg_color = el.value_of_css_property("background-color")
                except:
                    bg_color = ""

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(0.5)

                try:
                    actions.move_to_element(el).perform()
                except:
                    pass

                driver.execute_script("""
                    var elem = arguments[0];
                    var events = ['mouseover', 'mouseenter', 'mousemove'];
                    events.forEach(function(evt) {
                        var event = new MouseEvent(evt, {
                            'view': window,
                            'bubbles': true,
                            'cancelable': true
                        });
                        elem.dispatchEvent(event);
                    });
                """, el)
                
                time.sleep(2.5)

                popups = driver.find_elements(By.XPATH, "//*[contains(text(), 'Status') or contains(text(), 'KW') or contains(text(), 'W/S') or contains(text(), 'RRPM') or contains(text(), 'GRPM') or contains(text(), 'RPM')]")
                
                for pop in popups:
                    try:
                        p_text = pop.text.strip()
                        if p_text:
                            lines = p_text.split("\n")
                            for line in lines:
                                line_clean = line.strip()
                                if "Status" in line_clean and ":" in line_clean:
                                    status = line_clean.split(":")[-1].strip()
                                elif ("W/S" in line_clean or "w/s" in line_clean) and ":" in line_clean:
                                    ws = line_clean.split(":")[-1].strip()
                                elif ("KW" in line_clean or "kw" in line_clean) and ":" in line_clean:
                                    kw = line_clean.split(":")[-1].strip()
                                elif ("RRPM" in line_clean or "R/RPM" in line_clean) and ":" in line_clean:
                                    rrpm = line_clean.split(":")[-1].strip()
                                elif ("GRPM" in line_clean or "G/RPM" in line_clean or "Gen RPM" in line_clean) and ":" in line_clean:
                                    grpm = line_clean.split(":")[-1].strip()
                    except:
                        continue

                status = normalize_status(status, bg_color)
                break

            except Exception as retry_err:
                time.sleep(1)

        current_data[htsc_number] = {
            "name": htsc_number,
            "status": status,
            "ws": ws,
            "kw": kw,
            "rrpm": rrpm,
            "grpm": grpm,
            "location": master_info.get("location", "-"),
            "htsc": master_info.get("htsc", "-"),
            "order": master_info.get("order", 99)
        }

    print("Detected Current Data:", current_data)

    # Previous State Reading
    previous_states = load_json_file(STATE_FILE)
    new_state = dict(current_data)

    # ⚠️ 2. Status change -> separate message for EACH changed windmill only,
    #       when the new status is Running / Power Off / Emergency,
    #       or when the windmill stops Running
    if previous_states:
        for htsc, val in current_data.items():
            prev = previous_states.get(htsc)
            if not isinstance(prev, dict):
                continue  # new windmill - just remember it
            prev_status = str(prev.get("status", "-")).strip()
            new_status = str(val["status"]).strip()

            if new_status in ("", "-"):
                new_state[htsc] = prev  # could not read it this run - keep last value
                continue
            if prev_status.lower() == new_status.lower():
                continue

            print(f"Status change detected for {htsc}: {prev_status} -> {new_status}")
            # Message if the NEW status is Running / Power Off / Emergency,
            # OR the windmill has just LEFT Running (e.g. Running -> Stop)
            if new_status.lower() not in ALERT_STATUSES and prev_status.lower() != "running":
                print("   (not Running / Power Off / Emergency - no message)")
                continue
            if not send_telegram_alert(format_clean_message({htsc: val})):
                new_state[htsc] = prev  # keep old, so next run re-sends this alert
    else:
        print("First run - saving state only.")

    # 📊 3. Daily report - all windmills in ONE message, once at 8 AM and once at 6 PM
    report_slot = None
    if now_ist.hour >= 18 and report_log.get("evening_report") != today_str:
        report_slot = "evening_report"
    elif 8 <= now_ist.hour < 18 and report_log.get("morning_report") != today_str:
        report_slot = "morning_report"

    if report_slot and current_data:
        print(f"Sending {report_slot.replace('_', ' ')}...")
        if send_telegram_alert(format_clean_message(current_data)):
            report_log[report_slot] = today_str
            save_json_file(REPORT_LOG_FILE, report_log)

    # Save current state
    if current_data:
        save_json_file(STATE_FILE, new_state)

    print("Monitor execution completed successfully.")

except Exception as e:
    print("An error occurred during execution:")
    traceback.print_exc()
finally:
    driver.quit()
