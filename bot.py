import os, collections, threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN="8403393289:AAH4pCctVW1gSMv4HIIDuG4okGaBJ4yq9MM"
data={}
flask_app=Flask(__name__)
@flask_app.route('/')
def home(): return "V18 AUTO OK - Bot Running"

def get_data(cid):
    if cid not in data: data[cid]=[]
    return data[cid]

def fmt(nums):
    t=len(nums)
    if t==0: return "دز ارقام"
    c=collections.Counter(nums)
    m=c.most_common(3)
    s=sum(nums)
    return f"🧠 V18 AUTO\nالعدد:{t} المجموع:{s}\nالاقوى:{m}\n✅ AUTO بدون زر"

async def start_cmd(u,c):
    get_data(u.effective_chat.id).clear()
    await u.message.reply_text("✅ V18 AUTO جاهز!\nدز اي رقم وراح احلله تلقائي بدون زر")

async def msg_handler(u,c):
    txt=u.message.text.strip()
    cid=u.effective_chat.id
    lst=get_data(cid)
    if txt=="مسح":
        lst.clear()
        await u.message.reply_text("🗑️ تم المسح - دز ارقام جديدة")
        return
    if txt.startswith("/"): return
    if txt=="تحليل عبقري 🧠": return
    try:
        new_nums=[]
        for x in txt.replace(","," ").split():
            try:
                n=int(float(x))
                if 0<=n<=36: new_nums.append(n)
            except: pass
        if new_nums:
            lst.extend(new_nums)
            await u.message.reply_text(fmt(lst))
    except: pass

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def run_bot():
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    app.run_polling()

if __name__=="__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
