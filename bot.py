import os, re, threading
from collections import deque, defaultdict, Counter
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "V16 FINAL FIX - 30% default"
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
    if len(history) < 30:
        return None
    data = list(history)
    total = len(data)
    cnt = Counter(data)
    expected = total / 37.0

    # قطاع 50 رقم اخير
    sector = defaultdict(int)
    for num in data[-50:]:
        for nb in get_neighbors(num, 1):
            sector[nb] += 1
    sector_sorted = sorted(sector.items(), key=lambda x: x[1], reverse=True)
    top_sector = sector_sorted[0][1] if sector_sorted else 0
    expected_sector = (50*3)/37.0
    sector_ratio = top_sector / expected_sector if expected_sector else 1

    # اقوى ارقام
    top_cnt = cnt.most_common(3)
    max_count = top_cnt[0][1] if top_cnt else 0

    # النسبة الحقيقية
    ratio = max_count / expected if expected else 0

    # حساب الثقة يبدأ من 0
    reasons = []

    # V16 صارم جدا
    is_play = False
    confidence = 25.0 # البداية 25% فقط

    if ratio >= 3.3 and max_count >= 9:
        confidence += 40
        reasons.append(f"وحش {top_cnt[0][0]} طالع {max_count} (يحتاج 3.3x وعندك {ratio:.2f}x)")
        monster_ok = True
    elif ratio >= 3.0 and max_count >= 8:
        confidence += 20
        reasons.append(f"شبه وحش {top_cnt[0][0]} {max_count}x ({ratio:.2f}x) - يحتاج 3.3x")
        monster_ok = False
    else:
        reasons.append(f"ما فيه وحش - اكبر رقم {top_cnt[0][0]} طالع {max_count} والطبيعي {expected:.1f} ({ratio:.2f}x)")
        monster_ok = False

    if sector_ratio >= 2.6:
        confidence += 40
        reasons.append(f"قطاع محشور {sector_ratio:.2f}x")
        sector_ok = True
    elif sector_ratio >= 2.3:
        confidence += 15
        reasons.append(f"تحيز بسيط {sector_ratio:.2f}x (احتاج 2.6x)")
        sector_ok = False
    else:
        reasons.append(f"عشوائي {sector_ratio:.2f}x")
        sector_ok = False

    # العب فقط اذا الاثنين مع بعض
    if monster_ok and sector_ok:
        is_play = True
        confidence = min(90, confidence + 10)
    else:
        is_play = False
        confidence = min(55, confidence) # مستحيل يفوت 55 اذا مو وحش حقيقي

    final_score = defaultdict(float)
    for num,c in cnt.items():
        final_score[num] += c*2
    for num,c in sector_sorted[:5]:
        final_score[num] += c
    top3 = sorted(final_score.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "top3": top3,
        "confidence": round(confidence,1),
        "is_play": is_play,
        "ratio": round(ratio,2),
        "sector_ratio": round(sector_ratio,2),
        "expected": round(expected,2),
        "max_count": max_count,
        "hot": top_cnt,
        "total": total,
        "last": data[-1],
        "reasons": reasons
    }

def format_msg(res, auto=False):
    if not res:
        return f"عندك {len(history)} رقم، احتاج 30"
    header = "🔔 تنبيه تلقائي - فرصة نادرة!\n" if auto else "🧠 V16 FINAL FIX\n"
    txt = header
    txt += f"📊 {res['total']} رقم - الطبيعي {res['expected']} - اقوى رقم طالع {res['max_count']} ({res['ratio']}x)\n"
    txt += f"━━━━━━━━━━━━━━\n"
    txt += f"🎯 الثلاثة: {', '.join([str(n[0]) for n in res['top3']])}\n"
    txt += f"📈 الثقة: {res['confidence']}%\n"
    if res['is_play']:
        txt += f"✅ العب - فرصة حقيقية\n"
        txt += f"💰 العب: {res['top3'][0][0]} + جيرانه {get_neighbors(res['top3'][0][0],1)}\n"
    else:
        txt += f"❌ لا تلعب\n"
    txt += f"💤 السبب:\n"
    for r in res['reasons']:
        txt += f"- {r}\n"
    txt += f"⏳ قطاع: {res['sector_ratio']}x"
    return txt

@bot.message_handler(commands=['start'])
def start_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🧠 V16 FINAL - ما اقول 100% ابد\nالبداية 25% فقط، ما اوصل 85% الا اذا وحش حقيقي\nدز 30 رقم", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "مسح" in m.text)
def clear_h(m):
    history.clear()
    bot.send_message(m.chat.id, "🗑️ تم المسح - V16 صارم", reply_markup=main_markup())

@bot.message_handler(func=lambda m: m.text and "عبقري" in m.text)
def genius_h(m):
    res = ultra_analyze()
    bot.send_message(m.chat.id, format_msg(res) if res else f"عندك {len(history)} احتاج 30", reply_markup=main_markup())

@bot.message_handler(func=lambda m: True)
def all_text(m):
    if not m.text or m.text.startswith('/') or "مسح" in m.text or "عبقري" in m.text:
        return
    nums = [int(n) for n in re.findall(r'\b\d{1,2}\b', m.text) if 0 <= int(n) <= 36]
    if nums:
        history.extend(nums)
        bot.send_message(m.chat.id, f"✅ {len(nums)} - المجموع {len(history)}", reply_markup=main_markup())
        res = ultra_analyze()
        if res and res['is_play']:
            bot.send_message(m.chat.id, format_msg(res, auto=True), reply_markup=main_markup())
    else:
        if len(m.text) < 20:
            bot.send_message(m.chat.id, "دز ارقام 0-36", reply_markup=main_markup())

threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
