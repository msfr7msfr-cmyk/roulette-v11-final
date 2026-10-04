import os, re, threading, cv2, pytesseract
from collections import Counter, deque, defaultdict
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup
import math

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V14 GENIUS - 7 Algorithms - 3 Numbers Only"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get("BOT_TOKEN","")
bot = telebot.TeleBot(BOT_TOKEN)
history = deque(maxlen=300)

RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
# ترتيب عجلة الروليت الأوروبية الحقيقية
WHEEL_ORDER = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

def get_neighbors(num, n=2):
    if num not in WHEEL_ORDER: return []
    idx = WHEEL_ORDER.index(num)
    res=[]
    for i in range(-n, n+1):
        res.append(WHEEL_ORDER[(idx+i) % len(WHEEL_ORDER)])
    return res

def main_markup():
    m = ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("🧠 تحليل عبقري", "مسح 🗑️")
    return m

def genius_analyze():
    if len(history) < 20:
        return None
    data = list(history)
    last = data[-1]
    counter = Counter(data)
    total = len(data)

    # 1. HOT - الأكثر تكرارا
    hot = counter.most_common(5)

    # 2. MARKOV - ماذا يأتي بعد آخر 3 أرقام
    transitions = defaultdict(list)
    for i in range(len(data)-1):
        transitions[data[i]].append(data[i+1])
    markov_candidates = Counter(transitions.get(last, [])).most_common(3)

    # 3. GAP - الأرقام المتأخرة (Overdue)
    last_seen = {}
    for i, num in enumerate(data):
        last_seen[num] = i
    gap_scores = {}
    for n in range(37):
        gap = total - last_seen.get(n, 0)
        # اذا الرقم ما طلع من زمان، احتماله يزيد
        gap_scores[n] = gap
    overdue = sorted(gap_scores.items(), key=lambda x: x[1], reverse=True)[:5]

    # 4. SECTOR - تحيز قطاع العجلة
    sector_count = defaultdict(int)
    for num in data[-50:]: # آخر 50
        for nb in get_neighbors(num, 1):
            sector_count[nb] += 1
    sector_bias = sorted(sector_count.items(), key=lambda x: x[1], reverse=True)[:5]

    # 5. NEIGHBOR of HOT
    neighbor_of_hot = []
    for num,_ in hot[:2]:
        neighbor_of_hot.extend(get_neighbors(num, 1))
    neighbor_counter = Counter(neighbor_of_hot).most_common(5)

    # 6. Scoring System - دمج كل الخوارزميات
    final_score = defaultdict(float)
    for num,cnt in hot: final_score[num] += cnt * 3.0
    for num,cnt in markov_candidates: final_score[num] += cnt * 4.0
    for num,gap in overdue: final_score[num] += (gap/total)*10
    for num,cnt in sector_bias: final_score[num] += cnt * 2.5
    for num,cnt in neighbor_counter: final_score[num] += cnt * 2.0

    # بونص اذا الرقم تكرر كثير بالـ 10 الأخيرة
    for num in data[-10:]:
        final_score[num] += 1.5

    top3 = sorted(final_score.items(), key=lambda x: x[1], reverse=True)[:3]

    # حساب الثقة - Consensus
    max_score = top3[0][1] if top3 else 0
    # اذا 3 خوارزميات اتفقت على نفس الرقم، الثقة عالية
    confidence = min(95, (max_score / 10 * 100) * 0.7 + (len([s for s in final_score.values() if s>5])/3)*10)
    # تعديل الثقة حسب قوة البيانات
    if total < 50: confidence *= 0.6
    elif total < 100: confidence *= 0.85

    return {
        "top3": [n for n,_ in top3],
        "scores": top3,
        "confidence": round(confidence,1),
        "hot": hot[:3],
        "markov": markov_candidates,
        "overdue": overdue[:3],
        "last": last,
        "total": total
    }

