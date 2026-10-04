import os, re, threading
from collections import Counter, deque, defaultdict
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V14 GENIUS FIXED LIVE"

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
def get_neighbors(num, n=1):
    if num not in WHEEL_ORDER: return []
    idx=WHEEL_ORDER.index(num)
    return [WHEEL_ORDER[(idx+i)%37] for i in range(-n, n+1) if i!=0]

history = deque(maxlen=300)
BOT_TOKEN = os.environ.get("BOT_TOKEN","")
bot = telebot.TeleBot(BOT_TOKEN)

def genius_analyze():
    if len(history)<20: return None
    data=list(history); last=data[-1]; total=len(data)
    counter=Counter(data)
    hot=counter.most_common(5)
    transitions=defaultdict(list)
    for i in range(len(data)-1): transitions[data[i]].append(data[i+1])
    markov=Counter(transitions.get(last,[])).most_common(3)
    last_seen={}
    for i,num in enumerate(data): last_seen[num]=i
    gap_scores={n: total-last_seen.get(n,0) for n in range(37)}
    overdue=sorted(gap_scores.items(), key=lambda x:x[1], reverse=True)[:5]
    final_score=defaultdict(float)
    for num,cnt in hot: final_score[num]+=cnt*3.0
    for num,cnt in markov: final_score[num]+=cnt*4.0
    for num,gap in overdue: final_score[num]+=(gap/total)*10
    for num in data[-10:]: final_score[num]+=1.5
    for nb in get_neighbors(last,1): final_score[nb]+=5
    top3=sorted(final_score.items(), key=lambda x:x[1], reverse=True)[:3]
    max_score=top3[0][1] if top3 else 0
    conf=min(95, (max_score/10*50)+40)
    if total<50: conf*=0.6
    return {"top3":[n for n,_ in top3], "scores":top3, "confidence":round(conf,1), "hot":hot[:3], "markov":markov, "overdue":overdue[:3], "last":last, "total":total}

def format_genius(res):
    if not res: return "دز 20 رقم على الاقل"
    conf=res['confidence']
    status="✅ العب - ثقة عالية" if conf>=80 else "⚠️ انتظر" if conf>=60 else "❌ لا تلعب"
    txt=f"🧠 V14 GENIUS\n📊 {res['total']} رقم - اخر: {res['last']}\n━━━━━━━━━━━━━━\n🎯 الثلاثة الذهبية:\n"
    for i,(num,score) in enumerate(res["scores"],1): txt+=f"{i}. {num} (قوة {round(score,1)})\n"
    txt+=f"━━━━━━━━━━━━━━\n🔥 حارة: {res['hot']}\n🔗 بعد {res['last']}: {res['markov']}\n⏰ متأخرة: {res['overdue']}\n━━━━━━━━━━━━━━\n📈 الثقة: {conf}%\n{status}\n"
    if conf>=80: txt+=f"\n💰 العب {res['top3'][0]} + جيرانه {get_neighbors(res['top3'][0],1)}"
    return txt

def main_markup():
    m=ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("🧠 تحليل عبقري","مسح 🗑️")
    return m

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id,"🧠 V14 GENIUS - 7 خوارزميات - 3 ارقام فقط\nدز 30 رقم على الاقل", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id,"🗑️ تم المسح", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res=genius_analyze()
    bot.send_message(m.chat.id, format_genius(res) if res else f"عندك {len(history)} بس، احتاج 20", reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text: return
    if "مسح" in m.text or "عبقري" in m.text or m.text.startswith('/'): return
    nums=[int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0<=int(n)<=36]
    if nums:
        history.extend(nums)
        bot.send_message(m.chat.id, f"✅ {len(nums)} رقم - المجموع {len(history)}", reply_markup=main_markup())
        if len(history)>=15 and len(nums)>=2:
            res=genius_analyze()
            if res: bot.send_message(m.chat.id, format_genius(res), reply_markup=main_markup())

threading.Thread(target=lambda: app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000))), daemon=True).start()
bot.infinity_polling()
