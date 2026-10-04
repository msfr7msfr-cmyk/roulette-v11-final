import os, re, threading, random
from collections import Counter, deque, defaultdict
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V16 SECTOR - NOT STUCK"

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
def get_neighbors(num, n=2):
    if num not in WHEEL_ORDER: return []
    idx=WHEEL_ORDER.index(num)
    return [WHEEL_ORDER[(idx+i)%37] for i in range(-n, n+1) if i!=0]

history = deque(maxlen=300)
loss_streak = 0
BOT_TOKEN = os.environ.get("BOT_TOKEN","")
bot = telebot.TeleBot(BOT_TOKEN)

def genius_analyze_v16():
    if len(history)<15: return None
    data=list(history); last=data[-1]; total=len(data)

    # V16: نستخدم اخر 30 فقط للحارة - مو كل التاريخ
    recent = data[-30:]
    counter_recent = Counter(recent)
    counter_all = Counter(data)

    # 1. حارة حديثة (اخر 30)
    hot_recent = counter_recent.most_common(5)
    # 2. باردة - ما طلعت من زمان
    last_seen={}
    for i,num in enumerate(data): last_seen[num]=i
    overdue=[]
    for n in range(37):
        gap = total - last_seen.get(n, -1) -1
        overdue.append((n,gap))
    overdue_sorted=sorted(overdue, key=lambda x:x[1], reverse=True)

    # 3. Markov من اخر رقم
    transitions=defaultdict(list)
    for i in range(len(data)-1): transitions[data[i]].append(data[i+1])
    markov=Counter(transitions.get(last,[])).most_common(4)

    # 4. قطاعات - وين تتجمع الارقام بالعجلة؟
    sector_scores=defaultdict(int)
    for num in recent:
        if num in WHEEL_ORDER:
            idx=WHEEL_ORDER.index(num)
            sector_scores[WHEEL_ORDER[idx]]+=1
            for nb in get_neighbors(num,1): sector_scores[nb]+=0.5

    final_score=defaultdict(float)

    # اذا خسران كثير - غير الاسلوب
    global loss_streak
    if loss_streak >= 2:
        # العب الباردة
        for num,gap in overdue_sorted[:6]: final_score[num]+=gap*0.6
        strategy = f"باردة (خسران {loss_streak})"
    else:
        # العب الحارة + ماركوف + قطاع
        for num,cnt in hot_recent: final_score[num]+=cnt*3.5
        for num,cnt in markov: final_score[num]+=cnt*4.5
        for num,sc in sector_scores.items(): final_score[num]+=sc*1.2
        for nb in get_neighbors(last,2): final_score[nb]+=2.5
        strategy = "حارة + قطاع"

    # لا تعلق - اذا اول رقم مسيطر بفرق كبير، قلل قوته شوي وخلي تنوع
    sorted_scores=sorted(final_score.items(), key=lambda x:x[1], reverse=True)
    if len(sorted_scores)>=2 and sorted_scores[0][1] > sorted_scores[1][1]*1.8:
        final_score[sorted_scores[0][0]] *= 0.7

    top3=sorted(final_score.items(), key=lambda x:x[1], reverse=True)[:3]

    score1=top3[0][1] if top3 else 0
    score2=top3[1][1] if len(top3)>1 else 0
    diff=score1-score2
    conf = 40 + diff*6 + random.uniform(-5,5)
    if len(recent)>=25: conf+=10
    conf = max(28, min(88, round(conf,1)))

    return {"top3":[n for n,_ in top3], "scores":top3, "confidence":conf, "hot_recent":hot_recent, "overdue":overdue_sorted[:3], "markov":markov, "last":last, "total":total, "strategy":strategy}

def format_v16(res):
    conf=res['confidence']
    if conf>=75: status="✅ العب"
    elif conf>=55: status="⚠️ جرب بمبلغ صغير"
    else: status="❌ لا تلعب"

    txt=f"🧠 V16 SECTOR - {res['strategy']}\n📊 {res['total']} - اخر: {res['last']}\n"
    txt+=f"━━━━━━━━━━━━\n🎯 الترشيح:\n"
    for i,(num,sc) in enumerate(res["scores"],1):
        txt+=f"{i}. {num} (قوة {round(sc,1)}) جيران {get_neighbors(num,1)}\n"
    txt+=f"━━━━━━━━━━━━\n"
    txt+=f"🔥 اخر 30: {', '.join([f'{n}x{c}' for n,c in res['hot_recent'][:3]])}\n"
    txt+=f"⏰ بارد: {', '.join([f'{n} غاب {g}' for n,g in res['overdue']])}\n"
    if res['markov']: txt+=f"🔗 بعد {res['last']}: {', '.join([f'{n}' for n,c in res['markov'][:2]])}\n"
    txt+=f"━━━━━━━━━━━━\n📈 ثقة: {conf}% - {status}\n"
    if conf>=55:
        txt+=f"\n💰 العب: {res['top3']} + جيرانهم\n💡 لا تلعب اكثر من 3 لفات بنفس الارقام"
    else:
        txt+=f"\n💤 تخطى - موجة عشوائية"
    return txt

def main_markup():
    m=ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("🧠 تحليل عبقري","مسح 🗑️")
    m.row("✅ فزت","❌ خسرت")
    return m

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    global loss_streak; loss_streak=0
    bot.send_message(m.chat.id,"🧠 V16 - ما يعلق على 28/2/9\nيحلل اخر 30 رقم بس + يغير استراتيجيته اذا خسر\nاذا فزت دوس ✅ فزت واذا خسرت ❌ خسرت عشان يتعلم", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    global loss_streak; loss_streak=0
    bot.send_message(m.chat.id,"🗑️ مسح", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "فزت" in m.text)
def win_h(m):
    global loss_streak; loss_streak=0
    bot.send_message(m.chat.id,"🔥 ممتاز! صفرنا الخسارة - نكمل بنفس الاسلوب", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "خسرت" in m.text)
def lose_h(m):
    global loss_streak; loss_streak+=1
    bot.send_message(m.chat.id,f"تمام، خسارة {loss_streak} ورا بعض - راح اغير الاسلوب للباردة", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res=genius_analyze_v16()
    if res: bot.send_message(m.chat.id, format_v16(res), reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text or m.text.startswith('/'): return
    if any(x in m.text for x in ["مسح","عبقري","فزت","خسرت"]): return
    nums=[int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0<=int(n)<=36]
    if not nums: return
    for n in nums: history.append(n)
    if len(history)<15:
        bot.send_message(m.chat.id, f"✅ {len(history)}/15", reply_markup=main_markup())
    else:
        res=genius_analyze_v16()
        bot.send_message(m.chat.id, format_v16(res), reply_markup=main_markup())

threading.Thread(target=lambda: app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000))), daemon=True).start()
bot.infinity_polling()
