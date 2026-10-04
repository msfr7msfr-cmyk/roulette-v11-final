import os, re, threading, cv2, pytesseract
from collections import Counter, deque, defaultdict
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V15 ULTRA FILTER - Auto Alert"
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

def ultra_analyze():
    if len(history) < 25:
        return None
    data = list(history)
    total = len(data)
    cnt = Counter(data)
    expected = total / 37.0

    # 1. فلتر القوة الحقيقية
    strong_nums = []
    for num, c in cnt.items():
        if c >= expected * 2.2 and c >= 6: # لازم ضعفين ونص و 6 مرات على الأقل
            strong_nums.append((num, c))

    # 2. تحيز القطاع
    sector = defaultdict(int)
    for num in data[-40:]:
        for nb in get_neighbors(num, 1):
            sector[nb] += 1
    sector_top = sorted(sector.items(), key=lambda x: x[1], reverse=True)
    sector_bias_ratio = sector_top[0][1] / (40*3/37) if sector_top else 1 # مقارنة بالطبيعي

    # 3. التكرار الحقيقي
    hot = cnt.most_common(3)

    # حساب الثقة الحقيقية - صارم جدا
    confidence = 0
    reason = []

    if strong_nums:
        confidence += 35
        reason.append(f"رقم قوي {strong_nums[0][0]} طالع {strong_nums[0][1]} مرات")
    if sector_bias_ratio >= 1.8:
        confidence += 35
        reason.append(f"تحيز قطاع {sector_bias_ratio:.1f}x")
    if hot[0][1] >= 7:
        confidence += 20
        reason.append(f"ساخن جدا {hot[0][0]}")
    if total >= 80:
        confidence += 10

    # اذا رقم واحد يجمع كل الشروط
    final_score = defaultdict(float)
    for num,c in cnt.items():
        # نقطة لكل مرة
        final_score[num] += c * 2
        if c >= expected*2: final_score[num] += 15

    for num,c in sector_top[:5]:
        final_score[num] += c * 1.5

    top3 = sorted(final_score.items(), key=lambda x: x[1], reverse=True)[:3]

    # الثقة النهائية
    # اذا ما فيه شروط قوية، الثقة تنزل ل 30-50
    if not strong_nums or sector_bias_ratio < 1.6:
        confidence = min(confidence, 55)

    is_play = confidence >= 80 and len(strong_nums) > 0 and sector_bias_ratio >= 1.7

    return {
        "top3": top3,
        "confidence": round(confidence,1),
        "is_play": is_play,
        "strong": strong_nums,
        "sector_ratio": round(sector_bias_ratio,2),
        "hot": hot,
        "total": total,
        "last": data[-1],
        "reason": reason
    }

def format_ultra(res, auto=False):
    if not res:
        return f"عندك {len(history)} رقم، احتاج 25 على الأقل"

    header = "🔔 تنبيه تلقائي - فرصة ذهبية!\n" if auto else "🧠 V15 ULTRA FILTER\n"
    txt = header
    txt += f"📊 {res['total']} رقم - اخر: {res['last']}\n"
    txt += f"━━━━━━━━━━━━━━\n"

    if res['is_play']:
        txt += f"🎯 الأرقام الثلاثة:\n"
        for i,(num,sc) in enumerate(res['top3'],1):
            txt += f"{i}. {num} (قوة {round(sc,1)})\n"
        txt += f"━━━━━━━━━━━━━━\n"
        txt += f"🔥 القوي: {res['strong'][:2]}\n"
        txt += f"🎡 تحيز القطاع: {res['sector_ratio']}x\n"
        txt += f"📈 الثقة: {res['confidence']}%\n"
        txt += f"✅ العب - فرصة حقيقية\n"
        txt += f"💡 السبب: {', '.join(res['reason'])}\n"
        txt += f"\n💰 العب: {res['top3'][0][0]} + جيرانه {get_neighbors(res['top3'][0][0],1)}"
    else:
        txt += f"📈 الثقة: {res['confidence']}%\n"
        txt += f"❌ لا تلعب - انتظر\n"
        txt += f"💤 السبب: "
        if not res['strong']:
            txt += f"ما فيه رقم قوي (المتوقع {res['total']/37:.1f} لكل رقم)\n"
        if res['sector_ratio'] < 1.7:
            txt += f"العجلة عشوائية {res['sector_ratio']}x\n"
        txt += f"🔥 الأكثر: {res['hot']}\n"
        txt += f"💡 انتظر 10-20 رقم اضافي أو غير الطاولة"
    return txt

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
        file_info = bot.get_file(m.photo[-1].file_id)
        data = bot.download_file(file_info.file_path)
        p = f"/tmp/{m.photo[-1].file_id}.jpg"
        with open(p,'wb') as f: f.write(data)
        nums = extract_from_image(p)
        if nums:
            history.extend(nums)
            bot.send_message(m.chat.id, f"✅ {len(nums)} رقم - المجموع {len(history)}", reply_markup=main_markup())
            res = ultra_analyze()
            if res:
                # تنبيه تلقائي فقط اذا فرصة حقيقية
                if res['is_play']:
                    bot.send_message(m.chat.id, format_ultra(res, auto=True), reply_markup=main_markup())
                elif len(history) % 10 == 0: # كل 10 ارقام يعطيك تحديث اذا طلبت
                    pass
        else:
            bot.send_message(m.chat.id, "❌ ما قريت", reply_markup=main_markup())
    except Exception as e:
        bot.send_message(m.chat.id, f"خطأ {e}")

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🧠 V15 ULTRA FILTER\nما يقول العب إلا إذا شاف 80%+ حقيقي\nدز 25 رقم على الأقل\nراح أنبهك لحالي اذا شفت فرصة", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🗑️ تم المسح - V15 جاهز", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res = ultra_analyze()
    if res:
        bot.send_message(m.chat.id, format_ultra(res), reply_markup=main_markup())
    else:
        bot.send_message(m.chat.id, f"عندك {len(history)} رقم، احتاج 25", reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text or m.text.startswith('/') or "مسح" in m.text or "عبقري" in m.text:
        return
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0 <= int(n) <= 36]
    if nums:
        history.extend(nums)
        bot.send_message(m.chat.id, f"✅ {len(nums)} رقم - المجموع {len(history)}", reply_markup=main_markup())
        res = ultra_analyze()
        # تنبيه تلقائي حقيقي
        if res and res['is_play']:
            bot.send_message(m.chat.id, format_ultra(res, auto=True), reply_markup=main_markup())
    else:
        if len(m.text) < 20:
            bot.send_message(m.chat.id, "دز ارقام 0-36", reply_markup=main_markup())

threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
