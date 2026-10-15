import os
import re
import json
import time
import hmac
import sqlite3
import logging
import math
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

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = set(range(37)) - RED_NUMBERS - {0}

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
            prediction_id INTEGER NOT NULL DEFAULT 0,
            model_weights TEXT NOT NULL DEFAULT '{}'
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
    allowed = {"history", "prediction", "horizon", "spins_seen", "prediction_id", "model_weights"}
    fields = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in ("history", "prediction", "model_weights"):
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
            INSERT INTO users(chat_id, history, prediction, horizon, spins_seen, prediction_id, model_weights)
            VALUES(?, '[]', '[]',?, 0, 0, '{}')
            ON CONFLICT(chat_id) DO UPDATE SET history='[]', prediction='[]', horizon=excluded.horizon, spins_seen=0, prediction_id=0, model_weights='{}'
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

    red_count = sum(1 for n in history[-50:] if n in RED_NUMBERS)
    black_count = sum(1 for n in history[-50:] if n in BLACK_NUMBERS)
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

    dozens = {1: 0, 2: 0, 3: 0}
    for n in history[-50:]:
        if 1 <= n <= 12:
            dozens[1] += 1
        elif 13 <= n <= 24:
            dozens[2] += 1
        elif 25 <= n <= 36:
            dozens[3] += 1

    columns = {1: 0, 2: 0, 3: 0}
    for n in history[-50:]:
        if n!= 0:
            columns[(n - 1) % 3 + 1] += 1

    wheel_neighbors = {}
    for number in range(37):
        index = WHEEL_INDEX[number]
        neighbors = [WHEEL[(index + offset) % WHEEL_SIZE] for offset in range(-2, 3)]
        wheel_neighbors[number] = sum(1 for n in history[-30:] if n in neighbors)

    sequences = {}
    for length in [2, 3, 4]:
        seq_key = f"seq_{length}"
        sequences[seq_key] = Counter()
        for i in range(len(history) - length):
            seq = tuple(history[i:i + length])
            sequences[seq_key][seq] += 1

    pairs = Counter()
    for i in range(len(history) - 1):
        pairs[(history[i], history[i + 1])] += 1

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
        "trends": trends,
        "dozens": dozens,
        "columns": columns,
        "wheel_neighbors": wheel_neighbors,
        "sequences": sequences,
        "pairs": pairs
    }

def calculate_entropy(history):
    counts = Counter(history[-100:])
    total = len(history[-100:])
    entropy = 0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy

def detect_bias(history):
    counts = Counter(history[-200:])
    total = len(history[-200:])
    expected = total / 37
    bias_scores = {}
    for number in range(37):
        observed = counts.get(number, 0)
        deviation = (observed - expected) / math.sqrt(expected) if expected > 0 else 0
        bias_scores[number] = deviation
    return bias_scores

def markov_chain_probabilities(history):
    transition_matrix = {}
    for i in range(len(history) - 1):
        current = history[i]
        next_num = history[i + 1]
        if current not in transition_matrix:
            transition_matrix[current] = Counter()
        transition_matrix[current][next_num] += 1

    transition_matrix_2 = {}
    for i in range(len(history) - 2):
        current_pair = (history[i], history[i + 1])
        next_num = history[i + 2]
        if current_pair not in transition_matrix_2:
            transition_matrix_2[current_pair] = Counter()
        transition_matrix_2[current_pair][next_num] += 1

    return transition_matrix, transition_matrix_2

