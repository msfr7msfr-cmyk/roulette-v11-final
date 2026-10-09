import os, requests
from collections import Counter
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]

history = {}; last_pred = {}

def send(c,t):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":c,"text":t})

def get_neighbors(num):
    if num not in WHEEL: return []
    i = WHEEL.index(num)
    return [WHEEL[(i+1)%37], WHEEL[(i-1)%37], WHEEL[(i+2)%37], WHEEL[(i-2)%37]]

def get_v22_five(nums):
    if len(nums) < 15: return [], Counter(), {}
    f50 = Counter(nums[-50:])
    f20 = Counter(nums[-20:])
    f15 = Counter(nums[-15:])

    scored = {}
    gaps = {}

    for num in range(37):
        if num not in f50:
            continue

        # 1. Gap10 ثابت
        last_pos = len(nums) - 1 - nums[::-1].index(num)
        gap = len(nums) - 1 - last_pos
        gaps[num] = gap
        if gap >= 10: # ثبتنا Gap10
            continue

        score = 0

        # === 1. وزن زمني جديد ===
        # نحسب كل ظهور وزنه حسب مكانه
        for idx, val in enumerate(reversed(nums[-50:])):
            if val == num:
                pos = idx + 1 # 1 = اخر لفة
                if pos <= 10:
                    score += 3
                elif pos <= 25:
                    score += 1
                else:
                    score += 0.2

        # اساس 50 (للتوازن)
        score += f50[num] * 0.5

        # 2. Repeaters
        if f15[num] >= 2:
            score += 4
        if f15[num] >= 3:
            score += 3

        # جيران فيزيائي
        neigh = get_neighbors(num)[:2]
        score += sum(f50.get(x, 0) * 0.5 for x in neigh)

        # وزن الذاكرة القصيرة 15
        score += f15[num] * 2.5

        # بونص اخر 5
        if nums[-5:].count(num) >= 2:
            score += 2

        scored[num] = score

    five = sorted(scored, key=scored.get, reverse=True)[:5]
    return five, f50, gaps, f20

@app.route('/', methods=['POST'])
def webhook():
    data = request.json
    if "message" not in data: return "ok"
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text","").strip()
    if chat_id not in history: history[chat_id] = []

    if text in ["/start","مسح","م","clear"]:
        history[chat_id] = []; last_pred.pop(chat_id,None)
        send(chat_id,"✅ تم المسح - V22 Gap10 المحسن\n✅ وزن زمني + فلتر ميت + نقطة دخول"); return "ok"

    nums = [int(x) for x in text.replace(',',' ').split() if x.isdigit() and 0<=int(x)<=36]
    if not nums: return "ok"

    for n in nums:
        if chat_id in last_pred and n in last_pred[chat_id]:
            send(chat_id,f"✅ تحقق! {n} كان ضمن {last_pred[chat_id]}")

    history[chat_id].extend(nums)

    if len(history[chat_id]) < 15:
        send(chat_id,f"تم {len(history[chat_id])} - باقي {15-len(history[chat_id])}"); return "ok"

    five, f50, gaps, f20 = get_v22_five(history[chat_id])

    # === 3. نقطة الدخول - اهم فلتر ===
    repeaters_in_20 = sum(1 for k,v in f20.items() if v >= 2)
    if repeaters_in_20 < 2:
        send(chat_id,f"⏸️ لا تلعب - انتظر\nماكو Repeater قوي (عندي {repeaters_in_20}/2 بس)\nاخر 20: {f20.most_common(3)}")
        return "ok"

    recent = history[chat_id][-20:]
    counts = {"Voisins": sum(1 for x in recent if x in VOISINS), "Tiers": sum(1 for x in recent if x in TIERS), "Orphelins": sum(1 for x in recent if x in ORPHELINS)}
    sector = max(counts, key=counts.get)

    last_pred[chat_id] = five
    hot_str = ", ".join([f"{k}({v}x)" for k,v in f50.most_common(5)])

    main = five[0] if five else 0
    gap_main = gaps.get(main, 0)

    # === 2. فلتر الجيران الميت ===
    if gap_main >= 10:
        with_neigh = five # اذا الاساسي ميت لا ترشح جيرانه، رشح الخمسة الاساسية فقط
        neigh_note = f"⚠️ {main} Gap{main} عالي - بدون جيران"
    else:
        idx = WHEEL.index(main) if main in WHEEL else 0
        # فلتر: شيل الجيران الميتين
        raw_neigh = [WHEEL[(idx+1)%37], WHEEL[(idx-1)%37], WHEEL[(idx+2)%37], WHEEL[(idx-2)%37]]
        alive_neigh = [x for x in raw_neigh if gaps.get(x, 99) < 10]
        with_neigh = [main] + alive_neigh[:4]
        neigh_note = f"جيران حية فقط (Gap<10)"

    msg = f"""🧠 V22 Gap10 المحسن
📍 اخر: {history[chat_id][-1]} | قطاع: {sector}({counts[sector]}/20) | دخول: ✅ ({repeaters_in_20} Repeater)

🔥 5 الحارة (وزن زمني):
{hot_str}

💰 الاساسي: {five}
💰 مع الجيران: {with_neigh}
ℹ️ {neigh_note}

ثابت 4 لفات | اخر 10: {history[chat_id][-10:]}"""
    send(chat_id, msg); return "ok"

@app.route('/')
def home(): return "V22 Gap10 Enhanced Running"
if __name__ == "__main__": app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
