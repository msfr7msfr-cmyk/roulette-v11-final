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
    direction = "يمين ➡️" if avg>0 else "يسار ⬅️"
    stable = f"({max(pos,3-pos)+1}/4)"

    last = idx[-1]
    pred_idx = int((last + avg) % 37)
    sector = [WHEEL[(pred_idx+i)%37] for i in range(-2,3)]
    mid = WHEEL[pred_idx]
    mid_i = WHEEL.index(mid)
    neighbors = [WHEEL[(mid_i-2)%37], WHEEL[(mid_i-1)%37], WHEEL[(mid_i+1)%37], WHEEL[(mid_i+2)%37]]

    return sector, mid, neighbors, direction, stable

@app.route('/')
def home():
    return "V21 Live - LounHelper_bot55"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" not in data: return "ok"
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","")

    if "/start" in text:
        send_msg(chat_id, "🎯 بوت الروليت V21 جاهز\nدز 4 أرقام مثال:\n15 2 34 4")
        return "ok"

    nums = [int(x) for x in re.findall(r'\d+', text) if 0 <= int(x) <= 36]
    if not nums: return "ok"

    if chat_id not in history: history[chat_id]=[]
    history[chat_id].extend(nums)
    history[chat_id]=history[chat_id][-10:]

    if len(history[chat_id])>=4:
        try:
            sector, main, neigh, dir_, stab = predict(history[chat_id])
            msg = f"🧠 V21 - تثبيت {stab} + تدرج\n🎯 العب: {sector} + جيران = {neigh}\nالأساسي: {main}\n{dir_} اتجاه: {dir_}"
            # نفس فورمات صورتك
            msg2 = f"🧠 V21 - تثبيت {stab}\n🎯 العب: {sector} + جيران = {neigh}\n[{','.join(map(str,sector))}]\nاتجاه: {dir_}"
            send_msg(chat_id, msg2)
        except Exception as e:
            send_msg(chat_id, f"خطأ: {e}")
    else:
        send_msg(chat_id, f"تم حفظ {len(history[chat_id])}/4 - دز بعد")
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