def choose_numbers(history, model_weights=None):
    if not history:
        return WHEEL[:PICK_COUNT]

    if model_weights is None or not model_weights:
        model_weights = {
            "frequency": 1.0,
            "follower": 0.9,
            "wheel_step": 0.12,
            "neighborhood": 0.08,
            "gap": 0.15,
            "trend": 0.2,
            "balance": 0.1,
            "pattern": 0.05,
            "markov": 0.25,
            "bias": 0.18,
            "entropy": 0.1
        }

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
            scores[number] += model_weights.get("frequency", 1.0) * weight * (probability - 1 / 37)

    followers = data["followers"]
    total_followers = sum(followers.values())
    if total_followers:
        shrink = total_followers / (total_followers + 12)
        for number in range(37):
            probability = (followers[number] + 0.5) / (total_followers + 18.5)
            scores[number] += model_weights.get("follower", 0.9) * shrink * (probability - 1 / 37)

    steps = data["steps"][-30:]
    if len(steps) >= 8:
        step_counts = Counter(steps)
        total_steps = len(steps)
        last_number = history[-1]
        for number in range(37):
            step = wheel_step(last_number, number)
            probability = (step_counts[step] + 0.5) / (total_steps + 18.5)
            scores[number] += model_weights.get("wheel_step", 0.12) * (probability - 1 / 37)

    recent = history[-50:]
    for candidate in range(37):
        index = WHEEL_INDEX[candidate]
        neighborhood = {WHEEL[(index + offset) % WHEEL_SIZE] for offset in range(-2, 3)}
        observed = sum(1 for number in recent if number in neighborhood)
        expected = len(recent) * 5 / 37
        scores[candidate] += model_weights.get("neighborhood", 0.08) * (observed - expected) / max(len(recent), 1)

    gaps = data["gaps"]
    avg_gap = sum(gaps.values()) / 37
    for number in range(37):
        if gaps[number] > avg_gap * 1.5:
            scores[number] += model_weights.get("gap", 0.15) * (gaps[number] - avg_gap) / avg_gap

    trends = data["trends"]
    for number in range(37):
        if trends[number] > 0:
            scores[number] += model_weights.get("trend", 0.2) * trends[number]

    recent50 = data["recent50"]
    total50 = sum(recent50.values())
    if total50 > 0:
        red_ratio = data["red_count"] / total50
        black_ratio = data["black_count"] / total50
        even_ratio = data["even_count"] / total50
        odd_ratio = data["odd_count"] / total50

        for number in range(37):
            if number in RED_NUMBERS and red_ratio < 0.45:
                scores[number] += model_weights.get("balance", 0.1) * 0.1
            elif number in BLACK_NUMBERS and black_ratio < 0.45:
                scores[number] += model_weights.get("balance", 0.1) * 0.1
            if number % 2 == 0 and number!= 0 and even_ratio < 0.45:
                scores[number] += model_weights.get("balance", 0.1) * 0.1
            elif number % 2!= 0 and odd_ratio < 0.45:
                scores[number] += model_weights.get("balance", 0.1) * 0.1

    if len(history) >= 10:
        last_10 = history[-10:]
        for pattern_len in [3, 4, 5]:
            for i in range(len(history) - pattern_len):
                pattern = tuple(history[i:i + pattern_len])
                if pattern == tuple(last_10[-pattern_len:]):
                    next_number = history[i + pattern_len] if i + pattern_len < len(history) else None
                    if next_number is not None:
                        scores[next_number] += model_weights.get("pattern", 0.05) * pattern_len

    transition_matrix, transition_matrix_2 = markov_chain_probabilities(history)
    last_number = history[-1]

    if last_number in transition_matrix:
        transitions = transition_matrix[last_number]
        total_transitions = sum(transitions.values())
        for number in range(37):
            probability = (transitions.get(number, 0) + 0.5) / (total_transitions + 18.5)
            scores[number] += model_weights.get("markov", 0.25) * (probability - 1 / 37)

    if len(history) >= 2:
        last_pair = (history[-2], history[-1])
        if last_pair in transition_matrix_2:
            transitions_2 = transition_matrix_2[last_pair]
            total_transitions_2 = sum(transitions_2.values())
            for number in range(37):
                probability = (transitions_2.get(number, 0) + 0.5) / (total_transitions_2 + 18.5)
                scores[number] += model_weights.get("markov", 0.25) * 0.5 * (probability - 1 / 37)

    bias_scores = detect_bias(history)
    for number in range(37):
        if bias_scores[number] > 1.5:
            scores[number] += model_weights.get("bias", 0.18) * (bias_scores[number] - 1.5)

    entropy = calculate_entropy(history)
    max_entropy = math.log2(37)
    entropy_ratio = entropy / max_entropy if max_entropy else 1

    if entropy_ratio < 0.9:
        for number in range(37):
            if data["recent20"].get(number, 0) > 0:
                scores[number] += model_weights.get("entropy", 0.1) * data["recent20"].get(number, 0) / 20

    dozens = data["dozens"]
    columns = data["columns"]
    total50 = sum(dozens.values())
    if total50 > 0:
        for number in range(37):
            if 1 <= number <= 12 and dozens[1] / total50 < 0.3:
                scores[number] += 0.05
            elif 13 <= number <= 24 and dozens[2] / total50 < 0.3:
                scores[number] += 0.05
            elif 25 <= number <= 36 and dozens[3] / total50 < 0.3:
                scores[number] += 0.05

            if number!= 0:
                col = (number - 1) % 3 + 1
                if columns[col] / total50 < 0.3:
                    scores[number] += 0.05

    pairs = data["pairs"]
    if len(history) >= 2:
        last_pair = (history[-2], history[-1])
        if last_pair in pairs:
            total_pairs = sum(pairs.values())
            for number in range(37):
                pair_count = pairs.get((last_pair[1], number), 0)
                probability = (pair_count + 0.5) / (total_pairs + 18.5)
                scores[number] += 0.08 * (probability - 1 / 37)

    wheel_rank = {number: index for index, number in enumerate(WHEEL)}
    ranked = sorted(range(37), key=lambda n: (-scores[n], wheel_rank[n]))
    return ranked[:PICK_COUNT]

