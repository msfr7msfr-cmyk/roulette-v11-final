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

def get_neighbors(num, count=2):
    if num not in WHEEL: return []
    i = WHEEL.index(num)
    res=[]
    for k in range(1, count+1):
        res.append(WHEEL[(i+k)%37])
        res.append(WHEEL[(i-k)%37])
    return res

def get_v21_five(nums):
    if len(nums)<15: return [], Counter()
    f50=Counter(nums[-50:]); f15=Counter(nums[-15:])
    scored={}
    for num in range(37):
        if num not in f50: continue

        # 4. فلتر Gap 25 - اذا ما طلع من 25 نشيله
        last_pos = len(nums)-1-nums[::-1].index(num)
        gap = len(nums)-1-last_pos
        if gap >= 25:
            continue

        score = f50[num] # اساس 50

        # 6. Repeaters - مرتين بآخر 15
        if f15[num] >= 2: score += 4
        if f15[num] >= 3: score += 3

        # جيران العجلة
        neigh = get_neighbors(num, 1)
        score += sum(f50.get(x,0)*0.6 for x in neigh)

        # وزن الذاكرة القصيرة 15
        score += f15[num]*2.5

        # اذا تكرر بآخر 5
        if nums[-5:].count(num) >= 2: score += 2

        scored[num]=score

    five = sorted(scored, key=scored.get, reverse=True)[:5]
    return five, f50

@app.route('/', methods=['POST'])
def webhook():
    data=request.json
    if "message" not in data: return "ok"
    chat_id=data["message"]["chat"]["id"]
    text=data["message"].get("text","").strip()
    if chat_id not in history: history[chat_id]=[]

    if text in ["/start","مسح","م","clear"]:
        history[chat_id]=[]; last_pred.pop(chat_id,None)
        send(chat_id,"✅ تم المسح - V21 جاهز (ذاكرة 15 + Gap 25 + Repeaters)"); return "ok"

    nums=[int(x) for x in text.replace(',',' ').split() if x.isdigit() and 0<=int(x)<=36]
    if not nums: return "ok"

    # تحقق
    for n in nums:
        if chat_id in last_pred and n in last_pred[chat_id]:
            send(chat_id,f"✅ تحقق! {n} كان ضمن {last_pred[chat_id]}")

    history[chat_id].extend(nums)

    if len(history[chat_id])<15:
        send(chat_id,f"تم {len(history[chat_id])} - باقي {15-len(history[chat_id])} للتحليل"); return "ok"

    five,f50 = get_v21_five(history[chat_id])

    # 2. قطاع 20
    recent=history[chat_id][-20:]
    counts={"Voisins": sum(1 for x in recent if x in VOISINS), "Tiers": sum(1 for x in recent if x in TIERS), "Orphelins": sum(1 for x in recent if x in ORPHELINS)}
    sector=max(counts, key=counts.get)

    last_pred[chat_id]=five
    hot_str=", ".join([f"{k}({v}x)" for k,v in f50.most_common(5)])

    main=five[0] if five else 0
    i=WHEEL.index(main) if main in WHEEL else 0
    with_neigh=[main, WHEEL[(i+1)%37], WHEEL[(i+2)%37], WHEEL[(i-1)%37], WHEEL[(i-2)%37]]

    msg=f"""🧠 V21 - تثبيت 4/4 | ذاكرة 15
📍 اخر: {history[chat_id][-1]} | قطاع: {sector}({counts[sector]}/20)

🔥 الـ 5 الحارة (50 لفة - فلتر Gap 25 + Repeaters):
{hot_str}

💰 العب الاساسي: {five}
💰 مع الجيران: {with_neigh}

ثابت لـ 4 لفات | اخر 10: {history[chat_id][-10:]}"""
    send(chat_id,msg); return "ok"

@app.route('/')
def home(): return "V21 Running"
if __name__=="__main__": app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
