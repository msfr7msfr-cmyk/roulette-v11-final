import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# التوكن يجي من ريندر Environment
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

RED = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]

def color(n):
    if n == 0:
        return "green"
    if n in RED:
        return "red"
    return "black"

def get_report(spins, window):
    data = spins[-window:]
    red = sum(1 for n in data if color(n) == "red")
    black = sum(1 for n in data if color(n) == "black")
    green = sum(1 for n in data if color(n) == "green")
    total = len(data)
    total_no_green = red + black
    rp = (red / total_no_green * 100) if total_no_green else 0
    bp = (black / total_no_green * 100) if total_no_green else 0
    return red, black, green, total, rp, bp

def make_report(spins):
    r200, b200, g200, total200, rp200, bp200 = get_report(spins, 200)
    r50, b50, g50, _, rp50, bp50 = get_report(spins, 50)

    if rp50 > bp50:
        reco = "⚫ الأسود أقل — مرشح للتعويض."
    elif bp50 > rp50:
        reco = "🔴 الأحمر أقل — مرشح للتعويض."
    else:
        reco = "⚖️ متوازن - لا توجد توصية"

    diff200 = abs(rp200 - bp200)
    if diff200 < 5:
        status200 = "⚖️ متوازن"
    elif rp200 > bp200:
        status200 = f"🔴 الأحمر متقدم (+{diff200:.1f}%)"
    else:
        status200 = f"⚫ الأسود متقدم (+{diff200:.1f}%)"

    diff50 = abs(rp50 - bp50)
    if diff50 < 5:
        status50 = "⚖️ متوازن"
    elif rp50 > bp50:
        status50 = f"🔴 الأحمر متقدم (+{diff50:.1f}%)"
    else:
        status50 = f"⚫ الأسود متقدم (+{diff50:.1f}%)"

    text = f"""📊 تقرير شامل (آخر {total200} لفة):
🔴 الأحمر: {r200} مرة ({r200/total200*100:.1f}%)
⚫ الأسود: {b200} مرة ({b200/total200*100:.1f}%)
🟢 الصفر: {g200} مرة ({g200/total200*100:.1f}%)
🎯 آخر رقم طاح: {spins[-1]}

⚖️ نسب التوازن (أحمر / أسود):

📊 آخر 200 لفة:
   🔴 الأحمر: {r200} ({rp200:.1f}%)
   ⚫ الأسود: {b200} ({bp200:.1f}%)
   🟢 الصفر: {g200}
   {status200}

📊 آخر 50 لفة:
   🔴 الأحمر: {r50} ({rp50:.1f}%)
   ⚫ الأسود: {b50} ({bp50:.1f}%)
   🟢 الصفر: {g50}
   {status50}

💡 التوصية (آخر 50): {reco}"""
    return text

def send_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text
        }, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

# هذا عشان UptimeRobot وريندر يعرفون انه شغال
@app.route("/", methods=["GET"])
def home():
    return "Bot is Live ✅", 200

# هذا اللي يستقبل رسايل تيليجرام
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print(data)
    if not data or "message" not in data:
        return jsonify({"ok": True}), 200

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    if text == "/start":
        send_message(chat_id, "أهلاً 👋\nارسل الأرقام مفصولة بمسافة، مثال:\n24 4 33 21 25 35 0 11 17\nوأنا أرسل لك التقرير كامل.")
        return jsonify({"ok": True}), 200

    try:
        spins = [int(x) for x in text.replace(",", " ").split()]
        spins = [n for n in spins if 0 <= n <= 36]
        if len(spins) < 5:
            send_message(chat_id, "ارسل على الأقل 5 أرقام، مثال:\n1 2 3 4 5 6 7")
            return jsonify({"ok": True}), 200

        report = make_report(spins)
        send_message(chat_id, report)

    except Exception as e:
        print(f"Error: {e}")
        send_message(chat_id, "ما فهمت، ارسل الأرقام جذي:\n24 4 33 21 25")

    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
