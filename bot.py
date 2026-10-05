import os, re, threading, time, random
from collections import Counter, deque, defaultdict
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V17 NEVER SLEEPS"

@app_flask.route('/ping')
def ping(): return "alive"

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
def get_neighbors(num, n=1):
    try:
        if num not in WHEEL_ORDER: return []
        idx=WHEEL_ORDER.index(num)
        return [WHEEL_ORDER[(idx+i)%37] for i in range(-n,n+1) if i!=0]
    except: return []

history = deque(maxlen=200)
loss_streak = 0
BOT_TOKEN = os.environ.get("BOT_TOKEN","").strip()
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

def analyze():
    if len(history)<12: return None
    data=list(history); last=data[-1]; total=len(data)
    recent=data[-25:] if len(data)>=25 else data
    cnt_rec=Counter(recent)
    hot_rec=cnt_rec.most_common(3)

    last_seen={}
    for i,n in enumerate(data): last_seen[n]=i
    overdue=[]
    for n in range(37):
        gap = total-1-last_seen.get(n,-1)
        if gap>0: overdue.append((n,gap))
    overdue=sorted(overdue, key=lambda x:x[1], reverse=True)[:3]

    trans=defaultdict(list)
    for i in range(len(data)-1): trans[data[i]].append(data[i+1])
    markov=Counter(trans.get(last,[])).most_common(2)

    score=defaultdict(float)
    if loss_streak>=2:
        for n,g in overdue[:5]: score[n]+=min(g*0.5,10)
        strat=f"باردة - خسارة {loss_streak}"
    else:
        for n,c in hot_rec: score[n]+=c*3
        for n,c in markov: score[n]+=c*5
        for nb in get_neighbors(last,1): score[nb]+=3
        strat="قطاع + جيران"

    # منع التعليق على رقم واحد
    top=sorted(score.items(), key=lambda x:x[1], reverse=True)[:5]
    if len(top)>=2 and top[0][1] > top[1][1]*2:
        score[top[0][0]] *= 0.6
        top=sorted(score.items(), key=lambda x:x[1], reverse=True)[:3]
    else:
        top=top[:3]

    if not top: return None
    diff = top[0][1] - (top[1][1] if len(top)>1 else 0)
    conf = 45 + diff*5 + random.uniform(-3,3)
    conf = max(30, min(88, round(conf,1)))
    return {"top3":[n for n,_ in top], "scores":top, "conf":conf, "hot":hot_rec, "over":overdue, "mark":markov, "last":last, "total":total, "strat":strat}

def fmt(r):
    if not r: return None
    conf=r['conf']
    st = "✅ العب" if conf>=65 else "⚠️ صغير" if conf>=50 else "❌ لا تلعب"
    t=f"🧠 V17 - {r['strat']}\n📊 {r['total']} - اخر {r['last']}\n"
    t+=f"━━━━━━━\n🎯:\n"
    for i,(n,s) in enumerate(r['scores'],1):
        t+=f"{i}. {n} قوة {round(s,1)} جيران {get_neighbors(n,1)}\n"
    t+=f"━━━━━━━\n🔥 25 اخيرة: {', '.join([f'{n}x{c}' for n,c in r['hot']])}\n"
    t+=f"⏰ بارد: {', '.join([f'{n} غاب {g}' for n,g in r['over']])}\n"
    if r['mark']: t+=f"🔗 بعد {r['last']}: {r['mark'][0][0]}\n"
    t+=f"━━━━━━━\n📈 {conf}% - {st}\n"
    if conf>=50: t+=f"💰 العب {r['top3']} + جيرانهم"
    else: t+=f"💤 انتظر"
    return t

def mk():
    m=ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("🧠 تحليل","مسح 🗑️")
    m.row("✅ فزت","❌ خسرت")
    return m

@bot.message_handler(commands=['start'])
def s(m):
    history.clear()
    global loss_streak; loss_streak=0
    bot.send_message(m.chat.id,"V17 شغال - ما ينام\nدز ارقام", reply_markup=mk())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def cl(m):
    history.clear()
    global loss_streak; loss_streak=0
    bot.send_message(m.chat.id,"مسح", reply_markup=mk())

@bot.message_handler(func=lambda m: m.text and "فزت" in m.text)
def w(m):
    global loss_streak; loss_streak=0
    bot.send_message(m.chat.id,"تم ✅", reply_markup=mk())
@bot.message_handler(func=lambda m: m.text and "خسرت" in m.text)
def l(m):
    global loss_streak; loss_streak+=1
    bot.send_message(m.chat.id,f"خسارة {loss_streak} - بغير الاسلوب", reply_markup=mk())

@bot.message_handler(func=lambda m: m.text and "تحليل" in m.text)
def an(m):
    r=analyze()
    if r: bot.send_message(m.chat.id, fmt(r), reply_markup=mk())

@bot.message_handler(func=lambda m: True)
def allm(m):
    try:
        if not m.text or m.text.startswith('/'): return
        if any(x in m.text for x in ["مسح","تحليل","فزت","خسرت"]): return
        nums=[int(x) for x in re.findall(r'\b\d{1,2}\b', m.text) if 0<=int(x)<=36]
        if not nums: return
        for n in nums: history.append(n)
        if len(history)<12:
            bot.send_message(m.chat.id, f"✅ {len(history)}/12", reply_markup=mk())
        else:
            r=analyze()
            if r: bot.send_message(m.chat.id, fmt(r), reply_markup=mk())
    except Exception as e:
        print("error",e)
        bot.send_message(m.chat.id, f"خطأ بسيط: {e}", reply_markup=mk())

def run_flask():
    app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))

threading.Thread(target=run_flask, daemon=True).start()

# polling مع اعادة تشغيل تلقائي اذا وقف
while True:
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        print(f"polling error {e} - restart in 5s")
        time.sleep(5)
