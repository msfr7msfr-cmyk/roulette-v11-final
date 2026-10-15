import os
import re
import json
import time
import hmac
import sqlite3
import logging
from collections import Counter
from flask import Flask, request, abort
import requests

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
DEFAULT_HORIZON = int(os.getenv("PREDICTION_HORIZON", "5"))

if DEFAULT_HORIZON not in (5, 10):
    DEFAULT_HORIZON = 5

MIN_HISTORY = 100
PICK_COUNT = 5

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette")

HTTP = requests.Session()

WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13,
    36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14,
    31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
WHEEL_SIZE = 37

# ================== قاعدة البيانات ==================

def connect_db():
    con = sqlite3.connect(DB_FILE, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect_db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY,
            history TEXT NOT NULL DEFAULT '[]',
            prediction TEXT NOT NULL DEFAULT '[]',
            horizon INTEGER NOT NULL DEFAULT 5,
            spins_seen INTEGER NOT NULL DEFAULT 0,
            prediction_id INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            numbers TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            spins_seen INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS updates_seen (
            update_id TEXT PRIMARY KEY
        );
        """)

init_db()

def get_user(chat_id):
    with connect_db() as con:
        row = con.execute("SELECT * FROM users WHERE chat_id =?", (str(chat_id),)).fetchone()
        if row is None:
            con.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            row = con.execute("SELECT * FROM users WHERE chat_id =?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id, **values):
    if not values:
        return
    allowed = {"history", "prediction", "horizon", "spins_seen", "prediction_id"}
    fields = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in ("history", "prediction"):
            value = json.dumps(value)
        fields.append(f"{key} =?")
        params.append(value)
    if not fields:
        return
    params.append(str(chat_id))
    with connect_db() as con:
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id =?", params)

def reset_user(chat_id):
    with connect_db() as con:
        con.execute("""
            INSERT INTO users(chat_id, history, prediction, horizon, spins_seen, prediction_id)
            VALUES(?, '[]', '[]',?, 0, 0)
            ON CONFLICT(chat_id) DO UPDATE SET history='[]', prediction='[]', horizon=excluded.horizon, spins_seen=0, prediction_id=0
        """, (str(chat_id), DEFAULT_HORIZON))
        con.execute("UPDATE predictions SET status='cancelled' WHERE chat_id=? AND status='active'", (str(chat_id),))

# ================== تيليجرام ==================

def send_message(chat_id, text):
    if not TOKEN:
        log.error("BOT_TOKEN is missing")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = HTTP.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=15)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            log.error("Telegram API error: %s", result)
            return False
        return True
    except Exception:
        log.exception("Failed to send Telegram message")
        return False

# ================== قراءة الأرقام ==================

def parse_numbers(text):
    tokens = [x for x in re.split(r"[\s,;،]+", text.strip()) if x]
    if not tokens:
        return []
    numbers = []
    for token in tokens:
        if not re.fullmatch(r"\d+", token):
            raise ValueError(f"القيمة غير صحيحة: {token}")
        number = int(token)
        if not 0 <= number <= 36:
            raise ValueError(f"الرقم {number} خارج النطاق 0 إلى 36")
        numbers.append(number)
    return numbers

def wheel_step(a, b):
    ia = WHEEL_INDEX[a]
    ib = WHEEL_INDEX[b]
    difference = (ib - ia) % WHEEL_SIZE
    if difference > WHEEL_SIZE / 2:
        difference -= WHEEL_SIZE
    return int(difference)

# ================== التحليل الإحصائي المتقدم ==================

def analyze_history(history):
    counts = Counter(history)
    recent20 = Counter(history[-20:])
    recent50 = Counter(history[-50:])
    recent100 = Counter(history[-100:])

    steps = [wheel_step(history[i - 1], history[i]) for i in range(1, len(history))]
    step_counts = Counter(steps)

    followers = Counter()
    last_number = history[-1]
    for i in range(len(history) - 1):
        if history[i] == last_number:
            followers[history[i + 1]] += 1

    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    black_numbers = set(range(37)) - red_numbers - {0}

    red_count = sum(1 for n in history[-50:] if n in red_numbers)
    black_count = sum(1 for n in history[-50:] if n in black_numbers)
    even_count = sum(1 for n in history[-50:] if n % 2 == 0 and n!= 0)
    odd_count = sum(1 for n in history[-50:] if n % 2!= 0)

    gaps = {}
    for number in range(37):
        positions = [i for i, n in enumerate(history) if n == number]
        if positions:
            gaps[number] = len(history) - positions[-1] - 1
        else:
            gaps[number] = len(history)

    trends = {}
    for number in range(37):
        recent_freq = recent20.get(number, 0) / 20
        older_freq = (counts.get(number, 0) - recent20.get(number, 0)) / max(len(history) - 20, 1)
        trends[number] = recent_freq - older_freq

    return {
        "counts": counts,
        "recent20": recent20,
        "recent50": recent50,
        "recent100": recent100,
        "steps": steps,
        "step_counts": step_counts,
        "followers": followers,
        "red_count": red_count,
        "black_count": black_count,
        "even_count": even_count,
        "odd_count": odd_count,
        "gaps": gaps,
        "trends": trends
    }

def choose_numbers(history):
    if not history:
        return WHEEL[:PICK_COUNT]

    data = analyze_history(history)
    scores = {n: 0.0 for n in range(37)}

    windows = [
        (history[-100:], 0.8),
        (history[-50:], 1.0),
        (history[-20:], 1.2),
        (history[-10:], 1.5)
    ]
    for window, weight in windows:
        counts = Counter(window)
        total = len(window)
        for number in range(37):
            probability = (counts[number] + 1) / (total + 37)
            scores[number] += weight * (probability - 1 / 37)

    followers = data["followers"]
    total_followers = sum(followers.values())
    if total_followers:
        shrink = total_followers / (total_followers + 12)
        for number in range(37):
            probability = (followers[number] + 0.5) / (total_followers + 18.5)
            scores[number] += 0.9 * shrink * (probability - 1 / 37)

    steps = data["steps"][-30:]
    if len(steps) >= 8:
        step_counts = Counter(steps)
        total_steps = len(steps)
        last_number = history[-1]
        for number in range(37):
            step = wheel_step(last_number, number)
            probability = (step_counts[step] + 0.5) / (total_steps + 18.5)
            scores[number] += 0.12 * (probability - 1 / 37)

    recent = history[-50:]
    for candidate in range(37):
        index = WHEEL_INDEX[candidate]
        neighborhood = {WHEEL[(index + offset) % WHEEL_SIZE] for offset in range(-2, 3)}
        observed = sum(1 for number in recent if number in neighborhood)
        expected = len(recent) * 5 / 37
        scores[candidate] += 0.08 * (observed - expected) / max(len(recent), 1)

    gaps = data["gaps"]
    avg_gap = sum(gaps.values()) / 37
    for number in range(37):
        if gaps[number] > avg_gap * 1.5:
            scores[number] += 0.15 * (gaps[number] - avg_gap) / avg_gap

    trends = data["trends"]
    for number in range(37):
        if trends[number] > 0:
            scores[number] += 0.2 * trends[number]

    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    recent50 = data["recent50"]
    total50 = sum(recent50.values())
    if total50 > 0:
        red_ratio = data["red_count"] / total50
        black_ratio = data["black_count"] / total50
        even_ratio = data["even_count"] / total50
        odd_ratio = data["odd_count"] / total50

        for number in range(37):
            if number in red_numbers and red_ratio < 0.45:
                scores[number] += 0.1
            elif number in (set(range(37)) - red_numbers - {0}) and black_ratio < 0.45:
                scores[number] += 0.1
            if number % 2 == 0 and number!= 0 and even_ratio < 0.45:
                scores[number] += 0.1
            elif number % 2!= 0 and odd_ratio < 0.45:
                scores[number] += 0.1

    if len(history) >= 10:
        last_10 = history[-10:]
        for pattern_len in [3, 4, 5]:
            for i in range(len(history) - pattern_len):
                pattern = tuple(history[i:i + pattern_len])
                if pattern == tuple(last_10[-pattern_len:]):
                    next_number = history[i + pattern_len] if i + pattern_len < len(history) else None
                    if next_number is not None:
                        scores[next_number] += 0.05 * pattern_len

    wheel_rank = {number: index for index, number in enumerate(WHEEL)}
    ranked = sorted(range(37), key=lambda n: (-scores[n], wheel_rank[n]))
    return ranked[:PICK_COUNT]

# ================== إنشاء التوقع ==================

def create_prediction(chat_id, history, horizon):
    numbers = choose_numbers(history)
    with connect_db() as con:
        con.execute("UPDATE predictions SET status='cancelled' WHERE chat_id=? AND status='active'", (str(chat_id),))
        cursor = con.execute(
            "INSERT INTO predictions(chat_id, numbers, horizon, status, created_at) VALUES(?,?,?, 'active',?)",
            (str(chat_id), json.dumps(numbers), horizon, time.time())
        )
        prediction_id = cursor.lastrowid
        con.execute(
            "UPDATE users SET prediction=?, horizon=?, spins_seen=0, prediction_id=? WHERE chat_id=?",
            (json.dumps(numbers), horizon, prediction_id, str(chat_id))
        )
    return numbers

# ================== تسجيل النتائج ==================

def record_result(chat_id, update_id, number):
    with connect_db() as con:
        try:
            con.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
        except sqlite3.IntegrityError:
            return None
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            return None
        user = dict(row)
        history = json.loads(user["history"])
        prediction = json.loads(user["prediction"])
        if len(history) < MIN_HISTORY:
            return None
        history.append(number)
        prediction_id = user["prediction_id"]
        spins_seen = int(user["spins_seen"])
        horizon = int(user["horizon"])
        hit = number in prediction
        event = "miss"
        if prediction_id:
            pred = con.execute("SELECT status FROM predictions WHERE id=? AND chat_id=?", (prediction_id, str(chat_id))).fetchone()
            if pred and pred["status"] == "active":
                spins_seen += 1
                if hit:
                    event = "hit"
                    con.execute("UPDATE predictions SET status='hit', spins_seen=? WHERE id=?", (spins_seen, prediction_id))
                elif spins_seen >= horizon:
                    event = "expired"
                    con.execute("UPDATE predictions SET status='miss', spins_seen=? WHERE id=?", (spins_seen, prediction_id))
                else:
                    event = "miss"
                    con.execute("UPDATE predictions SET spins_seen=? WHERE id=?", (spins_seen, prediction_id))
        con.execute("UPDATE users SET history=?, spins_seen=? WHERE chat_id=?", (json.dumps(history), spins_seen, str(chat_id)))
        return {"event": event, "history": history, "prediction": prediction, "spins_seen": spins_seen, "horizon": horizon}

# ================== الإحصاءات ==================

def get_stats(chat_id):
    with connect_db() as con:
        rows = con.execute("SELECT status, COUNT(*) AS total FROM predictions WHERE chat_id=? GROUP BY status", (str(chat_id),)).fetchall()
    result = {row["status"]: row["total"] for row in rows}
    completed = result.get("hit", 0) + result.get("miss", 0)
    rate = result.get("hit", 0) / completed if completed else None
    return result, rate, completed

# ================== الأوامر والرسائل ==================

def help_message():
    return (
        "🧠 بوت تحليل الروليت الأوروبية - النسخة المتقدمة\n\n"
        "أرسل سجلًا من 100 رقم أو أكثر في رسالة واحدة.\n"
        "بعدها أرسل كل نتيجة جديدة كرقم منفرد.\n\n"
        "الأوامر:\n"
        "/start - بدء جلسة جديدة\n"
        "/status - عرض حالة الجلسة\n"
        "/stats - عرض إحصاءات التوقعات\n"
        "/horizon5 - اختبار لمدة 5 لفات\n"
        "/horizon10 - اختبار لمدة 10 لفات\n"
        "/help - المساعدة\n\n"
        "⚙️ الخوارزمية المتقدمة تشمل:\n"
        "• التحليل التكراري المرجح\n"
        "• تحليل التابع (Follower)\n"
        "• تحليل الخطوات على العجلة\n"
        "• تحليل الجوار على العجلة\n"
        "• تحليل الفجوات (Gap)\n"
        "• تحليل الاتجاهات (Trend)\n"
        "• تحليل التوازن (Balance)\n"
        "• تحليل الأنماط المتكررة\n\n"
        "⚠️ تنبيه: لا توجد ضمانات للفوز. النتائج السابقة لا تحدد النتيجة التالية في الروليت العادلة."
    )

def process_message(message, update_id):
    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    if not text:
        return
    if text == "/start":
        reset_user(chat_id)
        send_message(chat_id, help_message())
        return
    if text == "/help":
        send_message(chat_id, help_message())
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if text in ("/horizon5", "/horizon10"):
        if len(history) < MIN_HISTORY:
            send_message(chat_id, "أرسل سجلًا من 100 رقم على الأقل أولاً.")
            return
        horizon = 5 if text == "/horizon5" else 10
        numbers = create_prediction(chat_id, history, horizon)
        send_message(chat_id, f"تم ضبط فترة الاختبار على {horizon} لفات.\nالأرقام الخمسة المرشحة: {numbers}\nهذه ترشيحات تجريبية وليست ضماناً.")
        return
    if text == "/status":
        user = get_user(chat_id)
        history = json.loads(user["history"])
        prediction = json.loads(user["prediction"])
        send_message(chat_id, f"عدد النتائج المسجلة: {len(history)}\nآخر رقم: {history[-1] if history else 'لا يوجد'}\nالأرقام المرشحة: {prediction or 'لا يوجد'}\nفترة الاختبار: {user['horizon']} لفات\nاللفات في التوقع الحالي: {user['spins_seen']}")
        return
    if text == "/stats":
        stats, rate, completed = get_stats(chat_id)
        rate_text = f"{rate * 100:.1f}%" if rate is not None else "لا توجد بيانات كافية"
        send_message(chat_id, "📊 إحصاءات الاختبار\n" f"التوقعات المكتملة: {completed}\n" f"التوقعات المصيبة: {stats.get('hit', 0)}\n" f"التوقعات غير المصيبة: {stats.get('miss', 0)}\n" f"معدل الإصابة: {rate_text}\n\n" "معدل الإصابة لا يساوي الربح المالي.")
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as error:
        send_message(chat_id, f"⚠️ {error}\nأرسل أرقامًا صحيحة من 0 إلى 36.")
        return
    if not numbers:
        send_message(chat_id, "أرسل 100 رقم أو أكثر لبدء الجلسة، ثم أرسل كل نتيجة جديدة وحدها.")
        return
    if len(numbers) >= MIN_HISTORY:
        pred = create_prediction(chat_id, numbers, DEFAULT_HORIZON)
        save_user(chat_id, history=numbers, prediction=pred, horizon=DEFAULT_HORIZON, spins_seen=0)
        send_message(chat_id, "✅ تم تحليل السجل بنجاح.\n" f"عدد الأرقام: {len(numbers)}\n" f"آخر رقم في السجل: {numbers[-1]}\n" f"الأرقام الخمسة المرشحة: {pred}\n" f"فترة الاختبار: {DEFAULT_HORIZON} لفات\n\n" "أرسل النتيجة التالية كرقم منفرد بعد ظهورها.")
        return
    if len(numbers)!= 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} رقمًا.\nللبداية أرسل 100 رقم على الأقل دفعة واحدة. بعدها أرسل كل نتيجة جديدة كرقم منفرد.")
        return
    number = numbers[0]
    result = record_result(chat_id, update_id, number)
    if result is None:
        send_message(chat_id, "تعذر تسجيل النتيجة أو أن سجل البداية غير مكتمل.")
        return
    event = result["event"]
    prediction = result["prediction"]
    spins_seen = result["spins_seen"]
    horizon = result["horizon"]
    history = result["history"]
    if event == "hit":
        send_message(chat_id, f"🟢 ظهَر الرقم {number} ضمن الأرقام {prediction}.\nتمت الإصابة خلال {spins_seen} لفة.\nسيتم الآن تحليل السجل المحدّث.")
        pred = create_prediction(chat_id, history, horizon)
        send_message(chat_id, f"🎯 الأرقام الخمسة المرشحة الجديدة: {pred}")
    elif event == "expired":
        send_message(chat_id, f"انتهت {horizon} لفات دون إصابة.\nآخر نتيجة: {number}.\nسيتم تحديث التحليل من السجل الجديد.")
        pred = create_prediction(chat_id, history, horizon)
        send_message(chat_id, f"🎯 الأرقام الخمسة المرشحة الجديدة: {pred}")
    else:
        send_message(chat_id, f"تم تسجيل الرقم {number}.\nالنتيجة {spins_seen}/{horizon}.\nالأرقام الثابتة الحالية: {prediction}")

# ================== Flask Webhook ==================

@app.get("/")
def home():
    return "Roulette analysis bot is running.", 200

@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return "ok", 200
    message = update.get("message")
    if not isinstance(message, dict):
        return "ok", 200
    update_id = str(update.get("update_id", time.time_ns()))
    try:
        process_message(message, update_id)
    except Exception:
        log.exception("Error processing Telegram update %s", update_id)
    return "ok", 200

if __name__ == "__main__":
    init_db()
    if not TOKEN:
        log.warning("BOT_TOKEN is not set. Telegram messages will not work")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
