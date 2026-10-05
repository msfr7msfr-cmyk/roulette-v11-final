import os, re, threading, time
from collections import Counter, deque
from flask import Flask
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
bot = telebot.TeleBot(BOT_TOKEN)

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V20.4 - 5 SECTOR ONLY"
@app_flask.route('/ping')
def ping(): return "alive"

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL)}

VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]
ORPHELINS = [1,20,14,31,9,17,34,6]

history = deque(maxlen=300)
last_pred = []
pred_age = 0

def neighbors(n, dir):
    if n not in WHEEL_INDEX: return []
    i = WHEEL_INDEX[n]
    return [WHEEL[(i+dir)%37]]

def direction(nums):
    if len(nums)<8: return 1
    diffs=[]
    for a,b in zip(nums[-12:-1], nums[-11:]):
        if a in WHEEL_INDEX and b in WHEEL_INDEX:
            d=WHEEL_INDEX[b]-WHEEL_INDEX[a]
            if d>18: d-=37
            if d<-18: d+=37
            diffs.append(d)
    return 1 if sum(diffs)/len(diffs)>0 else -1 if diffs else 1

def sector_top5(all_nums):
    recent=all_nums[-20:]
    v=sum(1 for x in recent if x in VOISINS)
    t=sum(1 for x in recent if x in TIERS)
    o=sum(1 for x in recent if x in ORPHELINS)
    if v>=t and v>=o:
        sector=VOISINS; name="Voisins (0)"
    elif t>=o:
        sector=TIERS; name="Tiers"
    else:
        sector=ORPHELINS; name="Orphelins"

    cnt=Counter([x for x in recent if x in sector])
    top = [n for n,_ in cnt.most_common(5)]

    # نكمل 5 اذا ما فيه تكرار كافي
    for s in sector:
        if s not in top:
            top.append(s)
        if len(top)>=5: break

    return top[:5], name, max(v,t,o), sector

@bot.message_handler(func=lambda m: True)
def handle(m):
    global last_pred, pred_age
    txt=(m.text or "").lower()
    if txt in ["مسح","clear","reset"]:
        history.clear(); last_pred=[]; pred_age=0
        bot.reply_to(m,"✅ تم مسح الذاكرة")
        return

    nums=[int(x) for x in re.findall(r'\b\d+\b', txt) if 0<=int(x)<=36]
    if not nums: return

    if len(nums)==1 and len(history)>=10:
        history.append(nums[0])
    elif len(nums)>=10:
        if len(nums)>20:
            history.clear()
            history.extend(nums)
        else:
            history.extend(nums)
    elif len(history)<10:
        bot.reply_to(m,f"البداية تحتاج 10 ارقام على الاقل (عندك {len(history)})")
        return
    else:
        history.append(nums[-1])

    all_nums=list(history)
    dir = direction(all_nums)
    dir_name="يمين ➡️" if dir==1 else "يسار ⬅️"

    pred_age+=1
    if last_pred and pred_age<=5:
        if all_nums[-1] in last_pred:
            bot.reply_to(m,f"✅ تحقق مباشر! {all_nums[-1]} كان ضمن {last_pred} بعد {pred_age} لفات")
            pred_age=0
            last_pred=[]
        elif pred_age<5:
            final=[]
            for p in last_pred:
                final.append(p); final.extend(neighbors(p,dir))
            final=list(dict.fromkeys(final))[:10]
            bot.reply_to(m,f"🧠 V20.4 - تثبيت ({pred_age}/5)\n📍 اتجاه: {dir_name} | اخر: {all_nums[-1]}\n🎯 العب: {last_pred} + جيران {dir_name} = {final}\n⏱️ باقي {5-pred_age} لفات")
            return

    top5, sec_name, sec_hits, sec_list = sector_top5(all_nums)

    last_pred = top5
    pred_age=0

    display=[]
    for n in top5:
        display.extend([n]+neighbors(n,dir))
    display=list(dict.fromkeys(display))

    msg=f"""🧠 V20.4 - 5 قطاع فقط
📍 اخر رقم: {all_nums[-1]} | اتجاه: {dir_name} | قطاع ساخن: {sec_name} ({sec_hits}/20)

🎯 الـ 5 من {sec_name}:
1. {top5[0]}
2. {top5[1]}
3. {top5[2]}
4. {top5[3]}
5. {top5[4]}

💰 العب: {top5} + جيرانهم {dir_name} = {display[:10]}

اخر 10: {', '.join(map(str, all_nums[-10:]))}
"""
    bot.reply_to(m, msg)

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.getenv("PORT",10000)))

if __name__=="__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(4)
