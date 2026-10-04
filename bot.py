import os, threading
from collections import Counter
from flask import Flask
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TOKEN="8246479435:AAFud5g3T3s1n9_g9E6r7PEfCkkljkY84sc
data={}
web=Flask(__name__)
@web.route('/')
def home(): return "OK"

def getd(cid):
 if cid not in data: data[cid]=[]
 return data[cid]

async def start(u,c):
 getd(u.effective_chat.id).clear()
 await u.message.reply_text("✅ V18 AUTO جاهز\nدز رقم")

async def onmsg(u,c):
 txt=u.message.text.strip()
 cid=u.effective_chat.id
 lst=getd(cid)
 if txt=="مسح":
  lst.clear()
  await u.message.reply_text("🗑️ تم")
  return
 if txt.startswith("/"): return
 nums=[]
 for p in txt.replace(","," ").split():
  try:
   n=int(float(p))
   if 0<=n<=36: nums.append(n)
  except: pass
 if nums:
  lst.extend(nums)
  co=Counter(lst)
  await u.message.reply_text(f"🧠 AUTO\nالعدد:{len(lst)} المجموع:{sum(lst)}\nالاكثر:{co.most_common(3)}")

def runweb():
 web.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))

def runbot():
 app=Application.builder().token(TOKEN).build()
 app.add_handler(CommandHandler("start",start))
 app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,onmsg))
 app.run_polling()

if __name__=="__main__":
 threading.Thread(target=runweb,daemon=True).start()
 runbot()
