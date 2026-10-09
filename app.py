import os, time, threading, collections
from flask import Flask
import telebot

TOKEN = os.getenv("BOT_TOKEN","").strip()
if not TOKEN:
    TOKEN = os.getenv("TOKEN","").strip()

print(f"TOKEN OK: {bool(TOKEN)} len={len(TOKEN)}")

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

NEIGHBORS={0:[32,26],32:[0,15],15:[32,19],19:[15,4],4:[19,21],21:[4,2],2:[21,25],25:[2,17],17:[25,34],34:[17,6],6:[34,27],27:[6,13],13:[27,36],36:[13,11],11:[36,30],30:[11,8],8:[30,23],23:[8,10],10:[23,5],5:[10,24],24:[5,16],16:[24,33],33:[16,1],1:[33,20],20:[1,14],14:[20,31],31:[14,9],9:[31,22],22:[9,18],18:[22,29],29:[18,7],7:[29,28],28:[7,12],12:[28,35],35:[12,3],3:[35,26],26:[3,0]}

history=[]

def get_v22():
    if len(history)<20:
        return f"📊 {len(history)}/20 باقي {20-len(history)}"
    f15={}
    for x in history[-15:]:
        f15[x]=f15.get(x,0)+1
    gap={}
    rev=list(reversed(history))
    for n in range(37):
        gap[n]=rev.index(n) if n in rev else 99
    score={}
    for n in range(37):
        if gap[n]>=10: continue
        c10=history[-10:].count(n)
        c25=history[-25:].count(n)
        c50=history[-50:].count(n)
        s=(c10*3)+((c25-c10)*1)+((c50-c25)*0.2)
        if f15.get(n,0)>=2: s+=1.5
        if f15.get(n,0)>=3: s+=1
        if s>0: score[n]=s
    if not score:
        return "ما كو ارقام حارة"
    basic=[n for n,_ in sorted(score.items(),key=lambda x:x[1],reverse=True)[:5]]
    with_nb=[]
    for num in basic[:3]:
        if gap[num]<10:
            with_nb.append(num)
            for nb in NEIGHBORS.get(num,[])[:1]:
                if gap[nb]<10: with_nb.append(nb)
        if len(with_nb)>=5: break
    return f"🧠 V22 Gap10\n🔥 اساسي: {basic}\n🎯 مع جار: {with_nb[:5]}\nاخر: {history[-1]}"

@bot.message_handler(commands=['start','reset'])
def start(m):
    history.clear()
    bot.reply_to(m,"✅ تم المسح V22\nدخل 20 رقم")

@bot.message_handler(func=lambda m: m.text and 'مسح' in m.text)
def clear_ar(m):
    history.clear()
    bot.reply_to(m,"✅ تم المسح V22 Gap10\nدخل 20 رقم")

@bot.message_handler(func=lambda m: True)
def all_msg(m):
    try:
        txt=m.text.replace(',',' ').replace('\n',' ')
        nums=[]
        for p in txt.split():
            if p.lstrip('-').isdigit():
                try:
                    n=int(p)
                    if 0<=n<=36: nums.append(n)
                except: pass
        if not nums: return
        for n in nums: history.append(n)
        bot.reply_to(m,(f"✅ اضافة {len(nums)}\n" if len(nums)>1 else "")+get_v22())
    except Exception as e:
        print(f"MSG ERR {e}")

@app.route('/')
def home():
    return f"V22 Live - hist:{len(history)} token:{bool(TOKEN)}"

def run_bot():
    bot.remove_webhook()
    time.sleep(3)
    while True:
        try:
            print("START POLLING")
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"POLLING ERR {e} retry in 5s")
            time.sleep(5)

threading.Thread(target=run_bot, daemon=True).start()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=10000)
