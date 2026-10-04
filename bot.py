import os, re, threading
from collections import Counter, deque, defaultdict
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V15 AUTO - FIXED"

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
    gap_list=[]
    for n in range(37):
        if n not in last_seen: gap_list.append((n, total))
        else: gap_list.append((n, total - last_seen[n] -1))
    overdue=sorted(gap_list, key=lambda x:x[1], reverse=True)[:4]

    final_score=defaultdict(float)
    for num,cnt in hot: final_score[num]+=cnt*3.0
    for num,cnt in markov: final_score[num]+=cnt*5.0
    for num,gap in overdue: final_score[num]+=min(gap*0.4, 8)
    for nb in get_neighbors(last,1): final_score[nb]+=4
    for nb in get_neighbors(last,2): final_score[nb]+=1.5

    top3=sorted(final_score.items(), key=lambda x:x[1], reverse=True)[:3]
    if not top3: return None

    # ثقة حقيقية - مو 95 دايما
    score1=top3[0][1]
    score2=top3[1][1] if len(top3)>1 else 0
    score3=top3[2][1] if len(top3)>2 else 0
    diff = score1 - score2

    # اذا الفرق كبير بين الاول والثاني = ثقة اعلى
    # اذا متقاربين = ثقة ضعيفة
    if diff >= 8: conf = 85 + min(diff,10)
    elif diff >= 4: conf = 70 + diff*2
    elif diff >= 2: conf = 55 + diff*3
    else: conf = 35 + diff*5

    if total < 30: conf *= 0.6
    elif total < 50: conf *= 0.8

    conf = max(25, min(92, round(conf,1)))

    return {"top3":[n for n,_ in top3], "scores":top3, "confidence":conf, "hot":hot[:3], "markov":markov, "overdue":overdue[:3], "last":last, "total":total}

def format_genius(res):
    if not res: return None
    conf=res['confidence']
    if conf >= 80: status="✅ العب - ثقة عالية"
    elif conf >= 60: status="⚠️ ممكن تلعب - ثقة متوسطة"
    elif conf >= 45: status="⏳ انتظر - ثقة ضعيفة"
    else: status="❌ لا تلعب - عشوائي"

    txt=f"🧠 V15 AUTO\n📊 {res['total']} رقم - اخر: {res['last']}\n"
    txt+=f"━━━━━━━━━━━━━━\n🎯 الثلاثة الذهبية:\n"
    for i,(num,score) in enumerate(res["scores"],1):
        txt+=f"{i}. {num} (قوة {round(score,1)})\n"
    txt+=f"━━━━━━━━━━━━━━\n"
    txt+=f"🔥 حارة: {', '.join([f'{n}({c}مره)' for n,c in res['hot']])}\n"
    if res['markov']: txt+=f"🔗 بعد {res['last']} تكرر: {', '.join([f'{n}' for n,c in res['markov']])}\n"
    txt+=f"⏰ متأخرة: {', '.join([f'{n} غاب {g}' for n,g in res['overdue']])}\n"
    txt+=f"━━━━━━━━━━━━━━\n📈 الثقة: {conf}%\n{status}\n"
    if conf>=70:
        txt+=f"\n💰 العب {res['top3'][0]} + جيرانه {get_neighbors(res['top3'][0],1)}"
    else:
        txt+=f"\n💤 لا تلعب هالجولة، اجمع ارقام"
    return txt

def main_markup():
    m=ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("🧠 تحليل عبقري","مسح 🗑️")
    return m

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id,"🧠 V15 AUTO FIXED\nدز ارقام والبوت يحلل لحاله تلقائيا\nكل رقم تدزه يحلل بدون ما تدوس زر", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id,"🗑️ تم المسح - دز 20 رقم ليبدأ", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res=genius_analyze()
    if res: bot.send_message(m.chat.id, format_genius(res), reply_markup=main_markup())
    else: bot.send_message(m.chat.id, f"عندك {len(history)} بس، احتاج 20", reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text: return
    if "مسح" in m.text or "عبقري" in m.text or m.text.startswith('/'): return
    nums=[int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0<=int(n)<=36]
    if not nums: return
    for n in nums: history.append(n)

    # يرد بعد كل رقم - بس التحليل التلقائي اذا 20+
    if len(history) < 20:
        bot.send_message(m.chat.id, f"✅ {nums} - المجموع {len(history)}/20", reply_markup=main_markup())
    else:
        # AUTO تحليل تلقائي!
        res=genius_analyze()
        if res:
            bot.send_message(m.chat.id, format_genius(res), reply_markup=main_markup())
        else:
            bot.send_message(m.chat.id, f"✅ {nums} - المجموع {len(history)}", reply_markup=main_markup())

threading.Thread(target=lambda: app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000))), daemon=True).start()
bot.infinity_polling()
