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

# GitHub Secret-இல் இருந்து Master Data-வை பெறுகிறது
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

def send_telegram_alert(full_message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram token/chat_id missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": full_message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload)
        print("Telegram API Response:", response.text)
    except Exception as e:
        print("Telegram Error:", e)

# ---------------- DGR PDF SENDING FUNCTION ----------------
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
    
    try:
        print(f"📄 Fetching DGR PDF for date: {yesterday}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.scadasolution.co.in/scada/garden/reports/'
        }
        
        response = session.post(url, data=payload, headers=headers)
        
        if response.status_code == 200 and len(response.content) > 1000:
            pdf_filename = f"DGR_Report_{yesterday}.pdf"
            
            with open(pdf_filename, "wb") as f:
                f.write(response.content)
            
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
            with open(pdf_filename, "rb") as pdf_file:
                files = {"document": pdf_file}
                data = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": f"📄 <b>ALL-TURBINES Date Report ({yesterday})</b>",
                    "parse_mode": "HTML"
                }
                res = requests.post(telegram_url, data=data, files=files)
                
                if res.status_code == 200:
                    print(f"✅ Successfully sent DGR PDF for {yesterday} to Telegram!")
                else:
                    print(f"❌ Failed to send PDF to Telegram: {res.text}")
            
            if os.path.exists(pdf_filename):
                os.remove(pdf_filename)
        else:
            print("❌ Failed to fetch PDF or empty response.")
            
    except Exception as e:
        print(f"❌ Error while fetching/sending PDF: {e}")
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
    elif "disp" in s or "connect" in s:
        return "Display Connected"
    elif "run" in s:
        return "Running"
        
    bg = bg_color.lower()
    # Red -> Emergency
    if "230, 0, 0" in bg or "255, 0, 0" in bg or "red" in bg:
        return "Emergency"
    # Yellow / Orange -> Stop
    elif "230, 204, 0" in bg or "yellow" in bg or "orange" in bg:
        return "Stop"
    # Light Blue / Cyan / Sky Blue -> Power Off (SF 523 போன்றவற்றுக்கு)
    elif "135, 206" in bg or "100, 149" in bg or "cyan" in bg or "lightblue" in bg or "sky" in bg or "110, 180" in bg:
        return "Power Off"
    # Dark Blue -> Pause
    elif "0, 0, 255" in bg or "blue" in bg:
        return "Pause"
    # Green -> Running
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

    # Time Calculation for Scheduled Actions
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)

    # ⏰ 1. PDF Report Logic: தினமும் காலை 8:00 AM IST (8:00 - 8:30 இடையே) மட்டுமே PDF அனுப்பும்
    if now_ist.hour == 8 and now_ist.minute < 30:
        print("⏰ Morning 8 AM detected. Executing DGR PDF sending task...")
        send_yesterday_dgr_pdf(session)

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
            if str(prev_status).lower() != str(val["status"]).lower():
                state_changed = True
                print(f"Status change detected for {htsc}: {prev_status} -> {val['status']}")
                break
    else:
        state_changed = True

    # Scheduled Check (8 AM & 6 PM IST)
    is_scheduled_report = (now_ist.hour in [8, 18]) and (now_ist.minute < 30)

    # Send Text Notification
    if (state_changed or is_scheduled_report) and current_data:
        full_message = format_clean_message(current_data)
        print("Sending aggregated Telegram notification...")
        send_telegram_alert(full_message)

    # Save current state
    if current_data:
        with open(STATE_FILE, "w") as f:
            json.dump(current_data, f, indent=4)

    print("Monitor execution completed successfully.")

except Exception as e:
    print("An error occurred during execution:")
    traceback.print_exc()
finally:
    driver.quit()
