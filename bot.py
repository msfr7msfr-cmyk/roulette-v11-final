import os, re, threading
from collections import deque, defaultdict, Counter
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V17 SMART TALKER"
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get("BOT_TOKEN","")
bot = telebot.TeleBot(BOT_TOKEN)
history = deque(maxlen=300)

WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
def get_neighbors(num, n=1):
    if num not in WHEEL_ORDER: return []
    idx = WHEEL_ORDER.index(num)
    return [WHEEL_ORDER[(idx+i) % len(WHEEL_ORDER)] for i in range(-n, n+1)]

def main_markup():
    m = ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("🧠 تحليل عبقري", "مسح 🗑️")
    return m

def analyze():
    if len(history) < 20:
        return None
    data = list(history)
    total = len(data)
    cnt = Counter(data)
    expected = total / 37.0
    top = cnt.most_common(3)
    max_c = top[0][1] if top else 0
    ratio = max_c / expected if expected else 0

    sector = defaultdict(int)
    for num in data[-50:]:
        for nb in get_neighbors(num,1):
            sector[nb]+=1
    sector_sorted = sorted(sector.items(), key=lambda x:x[1], reverse=True)
    top_sec = sector_sorted[0][1] if sector_sorted else 0
    expected_sec = (50*3)/37.0
    sec_ratio = top_sec / expected_sec if expected_sec else 1

    final_score = defaultdict(float)
    for num,c in cnt.items(): final_score[num]+=c*2
    for num,c in sector_sorted[:5]: final_score[num]+=c
    top3 = sorted(final_score.items(), key=lambda x:x[1], reverse=True)[:3]

    confidence = 25
    if ratio >= 3.3: confidence+=40
    elif ratio >= 2.8: confidence+=20
    elif ratio >= 2.3: confidence+=10

    if sec_ratio >= 2.6: confidence+=35
    elif sec_ratio >= 2.2: confidence+=15
    elif sec_ratio >= 1.7: confidence+=5

    is_play = (ratio >= 3.0 and sec_ratio >= 2.4 and max_c>=8)
    if is_play: confidence = min(92, confidence+10)
    else: confidence = min(70, confidence)

    return {"top3":top3,"confidence":round(confidence,1),"is_play":is_play,"ratio":round(ratio,2),"sec_ratio":round(sec_ratio,2),"expected":round(expected,2),"max_c":max_c,"hot":top,"total":total,"last":data[-1]}

def format_msg(res, auto=False):
    if not res: return f"عندك {len(history)} رقم، احتاج 20"
    header = "🔔 فرصة نادرة!\n" if res['is_play'] and auto else ("🧠 تحليل عبقري V17\n" if not auto else "📊 فحص سريع كل 10 أرقام\n")
    txt = header
    txt+=f"📊 المجموع {res['total']} - الطبيعي {res['expected']} - الأقوى {res['hot'][0][0]} طالع {res['max_c']} ({res['ratio']}x)\n"
    txt+=f"🎯 ترشيح: {res['top3'][0][0]}, {res['top3'][1][0]}, {res['top3'][2][0]}\n"
    txt+=f"📈 الثقة: {res['confidence']}%\n"
    txt+=f"📍 قطاع: {res['sec_ratio']}x\n"
    if res['is_play']:
        txt+=f"✅ العب الآن - وحش + قطاع\n"
        txt+=f"💰 العب {res['top3'][0][0]} + جيرانه {get_neighbors(res['top3'][0][0],1)}\n"
    else:
        if res['confidence'] < 50:
            txt+=f"❌ لا تلعب - طاولة عشوائية، وفر فلوسك\n"
            txt+=f"⏳ انتظر {15 - (res['total'] % 15)} أرقام أو غير الطاولة\n"
        else:
            txt+=f"⚠️ مراقبة - قربنا بس مو الآن\n"
            txt+=f"👀 خليك متابع\n"
    txt+=f"🔥 الأكثر: {', '.join([f'{n}x{c}' for n,c in res['hot']])}"
    return txt

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🧠 V17 SMART TALKER\nيتكلم كل 10 أرقام + اذا دوست تحليل عبقري يجاوب فورا حتى لو 200 رقم\nدز 20 رقم", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🗑️ تم المسح", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res = analyze()
    bot.send_message(m.chat.id, format_msg(res) if res else f"عندك {len(history)} احتاج 20", reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text or m.text.startswith('/') or "مسح" in m.text or "عبقري" in m.text: return
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0 <= int(n) <= 36]
    if nums:
        history.extend(nums)
        total = len(history)
        bot.send_message(m.chat.id, f"✅ +{len(nums)} - المجموع {total}", reply_markup=main_markup())
        res = analyze()
        if not res: return
        # يتكلم كل 10 ارقام حتى لو لا تلعب + اذا فرصة حقيقية
        if total % 10 == 0 or res['is_play']:
            bot.send_message(m.chat.id, format_msg(res, auto=True), reply_markup=main_markup())

threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
