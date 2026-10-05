import os, re, threading, time
from collections import Counter, deque
from flask import Flask
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
bot = telebot.TeleBot(BOT_TOKEN)

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V20.5 SMART SECTOR"
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

def get_direction(nums):
    if len(nums)<10: return 1
    diffs=[]
    for a,b in zip(nums[-15:-1], nums[-14:]):
        if a in WHEEL_INDEX and b in WHEEL_INDEX:
            d=WHEEL_INDEX[b]-WHEEL_INDEX[a]
            if d>18: d-=37
            if d<-18: d+=37
            diffs.append(d)
    if not diffs: return 1
    return 1 if sum(diffs)/len(diffs)>0 else -1

def gap_of(num, all_nums):
    # كم لفة من اخر ظهور
    for i in range(len(all_nums)-2, -1, -1):
        if all_nums[i]==num:
            return (len(all_nums)-1 - i)
    return 300 # عمره ما طلع

def smart_sector_top5(all_nums):
    recent=all_nums[-20:]
    v=sum(1 for x in recent if x in VOISINS)
    t=sum(1 for x in recent if x in TIERS)
    o=sum(1 for x in recent if x in ORPHELINS)

    if v>=t and v>=o:
        sector=VOISINS; name=f"Voisins({v})"
    elif t>=o:
        sector=TIERS; name=f"Tiers({t})"
    else:
        sector=ORPHELINS; name=f"Orphelins({o})"

    last = all_nums[-1]
    last_idx = WHEEL_INDEX.get(last, 0)
    dir = get_direction(all_nums)

    scored=[]
    for cand in sector:
        g = gap_of(cand, all_nums)
        cand_idx = WHEEL_INDEX[cand]
        forward = (cand_idx - last_idx) % 37 # المسافة للامام
        if dir==1:
            dist = forward # نبيه قدام
            if dist>18: dist = 37-dist + 10 # عقوبة اذا ورا
        else:
            backward = (last_idx - cand_idx) % 37
            dist = backward
            if dist>18: dist = 37-dist + 10

        # كلما الفجوة كبيرة و المسافة صغيرة = ممتاز
        score = dist*1.5 - g*0.8
        scored.append((cand, g, dist, score))

    scored.sort(key=lambda x: x[3]) # اقل سكور = افضل
    top5 = [x[0] for x in scored[:5]]

    return top5, name, dir, scored[:8]

@bot.message_handler(func=lambda m: True)
def handle(m):
    global last_pred, pred_age
    txt=(m.text or "").lower()
    if txt in ["مسح","clear","reset"]:
        history.clear(); last_pred=[]; pred_age=0
        bot.reply_to(m,"✅ مسح")
        return

    nums=[int(x) for x in re.findall(r'\b\d+\b', txt) if 0<=int(x)<=36]
    if not nums: return

    if len(nums)==1 and len(history)>=10:
        history.append(nums[0])
    elif len(nums)>=10:
        if len(nums)>25:
            history.clear(); history.extend(nums)
        else: history.extend(nums)
    elif len(history)<10:
        bot.reply_to(m,f"تحتاج 10 ارقام (عندك {len(history)})")
        return
    else:
        history.append(nums[-1])

    all_nums=list(history)
    dir = get_direction(all_nums)
    dir_name="يمين ➡️" if dir==1 else "يسار ⬅️"

    pred_age+=1
    if last_pred and pred_age<=5:
        if all_nums[-1] in last_pred:
            bot.reply_to(m,f"✅ تحقق! {all_nums[-1]} كان ضمن {last_pred} بعد {pred_age} لفات")
            pred_age=0; last_pred=[]
        elif pred_age<5:
            final=[]
            for p in last_pred:
                final.append(p); final.extend(neighbors(p,dir))
            final=list(dict.fromkeys(final))[:10]
            bot.reply_to(m,f"🧠 V20.5 - تثبيت ({pred_age}/5)\n🎯 العب: {last_pred} + جيران = {final}")
            return

    top5, sec_name, d, details = smart_sector_top5(all_nums)
    last_pred=top5; pred_age=0

    display=[]
    for n in top5:
        display.extend([n]+neighbors(n,dir))
    display=list(dict.fromkeys(display))

    detail_txt="\n".join([f"{c}: فجوة {g} | مسافة {dist}" for c,g,dist,s in details[:5]])

    msg=f"""🧠 V20.5 - قطاع ذكي
📍 اخر: {all_nums[-1]} | اتجاه: {dir_name} | قطاع: {sec_name}

🎯 الـ 5 الذكية (فجوة كبيرة + قريب باتجاه الديلر):
{detail_txt}

💰 العب الاساسي: {top5}
💰 مع الجيران {dir_name}: {display[:10]}

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