def update_model_weights(chat_id, history, prediction, result_number, hit):
    user = get_user(chat_id)
    try:
        model_weights = json.loads(user.get("model_weights") or "{}")
    except:
        model_weights = {}

    if not model_weights:
        model_weights = {
            "frequency": 1.0,
            "follower": 0.9,
            "wheel_step": 0.12,
            "neighborhood": 0.08,
            "gap": 0.15,
            "trend": 0.2,
            "balance": 0.1,
            "pattern": 0.05,
            "markov": 0.25,
            "bias": 0.18,
            "entropy": 0.1
        }

    data = analyze_history(history)
    factor_scores = {}

    recent20 = data["recent20"]
    factor_scores["frequency"] = recent20.get(result_number, 0) / 20

    followers = data["followers"]
    total_followers = sum(followers.values())
    factor_scores["follower"] = (followers.get(result_number, 0) + 0.5) / (total_followers + 18.5) if total_followers else 1/37

    steps = data["steps"][-30:]
    if len(steps) >= 8:
        step_counts = Counter(steps)
        total_steps = len(steps)
        step = wheel_step(history[-1], result_number)
        factor_scores["wheel_step"] = (step_counts.get(step, 0) + 0.5) / (total_steps + 18.5)
    else:
        factor_scores["wheel_step"] = 1/37

    index = WHEEL_INDEX[result_number]
    neighborhood = {WHEEL[(index + offset) % WHEEL_SIZE] for offset in range(-2, 3)}
    observed = sum(1 for n in history[-50:] if n in neighborhood)
    factor_scores["neighborhood"] = observed / 50

    gaps = data["gaps"]
    avg_gap = sum(gaps.values()) / 37
    factor_scores["gap"] = min(gaps.get(result_number, 0) / avg_gap, 2) if avg_gap > 0 else 1

    trends = data["trends"]
    factor_scores["trend"] = max(trends.get(result_number, 0), 0)

    learning_rate = 0.05
    for factor, score in factor_scores.items():
        if factor in model_weights:
            if hit:
                model_weights[factor] = min(model_weights[factor] * (1 + learning_rate * score), 2.0)
            else:
                model_weights[factor] = max(model_weights[factor] * (1 - learning_rate * score), 0.01)

    save_user(chat_id, model_weights=model_weights)
    return model_weights

# ================== إنشاء التوقع ==================

def create_prediction(chat_id, history, horizon):
    user = get_user(chat_id)
    try:
        model_weights = json.loads(user.get("model_weights") or "{}")
    except:
        model_weights = {}
    numbers = choose_numbers(history, model_weights)

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

        if prediction_id:
            update_model_weights(chat_id, history, prediction, number, hit)

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
        "🧠 بوت تحليل الروليت الأوروبية - النسخة الذكية\n\n"
        "أرسل سجلًا من 100 رقم أو أكثر في رسالة واحدة.\n"
        "بعدها أرسل كل نتيجة جديدة كرقم منفرد.\n\n"
        "الأوامر:\n"
        "/start - بدء جلسة جديدة\n"
        "/status - عرض حالة الجلسة\n"
        "/stats - عرض إحصاءات التوقعات\n"
        "/horizon5 - اختبار لمدة 5 لفات\n"
        "/horizon10 - اختبار لمدة 10 لفات\n"
        "/help - المساعدة\n\n"
        "⚙️ الخوارزمية الذكية تشمل 13 عامل تحليل:\n"
        "1. التحليل التكراري المرجح (4 نوافذ زمنية)\n"
        "2. تحليل التابع (Follower)\n"
        "3. تحليل الخطوات على العجلة\n"
        "4. تحليل الجوار على العجلة\n"
        "5. تحليل الفجوات (Gap)\n"
        "6. تحليل الاتجاهات (Trend)\n"
        "7. تحليل التوازن (Balance)\n"
        "8. تحليل الأنماط المتكررة\n"
        "9. تحليل سلسلة ماركوف (درجتان)\n"
        "10. تحليل الانحياز (Bias Detection)\n"
        "11. تحليل الإنتروبيا (Entropy)\n"
        "12. تحليل الأثلاث والأعمدة\n"
        "13. تحليل الأزواج المتكررة\n\n"
        "🧠 تعلم آلي: يتعلم البوت من النتائج ويحسن أوزانه تلقائيًا\n\n"
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
