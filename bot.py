import os
import logging
from collections import Counter, deque
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
WHEEL_INDEX = {num: i for i, num in enumerate(WHEEL)}

def get_neighbors_2(num):
    if num not in WHEEL_INDEX: return []
    idx = WHEEL_INDEX[num]
    return [WHEEL[(idx - 1) % len(WHEEL)], WHEEL[(idx + 1) % len(WHEEL)]]

def get_neighbors(num, n=1):
    if num not in WHEEL_INDEX: return []
    idx = WHEEL_INDEX[num]
    res=[]
    for i in range(1,n+1):
        res.append(WHEEL[(idx - i) % len(WHEEL)])
        res.append(WHEEL[(idx + i) % len(WHEEL)])
    return res

SECTORS = {
    "Voisins": [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25],
    "Tiers": [27,13,36,11,30,8,23,10,5,24,16,33],
    "Orphelins": [1,20,14,31,9,17,34,6],
}
RED = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
user_history = {}
def get_history(chat_id):
    if chat_id not in user_history:
        from collections import deque
        user_history[chat_id] = deque(maxlen=100)
    return user_history[chat_id]

def analyze_and_predict(history):
    from collections import Counter
    counter = Counter(history)
    last = history[-1]
    total = len(history)
    neighbor_score = Counter()
    for num in list(history)[-5:]:
        for nb in get_neighbors(num, 2): neighbor_score[nb]+=2
        for nb in get_neighbors_2(num): neighbor_score[nb]+=3
    sector_hits = {name:0 for name in SECTORS}
    for num in history:
        for s_name, s_nums in SECTORS.items():
            if num in s_nums: sector_hits[s_name]+=1
    dominant_sector = max(sector_hits, key=sector_hits.get) if history else None
    reds = sum(1 for n in history if n in RED and n!=0)
    blacks = sum(1 for n in history if n not in RED and n!=0)
    color_bias = "أحمر" if reds>blacks else "أسود" if blacks>reds else "متوازن"
    scores = {i:0 for i in range(37)}
    reasons = {i:[] for i in range(37)}
    for num in range(37):
        s=0
        if num in neighbor_score:
            s+=neighbor_score[num]*4
            reasons[num].append(f"جيران({neighbor_score[num]})")
        if num in counter:
            s+=counter[num]*5
            reasons[num].append(f"تكرار{counter[num]}")
        if dominant_sector and num in SECTORS[dominant_sector]:
            s+=6
            reasons[num].append(dominant_sector)
        if num==last: s+=4
        if num in get_neighbors_2(last):
            s+=8
            reasons[num].append("جار مباشر للأخير")
        scores[num]=s
    sorted_scores = sorted(scores.items(), key=lambda x:x[1], reverse=True)
    top3=[]
    for num,score in sorted_scores:
        if len(top3)>=3: break
        if score>0: top3.append(num)
    if len(top3)<3:
        for nb in get_neighbors(last,2):
            if nb not in top3: top3.append(nb)
            if len(top3)>=3: break
    top3=top3[:3]
    base_conf=60
    if total>=3: base_conf+=min(15,total*1.5)
    agreement=sum(len(reasons[n]) for n in top3)
    if agreement>=6: base_conf+=10
    confidence=min(92, max(62, int(base_conf + sum(scores[n] for n in top3)/3)))
    strength="🔥🔥🔥 قوي جدا" if confidence>=85 else "🔥🔥 قوي" if confidence>=78 else "🔥 متوسط قوي" if confidence>=70 else "⚠️ متوسط"
    return {"top3":top3,"confidence":confidence,"strength":strength,"reasons":reasons,"total":total,"last":last,"hot":counter.most_common(3),"sector_hits":sector_hits,"dominant_sector":dominant_sector,"color_bias":color_bias,"scores":scores}

async def start(update, context):
    get_history(update.effective_chat.id).clear()
    await update.message.reply_text("✅ بوت الروليت V12 العبقري جاهز 🧠🔥\nدز الأرقام (0-36)\nراح أطلع لك 3 أرقام تلعب عليهم مع نسبة الثقة %\n\nاكتب مسح للمسح")

async def handle_number(update, context):
    text=update.message.text.strip()
    chat_id=update.effective_chat.id
    if text in ["مسح","clear","امسح"]:
        get_history(chat_id).clear()
        await update.message.reply_text("🗑️ تم مسح كل الأرقام"); return
    if not text.isdigit(): return
    num=int(text)
    if not 0<=num<=36: return
    history=get_history(chat_id)
    history.append(num)
    if len(history)==1:
        await update.message.reply_text(f"✅ تم: [{num}]\n📊 العدد:1\n🎯 آخر رقم:{num}\n👥 جيرانه:{get_neighbors_2(num)}\n\nدز رقم ثاني للتحليل"); return
    pred=analyze_and_predict(list(history))
    top3=pred["top3"]; conf=pred["confidence"]; strength=pred["strength"]
    reason_lines=[f"• {n}: {','.join(pred['reasons'][n][:2])}" for n in top3]
    sector_info=f"{pred['dominant_sector']}" if pred['dominant_sector'] else "غير محدد"
    msg=(f"✅ تم: [{num}]\n📊 العدد الكلي: {pred['total']}\n🎯 آخر رقم: {pred['last']}\n👥 جيرانه: {get_neighbors_2(pred['last'])}\n🔥 الساخن: {pred['hot']}\n🎡 القطاع: {sector_info}\n🎨 اللون: {pred['color_bias']}\n{'─'*20}\n🧠 تحليل V12 العبقري:\n🎯 العب على: {top3}\n📈 نسبة الثقة: {conf}% {strength}\n{chr(10).join(reason_lines)}\n{'─'*20}\n")
    if conf>=80: msg+=f"💰 توصية: العب بقوة! {top3[0]} أساسي + {top3[1]},{top3[2]}\n"
    elif conf>=70: msg+=f"💡 توصية: العب متوسط، ركز على {top3[0]} و {top3[1]}\n"
    else: msg+=f"⚠️ توصية: انتظر رقم إضافي\n"
    msg+=f"\nدز رقم ثاني للتحليل"
    await update.message.reply_text(msg)

def main():
    token=os.getenv("BOT_TOKEN")
    if not token: raise ValueError("BOT_TOKEN not set!")
    app=ApplicationBuilder().token(token).build()
    from telegram.ext import CommandHandler, MessageHandler, filters
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number))
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
