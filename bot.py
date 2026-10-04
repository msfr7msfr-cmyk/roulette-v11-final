import os
from flask import Flask
from threading import Thread
from collections import Counter, deque
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL)}
def neighbors(n, r=1):
    i=WHEEL_INDEX.get(n,-1)
    if i==-1: return []
    res=[]
    for k in range(1, r+1):
        res.append(WHEEL[(i-k)%37]); res.append(WHEEL[(i+k)%37])
    return res

app = Flask(__name__)
@app.route('/')
def home(): return "Bot V13 Real Smart Live!"

history = deque(maxlen=100)

def analyze_real():
    if len(history)<5: return None
    c=Counter(history)
    last=history[-1]
    scores={i:0 for i in range(37)}
    reasons={i:[] for i in range(37)}

    # 1- اداة الحرارة (تكرار)
    for num,co in c.items():
        scores[num]+=co*3
        if co>1: reasons[num].append(f"حار x{co}")

    # 2- اداة الجيران (آخر رقم فقط)
    for nb in neighbors(last,1):
        scores[nb]+=8
        reasons[nb].append(f"جار {last}")

    # 3- اداة القطاعات - وين قاعد يضرب
    last10 = list(history)[-10:]
    sector_count = Counter([WHEEL_INDEX[n]//12 for n in last10]) # 3 قطاعات
    dominant_sector = sector_count.most_common(1)[0][0]
    for n in range(37):
        if WHEEL_INDEX[n]//12 == dominant_sector:
            scores[n]+=2
            reasons[n].append("قطاع نشط")

    # 4- اداة التأخر (ارقام ما طلعت من زمان)
    for n in range(37):
        if n not in history:
            scores[n]+=1
            reasons[n].append("متأخر")
        elif list(history)[::-1].index(n) > 20 if n in history else True:
            scores[n]+=2
            reasons[n].append("بارد")

    top3 = sorted(scores.items(), key=lambda x:x[1], reverse=True)[:3]

    # حساب الثقة الحقيقية
    total_score = sum(scores.values())
    top_score = sum([s for _,s in top3])
    conf = int((top_score / (total_score+1) * 100) + len(history))
    conf = min(92, max(45, conf))

    decision = "✅ العب الان" if conf >= 75 else "⛔ انتظر - لا تلعب"

    return [(n,reasons[n]) for n,s in top3], conf, decision

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    history.clear()
    await update.message.reply_text("🧠 V13 الحقيقي الذكي جاهز\n📊 4 ادوات تحليل\nدز 5 ارقام عالاقل يبدا التحليل")

async def handle(update:Update, context:ContextTypes.DEFAULT_TYPE):
    txt=update.message.text.strip()
    if txt.lower() in ["مسح","clear","امسح"]:
        history.clear(); await update.message.reply_text("🗑️ تم المسح"); return
    if not txt.isdigit(): return
    n=int(txt)
    if 0<=n<=36:
        history.append(n)
        if len(history)<5:
            await update.message.reply_text(f"✅ [{n}] باقي {5-len(history)} ويبدا الذكاء"); return

        result,conf,decision=analyze_real()
        msg=f"✅ لفة: [{n}]\n📊 الكلي: {len(history)}\n\n"
        for i,(num,rs) in enumerate(result,1):
            msg+=f"{i}️⃣ {num} | {', '.join(rs[:2])}\n"
        msg+=f"\n📈 الثقة: {conf}%\n{decision}\n"
        if conf>=75: msg+=f"💰 ادخل على {result[0][0]} بقوة!"
        else: msg+=f"⏳ لا تدخل هاللفة"
        await update.message.reply_text(msg)

def run_bot():
    token=os.getenv("BOT_TOKEN")
    application=ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
