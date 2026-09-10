import os
import json
import requests

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
        response = requests.post(url, json=payload)
        print(f"Telegram API Response: {response.status_code}, {response.text}")
    except Exception as e:
        print("Telegram Error:", e)

# Dummy turbine data for testing
current_states = {
    "SF042": "stop",      # Will trigger alert
    "SF101": "running",   # Normal (No alert)
    "SF1019": "emergency" # Will trigger alert
}

# Read previous state
previous_states = {}
if os.path.exists(STATE_FILE):
    with open(STATE_FILE, "r") as f:
        try:
            previous_states = json.load(f)
        except:
            pass

# If no previous state exists, set them as "running" so the dummy status changes trigger alerts immediately
if not previous_states:
    previous_states = {
        "SF042": "running",
        "SF101": "running",
        "SF1019": "running"
    }

print("Previous States:", previous_states)
print("Current States:", current_states)

# Compare changes and send alert
for htsc, current_status in current_states.items():
    prev_status = previous_states.get(htsc, "running")
    if prev_status != current_status:
        if current_status in ["pause", "stop", "emergency", "battery", "poweroff"]:
            send_telegram_alert(htsc, current_status)

# Save current state
with open(STATE_FILE, "w") as f:
    json.dump(current_states, f)

print("Dummy test check completed successfully.")