def format_genius(res):
    if not res: return "دز 20 رقم على الأقل"
    top3 = res["top3"]
    conf = res["confidence"]

    status = "✅ العب - ثقة عالية" if conf >= 80 else "⚠️ انتظر - ثقة ضعيفة" if conf >= 60 else "❌ لا تلعب - عشوائي"

    txt = f"🧠 V14 GENIUS - تحليل عبقري\n"
    txt += f"📊 {res['total']} رقم - اخر: {res['last']}\n"
    txt += f"━━━━━━━━━━━━━━\n"
    txt += f"🎯 الأرقام الثلاثة الذهبية:\n"
    for i, (num, score) in enumerate(res["scores"], 1):
        txt += f"{i}. {num} (قوة {round(score,1)})\n"
    txt += f"━━━━━━━━━━━━━━\n"
    txt += f"🔥 الأكثر تكرارا: {res['hot']}\n"
    txt += f"🔗 بعد {res['last']} يأتي: {res['markov']}\n"
    txt += f"⏰ متأخرة: {res['overdue']}\n"
    txt += f"━━━━━━━━━━━━━━\n"
    txt += f"📈 نسبة الثقة: {conf}%\n"
    txt += f"{status}\n"
    if conf >= 80:
        txt += f"\n💰 طريقة اللعب:\nالعب {top3[0]} + جيرانه في العجلة\n{get_neighbors(top3[0],1)}\nراهن مباشر + سبليت"
    else:
        txt += f"\n💤 نصيحة: لا تلعب الآن، اجمع 30 رقم اضافي أو غير الطاولة"
    return txt

# === Handlers ===
def extract_from_image(path):
    try:
        img = cv2.imread(path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789 '
        text = pytesseract.image_to_string(thresh, config=config)
        nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', text) if 0 <= int(n) <= 36]
        return nums
    except: return []

@bot.message_handler(content_types=['photo'])
def photo_h(m):
    try:
        bot.reply_to(m, "🧠 GENIUS يقرا الصورة بـ 7 خوارزميات...")
        file_info = bot.get_file(m.photo[-1].file_id)
        data = bot.download_file(file_info.file_path)
        p = f"/tmp/{m.photo[-1].file_id}.jpg"
        with open(p,'wb') as f: f.write(data)
        nums = extract_from_image(p)
        if nums:
            history.extend(nums)
            bot.send_message(m.chat.id, f"✅ {len(nums)} رقم - المجموع {len(history)}", reply_markup=main_markup())
            res = genius_analyze()
            if res: bot.send_message(m.chat.id, format_genius(res), reply_markup=main_markup())
        else:
            bot.send_message(m.chat.id, "❌ ما قدرت اقرا، دز كتابة", reply_markup=main_markup())
    except Exception as e:
        bot.send_message(m.chat.id, f"خطأ: {e}")

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🧠 V14 GENIUS\nبوت عبقري - 7 خوارزميات - 3 أرقام فقط\nدز 30 رقم على الأقل ليبدأ الذكاء", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🗑️ تم المسح - V14 GENIUS جاهز", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res = genius_analyze()
    if res:
        bot.send_message(m.chat.id, format_genius(res), reply_markup=main_markup())
    else:
        bot.send_message(m.chat.id, f"عندك {len(history)} رقم بس، احتاج 20 على الأقل", reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text: return
    if "مسح" in m.text or "عبقري" in m.text or m.text.startswith('/'): return
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0 <= int(n) <= 36]
    if nums:
        history.extend(nums)
        bot.send_message(m.chat.id, f"✅ {len(nums)} رقم - المجموع {len(history)}", reply_markup=main_markup())
        if len(history) >= 15:
            res = genius_analyze()
            if res and len(nums) >= 2:
                bot.send_message(m.chat.id, format_genius(res), reply_markup=main_markup())
    else:
        bot.send_message(m.chat.id, "دز ارقام 0-36", reply_markup=main_markup())

threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
