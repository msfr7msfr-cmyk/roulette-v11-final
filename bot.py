import os, re, threading, time
from collections import Counter, deque
from flask import Flask
import telebot

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
bot = telebot.TeleBot(BOT_TOKEN)

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V18 GENIUS - NO BUTTONS"
@app_flask.route('/ping')
def ping(): return "alive"

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL_ORDER)}

history = deque(maxlen=100)
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
    text = m.text or ""
    nums = [int(x) for x in re.findall(r'\b\d+\b', text) if 0 <= int(x) <= 36]
    if len(nums) < 5:
        bot.reply_to(m, "ارسل 10 ارقام على الاقل مفصولة بفاصلة")
        return

    history.extend(nums)
    all_nums = list(history)

    direction = detect_direction(all_nums)
    dir_name = "يمين ➡️" if direction==1 else "يسار ⬅️"

    # ذكاء التوقيت: اذا التوقع السابق لم يتحقق خلال 5 لفات نلتزم به
    pred_age += 1
    if last_prediction and pred_age <= 5:
        recent = all_nums[-pred_age:]
        if not any(x in recent for x in last_prediction):
            # لم يتحقق بعد - نطوره حسب الاتجاه الجديد
            final = []
            for n in last_prediction:
                final.append(n)
                final.extend(get_neighbors_dir(n, direction))
            final = list(dict.fromkeys(final))[:5]
            msg = f"🧠 V18 - عبقري - تثبيت توقيت ({pred_age}/5)\n📍 اتجاه الكورة: {dir_name}\n🎯 العب: {final[:3]} + جيرانهم {dir_name}\n⏱️ لازم يجي خلال {5-pred_age} لفات"
            bot.reply_to(m, msg)
            return

    # توقع جديد عبقري
    cnt = Counter(all_nums[-25:])
    hot = [n for n,c in cnt.most_common(3)]

    final = []
    for h in hot:
        final.append(h)
        final.extend(get_neighbors_dir(h, direction))
    final = list(dict.fromkeys(final))[:6]

    last_prediction = final[:3]
    pred_age = 0

    txt = f"""🧠 V18 - العبقري
📍 اخر رقم: {all_nums[-1]} | اتجاه الكورة: {dir_name}
⏱️ توقيت جديد

🎯 القطاع الذكي:
1. {final[0]} + جيران {get_neighbors_dir(final[0], direction)} قوة 12.0
2. {final[1]} + جيران {get_neighbors_dir(final[1], direction)} قوة 9.0
3. {final[2]} + جيران {get_neighbors_dir(final[2], direction)} قوة 9.0

🔥 اخر 10: {', '.join(map(str, all_nums[-10:]))}
💰 العب: {final[:3]} + جيرانهم

ذكاء: يقرا يمين/يسار + يلتزم 5 لفات"""
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
