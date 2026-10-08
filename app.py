import os, requests, collections
from flask import Flask, request
app = Flask(__name__)
TOKEN = os.getenv("BOT_TOKEN")
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]
history = {}
last_pred = {}

def send(c,t): requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":c,"text":t})
def get_neighbors(num):
    if num not in WHEEL: return []
    i=WHEEL.index(num)
    return [WHEEL[(i-1)%37], WHEEL[(i+1)%37], WHEEL[(i-2)%37], WHEEL[(i+2)%37]]

def get_hot_five(nums):
    from collections import Counter
    if len(nums)<10: return [], Counter()
    f50=Counter(nums[-50:]); f8=Counter(nums[-8:]); f15=Counter(nums[-15:])
    scored={}
    for num in range(37):
        if num not in f50: continue
        last_pos=len(nums)-1-nums[::-1].index(num); gap=len(nums)-1-last_pos
        base=f50[num]
        if gap>15:
            if base<3: continue
            base*=0.5
        if num==0 and gap>20 and nums[-20:].count(0)<2: continue
        score=base+f8[num]*3+sum(f50.get(x,0) for x in get_neighbors(num))*0.5
        if f15[num]>=2: score+=3
        if nums[-5:].count(num)>=2: score+=2
        scored[num]=score
    five=sorted(scored, key=scored.get, reverse=True)[:5]
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
        send(chat_id,"✅ تم المسح - V22 جاهز دز ارقام"); return "ok"
    nums=[int(x) for x in text.replace(',',' ').split() if x.isdigit() and 0<=int(x)<=36]
    if not nums: return "ok"
    for n in nums:
        if chat_id in last_pred and n in last_pred[chat_id]:
            send(chat_id,f"✅ تحقق! {n} كان ضمن {last_pred[chat_id]} بعد 1 لفة")
    history[chat_id].extend(nums)
    if len(history[chat_id])<10:
        send(chat_id,f"تم {len(history[chat_id])} - باقي {10-len(history[chat_id])}"); return "ok"
    five,f50=get_hot_five(history[chat_id])
    recent=history[chat_id][-20:]
    counts={"Voisins": sum(1 for x in recent if x in VOISINS), "Tiers": sum(1 for x in recent if x in TIERS), "Orphelins": sum(1 for x in recent if x in ORPHELINS)}
    sector=max(counts, key=counts.get)
    last_pred[chat_id]=five
    hot_str=", ".join([f"{k}({v}x)" for k,v in f50.most_common(5)])
    neigh=[]
    if five:
        i=WHEEL.index(five[0]) if five[0] in WHEEL else 0
        neigh=[WHEEL[(i+1)%37], WHEEL[(i+2)%37], WHEEL[(i-1)%37]]
    msg=f"""🧠 V22 - تثبيت 4/4 + خمسة حارة
📍 اخر: {history[chat_id][-1]} | اتجاه: يمين ➡️ | قطاع: {sector}({counts[sector]})

🔥 الـ 5 الحارة (الاكثر تكرار اخر 50 لفة داخل القطاع):
{hot_str}

💰 العب الاساسي: {five}
💰 مع الجيران يمين ➡️ : [{', '.join(map(str, (five[:2]+neigh+five[2:3])[:7]))}]

ثابت لـ 4 لفات | اخر 10: {history[chat_id][-10:]}"""
    send(chat_id,msg); return "ok"
@app.route('/')
def home(): return "V22 Running"
if __name__=="__main__": app.run(host='0.0.0.0', port=int(os.environ.get("PORT",10000)))
