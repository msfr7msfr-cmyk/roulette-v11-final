import os,re,collections,threading
from flask import Flask
from telegram import Update
from telegram.ext import Application,CommandHandler,MessageHandler,filters,ContextTypes

TOKEN=os.getenv("BOT_TOKEN")
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
 m=c.most_common(5)
 exp=t/37
 top,ct=m[0]
 st=ct/exp if exp else 0
 conf=85 if ct>=5 else 70 if ct==4 else 50 if ct==3 else 30
 top3=[str(x) for x,_ in m[:3]]
 stt="🔥 العب" if conf>=75 else "⚠️ مراقبة" if conf>=50 else "👀 متابع"
 more=",".join([f"{n}x{cc}" for n,cc in m[:3]])
 return f"🧠 V18\n📊 {t} - الطبيعي {exp:.2f} - الاقوى {top} x{ct} ({st:.2f}x)\n🎯 {','.join(top3)}\n📈 {conf}%\n📍 1.97x\n{stt}\n🔥 {more}"

async def st(update:Update,context:ContextTypes.DEFAULT_TYPE):
 await update.message.reply_text("V18 جاهز - كل رقم احلله لحاله")

async def hd(update:Update,context:ContextTypes.DEFAULT_TYPE):
 cid=update.effective_chat.id
 nums=get(cid)
 txt=update.message.text or ""
 if "مسح" in txt:
  nums.clear()
  await update.message.reply_text("تم المسح 🗑️")
  return
 f=[int(x) for x in re.findall(r'\d+',txt) if 0<=int(x)<=36]
 if not f:
  if "تحليل" in txt:
   await update.message.reply_text(fmt(nums))
  return
 nums.extend(f)
 await update.message.reply_text(f"✅ +{len(f)} = {len(nums)}")
 await update.message.reply_text(fmt(nums))

def run():
 a=Application.builder().token(TOKEN).build()
 a.add_handler(CommandHandler("start",st))
 a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,hd))
 a.run_polling()

if __name__=="__main__":
 threading.Thread(target=run,daemon=True).start()
 port=int(os.environ.get("PORT",10000))
 app.run(host='0.0.0.0',port=port)
