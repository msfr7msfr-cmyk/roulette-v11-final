import os, re, requests
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
history = {}

def send_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def predict(nums):
    if len(nums) < 4:
        return None
    idx = [WHEEL.index(n) if n in WHEEL else 0 for n in nums[-4:]]
    diffs = []
    for i in range(1,4):
        d = idx[i]-idx[i-1]
        if d>18: d-=37
        if d<-18: d+=37
        diffs.append(d)
    avg = sum(diffs)/3
    pos = sum(1 for d in diffs if d>0)
    neg = 3-pos
    # V21 منطق التدرج + اقتران
    if pos>=2:
        trend = int(avg) if avg>0 else 1
    else:
        trend = int(avg) if avg<0 else -1
    last = WHEEL.index(nums[-1])
    pred_idx = (last + trend) % 37
    return WHEEL[pred_idx], trend, pos, neg

# هذا السطر هو الحل لمشكلة النوم - يخلي UptimeRobot يشوفك UP
@app.route("/", methods=["GET"])
def home():
    return "V21 Bot Running - LounHelper_bot55", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return "ok", 200
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if text.startswith("/start"):
        history[chat_id]=[]
        send_msg(chat_id, "V21 جاهز 🔥\nدز الارقام مثل:\n15 2 34 4 19\n\nالبوت LounHelper_bot55 الاصلي")
        return "ok",200

    nums = list(map(int, re.findall(r'\d+', text)))
    nums = [n for n in nums if 0 <= n <= 36]
    if not nums:
        return "ok",200

    if chat_id not in history:
        history[chat_id]=[]
    history[chat_id].extend(nums)
    history[chat_id]=history[chat_id][-50:]

    pred = predict(history[chat_id])
    if pred:
        p, trend, pos, neg = pred
        send_msg(chat_id, f"V21 - تثبيت ({pos}/3)\nالاقتران: {trend}\n➡️ التوقع: {p}\nالتدرج: {'صاعد' if trend>0 else 'نازل'}")
    else:
        send_msg(chat_id, f"تم تسجيل {len(history[chat_id])} ارقام - دز بعد")
    return "ok",200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
