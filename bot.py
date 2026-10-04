import os, collections, threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN="8403393289:AAH4pCctVW1gSMv4HIIDuG4okGaBJ4yq9MM"
data={}
app=Flask(__name__)
@app.route('/')
def h():return "V18 AUTO OK"
def get(cid):
 if cid not in data:data[cid]=[]
 return data[cid]
def fmt(nums):
 t=len(nums)
 if t==0:return "دز ارقام"
 c=collections.Counter(nums)
 m=c.most_common(3)
 return f"🧠 V18 AUTO\nالعدد:{t} المجموع:{sum(nums)}\nالاقوى:{m}\nالثقة:{70 if t>5 else 50}%"
async def start(u,c):
 get(u.effective_chat.id).clear()
 await u.message.reply_text("✅ V18 AUTO جاهز\nدز ارقام ويتحلل تلقائي")
async def msg(u,c):
 txt=u.message.text.strip()
 cid=u.effective_chat.id
 lst=get(cid)
 if txt=="مسح":
  lst.clear()
  await u.message.reply_text("🗑️ تم المسح")
  return
 if txt.startswith("/"):return
 try:
  f=[]
  for x in txt.replace(","," ").split():
   try:
    n=int(float(x))
    if 0<=n<=36:f.append(n)
   except:pass
  if f:
   lst.extend(f)
   await u.message.reply_text(fmt(lst))
 except:pass
def run_flask():
 app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
def run_bot():
 a=Application.builder().token(TOKEN).build()
 a.add_handler(CommandHandler("start",start))
 a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg))
 a.run_polling()
if __name__=="__main__":
 threading.Thread(target=run_flask,daemon=True).start()
 run_bot()
