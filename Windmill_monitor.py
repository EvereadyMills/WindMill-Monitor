import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import requests

# 1. SCADA லாகின் விவரங்கள்
SCADA_URL = "https://www.scadasolution.co.in/scada/scada-login/"
SCADA_USERNAME = "eveready"
SCADA_PASSWORD = "ESMPL@123"

# 2. டெலிகிராம் விவரங்கள்
TELEGRAM_BOT_TOKEN = "8970098552:AAFv8vxUVDlaw5gEF_lYyLiO5na0-yEznIc"
TELEGRAM_CHAT_ID = "-1004427021048"  # மைனஸ் குறியுடன் (எ.கா: -100xxxxxxxxxx)

# பிரவுசரைத் திறத்தல்
options = webdriver.ChromeOptions()
# options.add_argument("--headless") # பிரவுசர் தெரியாமல் பின்னணியில் ஓட இதிலுள்ள கமெண்டை நீக்கலாம்
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
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print(f"Telegram Alert Sent: {status_name} -> {count}")
        else:
            print("Telegram Error:", response.text)
    except Exception as e:
            print("Connection Error:", e)

try:
    driver.get(SCADA_URL)
    time.sleep(2)

    # ஆட்டோமேட்டிக் லாகின்
    driver.find_element(By.ID, "uname").send_keys(SCADA_USERNAME)
    driver.find_element(By.ID, "password").send_keys(SCADA_PASSWORD)
    driver.find_element(By.NAME, "submit").click()
    
    print("வெற்றிகரமாக லாகின் செய்யப்பட்டது! விண்டுமில் நிலைகள் கண்காணிக்கப்படுகின்றன...")
    time.sleep(10) # டேஷ்போர்ட் லோட் ஆக அவகாசம்
    
    previous_counts = {}

    while True:
        try:
            # மேல்பகுதியில் உள்ள அனைத்து ஸ்டேட்டஸ் கவுண்ட்டுகளையும் எடுத்தல் (<font> டேக்குகள்)
            status_elements = driver.find_elements(By.XPATH, "//div[@class='image_menu']//font")
            
            current_counts = {}
            for elem in status_elements:
                text = elem.text.strip() # எ.கா: "Running:10" அல்லது "Stop:0"
                if ":" in text:
                    parts = text.split(":")
                    status_name = parts[0].strip() # Running, Pause, Stop, Emergency, முதலியவை
                    status_count = int(parts[1].strip()) # 10, 0, முதலியவை
                    current_counts[status_name] = status_count

            # முந்தைய நிலையும் தற்போதைய நிலையும் ஒப்பிடுதல்
            if previous_counts:
                for status, count in current_counts.items():
                    prev_count = previous_counts.get(status, 0)
                    
                    # 'Running' தவிர மற்ற ஸ்டேட்டஸ்கள் (Pause, Stop, Emergency, Battery, Power Off) அதிகரித்தால் அலர்ட் அனுப்பும்
                    if status != "Running" and count > prev_count:
                        print(f"மாற்றம் கண்டறியப்பட்டது: {status} எண்ணிக்கை {prev_count} லிருந்து {count} ஆக உயர்ந்துள்ளது!")
                        send_telegram_alert(status, count)
                    
                    # அல்லது Running எண்ணிக்கை குறைந்தாலும் அலர்ட் பெறலாம்
                    elif status == "Running" and count < prev_count:
                        print(f"Running எண்ணிக்கை குறைந்துள்ளது: {count}")
                        send_telegram_alert("Running Decreased", count)

            previous_counts = current_counts
                
        except Exception as inner_e:
            print("Loop Error:", inner_e)
            
        # ஒவ்வொரு 60 வினாடிகளுக்கு ஒருமுறை செக் செய்யும்
        time.sleep(60)

except Exception as e:
    print("An error occurred:", e)
finally:
    driver.quit()
