import os, requests
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]
history = {}

def send_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def get_neighbors(num):
    if num not in WHEEL: return []
    i = WHEEL.index(num)
    return [WHEEL[(i-1)%37], WHEEL[(i+1)%37], WHEEL[(i-2)%37], WHEEL[(i+2)%37]]

def get_hot_five(nums):
    from collections import Counter
    if len(nums) < 10: return []
    f50 = Counter(nums[-50:])
    f8 = Counter(nums[-8:])
    f15 = Counter(nums[-15:])
    scored = {}
    for num in range(37):
        if num not in f50: continue
        last_pos = len(nums)-1 - nums[::-1].index(num)
        gap = len(nums)-1 - last_pos
        base = f50[num]
        if gap > 15:
            if base < 3: continue
            base *= 0.5
        if num == 0 and gap > 20 and nums[-20:].count(0) < 2:
            continue
        score = base + f8[num]*3 + sum(f50.get(x,0) for x in get_neighbors(num))*0.5
        if f15[num] >= 2: score += 3
        if nums[-5:].count(num) >= 2: score += 2
        scored[num] = score
    return sorted(scored, key=scored.get, reverse=True)[:5]

def predict(nums):
    if len(nums) < 4: return None
    five = get_hot_five(nums)
    recent20 = nums[-20:]
    c = {"VOISINS": sum(1 for n in recent20 if n in VOISINS), "TIERS": sum(1 for n in recent20 if n in TIERS), "ORPHELINS": sum(1 for n in recent20 if n in ORPHELINS)}
    sector = max(c, key=c.get)
    return sector, c, five

@app.route('/', methods=['POST'])
def webhook():
    data = request.json
    if "message" not in data: return "ok"
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","").strip()
    if chat_id not in history: history[chat_id] = []

    if text in ["/start", "مسح", "مسح ", "clear", "م"]:
        history[chat_id] = []
        send_msg(chat_id, "✅ تم المسح - V22 جاهز دز ارقام")
        return "ok"

    nums = [int(x) for x in text.replace(',',' ').split() if x.isdigit() and 0 <= int(x) <= 36]
    if not nums: return "ok"
    history[chat_id].extend(nums)

    if len(history[chat_id]) < 10:
        send_msg(chat_id, f"تم تسجيل {len(history[chat_id])} ارقام - دز بعد")
        return "ok"

    sector, counts, five = predict(history[chat_id])
    if not five:
        send_msg(chat_id, "بعد")
        return "ok"

    msg = f"V22 - تثبيت (3/3)\nالاقتران: {five[0]}\nالتوقع: {five[0]}\nالتدرج: {sector} {counts}\nالخمسة: {five}"
    send_msg(chat_id, msg)
    return "ok"

@app.route('/')
def home(): return "V22 Running"
if __name__ == "__main__": app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
