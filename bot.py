import os, re, threading, time
from collections import Counter, deque
from flask import Flask
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
bot = telebot.TeleBot(BOT_TOKEN)

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V19 GENIUS - SINGLE NUMBER FIX"
@app_flask.route('/ping')
def ping(): return "alive"

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL_ORDER)}

history = deque(maxlen=200)
last_prediction = []
pred_age = 0

def get_neighbors_dir(num, direction=1):
    if num not in WHEEL_INDEX: return []
    idx = WHEEL_INDEX[num]
    return [WHEEL_ORDER[(idx + direction) % 37]]

def detect_direction(nums):
    if len(nums) < 6: return 1
    moves=[]
    for a,b in zip(nums[-10:-1], nums[-9:]):
        if a in WHEEL_INDEX and b in WHEEL_INDEX:
            d = WHEEL_INDEX[b] - WHEEL_INDEX[a]
            if d > 18: d -= 37
            if d < -18: d += 37
            moves.append(d)
    if not moves: return 1
    return 1 if sum(moves)/len(moves) > 0 else -1

@bot.message_handler(func=lambda m: True)
def handle(m):
    global last_prediction, pred_age
    text = (m.text or "").strip().lower()

    # امر مسح
    if text in ["مسح", "clear", "reset"]:
        history.clear()
        last_prediction=[]
        bot.reply_to(m, "✅ تم مسح الذاكرة - ارسل قائمة جديدة")
        return

    nums = [int(x) for x in re.findall(r'\b\d+\b', text) if 0 <= int(x) <= 36]

    if not nums:
        bot.reply_to(m, "ارسل ارقام فقط")
        return

    # اذا ارسل رقم واحد و الذاكرة فيها ارقام - نضيفه
    if len(nums) == 1 and len(history) >= 10:
        history.append(nums[0])
        all_nums = list(history)
        # نفحص اذا التوقع تحقق
        win = any(x == nums[0] or x in get_neighbors_dir(x, detect_direction(all_nums)) for x in last_prediction) if last_prediction else False
        # بس نكمل للتوقع الجديد
    elif len(nums) < 10 and len(history) < 10:
        bot.reply_to(m, f"ارسل 10 ارقام على الاقل للبداية (عندك {len(history)} حاليا)")
        return
    else:
        # قائمة طويلة جديدة - نضيفها
        history.extend(nums)
        all_nums = list(history)

    all_nums = list(history)
    if len(all_nums) < 10:
        bot.reply_to(m, "احتاج 10 ارقام على الاقل")
        return

    direction = detect_direction(all_nums)
    dir_name = "يمين ➡️" if direction==1 else "يسار ⬅️"

    pred_age += 1
    # فحص هل التوقع القديم تحقق بهذا الرقم الجديد؟
    if last_prediction and pred_age <= 5:
        recent_hit = nums[-1] in last_prediction or nums[-1] in [n for p in last_prediction for n in get_neighbors_dir(p, direction)]
        if recent_hit:
            bot.reply_to(m, f"✅ تحقق! الرقم {nums[-1]} كان ضمن توقع {last_prediction} - تم بعد {pred_age} لفات")
            pred_age = 0
            last_prediction = []
        elif pred_age < 5:
            final = []
            for n in last_prediction:
                final.append(n)
                final.extend(get_neighbors_dir(n, direction))
            final = list(dict.fromkeys(final))[:5]
            bot.reply_to(m, f"🧠 V19 - تثبيت ({pred_age}/5)\n📍 اتجاه: {dir_name} | اخر رقم: {all_nums[-1]}\n🎯 العب: {final[:3]} + جيرانهم {dir_name}\n⏱️ لازم يجي خلال {5-pred_age} لفات")
            return

    # توقع جديد
    cnt = Counter(all_nums[-30:])
    hot = [n for n,c in cnt.most_common(3)]
    final = []
    for h in hot:
        final.append(h)
        final.extend(get_neighbors_dir(h, direction))
    final = list(dict.fromkeys(final))[:6]
    last_prediction = final[:3]
    pred_age = 0

    txt = f"""🧠 V19 - العبقري
📍 اخر رقم: {all_nums[-1]} | اتجاه: {dir_name}

🎯 العب: {final[:3]} + جيرانهم
💰 قطاع: {final}

اخر 10: {', '.join(map(str, all_nums[-10:]))}"""
    bot.reply_to(m, txt)

def run_flask():
    port=int(os.environ.get("PORT",10000))
    app_flask.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except: time.sleep(5)
