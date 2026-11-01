import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = "https://roulette-v11-final.onrender.com/telegram-webhook"

# دالة ترسل رسالة لتليجرام
def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

# تحليل الروليت (مبسط - تقدر تطوره بعدين)
def analyze_numbers(nums):
    red = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    black = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]
    
    last = nums[-1] if nums else 0
    color = "🔴 أحمر" if last in red else "⚫ أسود" if last in black else "🟢 صفر"
    
    text = f"📊 تحليل الروليت:\n"
    text += f"الأرقام: {nums}\n"
    text += f"آخر رقم: {last} - {color}\n\n"
    
    # اقتراح بسيط
    if len(nums) >= 3:
        if nums[-1] % 2 == 0:
            text += "💡 اقتراح: فردي / أحمر"
        else:
            text += "💡 اقتراح: زوجي / أسود"
    else:
        text += "💡 أرسل 3 أرقام على الأقل مثل: 5, 9, 12"
    
    text += "\n\nأرسل رقمين مثل: 8, 12"
    return text

@app.route("/")
def home():
    return "Bot is Live ✅"

@app.route("/telegram-webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        print(f"Incoming: {data}")
        
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            
            # تجاهل /start
            if text.startswith("/start"):
                send_message(chat_id, "أهلاً! أرسل أرقام الروليت مثل:\n5, 9, 12")
                return jsonify({"ok": True})
            
            # حاول تستخرج الأرقام
            try:
                # يسمح بـ "5, 9" أو "5 9" أو "5,9"
                cleaned = text.replace(",", " ")
                nums = [int(x) for x in cleaned.split() if x.isdigit() or (x.lstrip('-').isdigit())]
                # فلتر 0-36
                nums = [n for n in nums if 0 <= n <= 36]
                
                if nums:
                    reply = analyze_numbers(nums)
                    send_message(chat_id, reply)
                else:
                    send_message(chat_id, "أرسل أرقام صحيحة مثل: 8, 12")
            except Exception as e:
                print(f"Parse error: {e}")
                send_message(chat_id, "صيغة خاطئة، أرسل مثل: 5, 12")
                
    except Exception as e:
        print(f"Webhook error: {e}")
    
    return jsonify({"ok": True})

# أول ما يشتغل السيرفر يربط الويبهوك تلقائياً
def set_webhook_on_start():
    try:
        if not BOT_TOKEN:
            print("No BOT_TOKEN")
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}"
        r = requests.get(url, timeout=15)
        print(f"Webhook set result: {r.text}")
    except Exception as e:
        print(f"Failed to set webhook: {e}")

set_webhook_on_start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
