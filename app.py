import os, requests, collections
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]

history = {}
last_prediction = {}

def send(chat_id, text):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

def get_sector(num):
    if num in VOISINS: return "Voisins"
    if num in TIERS: return "Tiers"
    if num in ORPHELINS: return "Orphelins"
    return "Voisins"

def get_neighbors(num, side="right", count=2):
    if num not in WHEEL: return []
    i = WHEEL.index(num)
    if side == "right": return [WHEEL[(i+k)%37] for k in range(1, count+1)]
    else: return [WHEEL[(i-k)%37] for k in range(1, count+1)]

def analyze(nums):
    c50 = collections.Counter(nums[-50:])
    c8 = collections.Counter(nums[-8:])
    hot = sorted(c50.items(), key=lambda x: (x[1], c8.get(x[0],0)), reverse=True)[:5]
    return [n for n,_ in hot], c50

@app.route('/', methods=['POST'])
def webhook():
    data = request.json
    if "message" not in data: return "ok"
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","").strip()
    if chat_id not in history: history[chat_id]=[]

    if text in ["/start","مسح","م","clear"]:
        history[chat_id]=[]
        last_prediction.pop(chat_id, None)
        send(chat_id, "✅ تم المسح - V22 جاهز دز ارقام")
        return "ok"

    nums = [int(x) for x in text.replace(',',' ').split() if x.isdigit() and 0 <= int(x) <= 36]
    if not nums: return "ok"

    # تحقق من التوقع السابق
    for n in nums:
        if chat_id in last_prediction and n in last_prediction[chat_id].get("five", []):
            idx = last_prediction[chat_id]["five"].index(n) if n in last_prediction[chat_id]["five"] else 99
            send(chat_id, f"✅ تحقق! {n} كان ضمن {last_prediction[chat_id]['five']} بعد {last_prediction[chat_id]['lag']} لفات")

    history[chat_id].extend(nums)
    if len(history[chat_id]) < 8:
        send(chat_id, f"تم {len(history[chat_id])} - دز بعد")
        return "ok"

    five, c50 = analyze(history[chat_id])
    # قطاع
    recent = history[chat_id][-20:]
    counts = {"Voisins": sum(1 for x in recent if x in VOISINS), "Tiers": sum(1 for x in recent if x in TIERS), "Orphelins": sum(1 for x in recent if x in ORPHELINS)}
    sector = max(counts, key=counts.get)

    # تثبيت منطق
    stab = min(4, len(history[chat_id])//10 + 1)

    # الجيران يمين
    main = five[0] if five else 0
    neigh_r = get_neighbors(main, "right", 2)
    neigh_l = get_neighbors(main, "left", 2)
    with_neigh = [main] + neigh_r + neigh_l + five[1:3]

    # خزن
    last_prediction[chat_id] = {"five": five, "lag": 1, "main": main}

    hot_str = ", ".join([f"{k}({v}x)" for k,v in c50.most_common(5)])

    msg = f"""🧠 V20.6 - تثبيت {stab}/4 + خمسة حارة
📍 اخر: {history[chat_id][-1]} | اتجاه: يمين ➡️ | قطاع: {sector}({counts[sector]})

🔥 الـ 5 الحارة (الاكثر تكرار اخر 50 لفة داخل القطاع):
{hot_str}

💰 العب الاساسي: {five}
💰 مع الجيران يمين ➡️ : {with_neigh[:7]}

ثابت لـ 4 لفات | اخر 10: {history[chat_id][-10:]}"""

    send(chat_id, msg)
    return "ok"

@app.route('/')
def home(): return "V20.6 Running"
if __name__ == "__main__": app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
