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
log = logging.getLogger("roulette_ai")
HTTP = requests.Session()

WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
    5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
WHEEL_SIZE = 37

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = set(range(37)) - RED_NUMBERS - {0}

SECTORS = {
    "voisins": {22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25},
    "tiers": {27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33},
    "orphelins": {1, 20, 14, 31, 9, 17, 34, 6},
    "zero_game": {12, 35, 3, 26, 0, 32, 15}
}

def connect_db():
    con = sqlite3.connect(DB_FILE, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect_db() as con:
        con.execute("PRAGMA journal_mode=WAL;")
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
            ON CONFLICT(chat_id) DO UPDATE SET
                history='[]', prediction='[]', horizon=excluded.horizon, spins_seen=0, prediction_id=0, model_weights='{}'
        """, (str(chat_id), DEFAULT_HORIZON))
        con.execute("UPDATE predictions SET status='cancelled' WHERE chat_id=? AND status='active'", (str(chat_id),))

def send_message(chat_id, text):
    if not TOKEN:
        log.error("BOT_TOKEN is missing")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = HTTP.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "parse_mode": "HTML"}, timeout=15)
        if not response.ok:
            log.error("Telegram Error: %s", response.text)
            HTTP.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
            return False
        return True
    except Exception:
        log.exception("Failed to send Telegram message")
        return False

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

def wheel_angular_distance(a, b):
    ia = WHEEL_INDEX[a]
    ib = WHEEL_INDEX[b]
    diff = abs(ia - ib) % WHEEL_SIZE
    return min(diff, WHEEL_SIZE - diff)

def wheel_step(a, b):
    ia = WHEEL_INDEX[a]
    ib = WHEEL_INDEX[b]
    diff = (ib - ia) % WHEEL_SIZE
    if diff > WHEEL_SIZE / 2:
        diff -= WHEEL_SIZE
    return int(diff)

def z_normalize(scores_dict):
    values = list(scores_dict.values())
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = math.sqrt(variance) if variance > 1e-9 else 1.0
    return {k: (v - mean) / std for k, v in scores_dict.items()}

def hyper_ai_prediction_engine(history, model_weights=None):
    if not history:
        return WHEEL[:PICK_COUNT]
    default_weights = {
        "circular_kde": 1.40,
        "dealer_signature": 1.30,
        "fibonacci_momentum": 1.25,
        "markov_clusters": 1.15,
        "sector_resonance": 1.10,
        "entropy_gating": 0.95,
        "gap_acceleration": 0.85
    }
    weights = default_weights if not model_weights else {**default_weights, **model_weights}
    n_total = len(history)
    last_num = history[-1]
    kde_scores = {i: 0.0 for i in range(37)}
    recent_spins = history[-40:]
    sigma = 2.2
    for spin_idx, spin in enumerate(recent_spins):
        weight = math.exp((spin_idx - len(recent_spins)) / 15.0)
        for cand in range(37):
            d = wheel_angular_distance(spin, cand)
            kernel_val = math.exp(-(d ** 2) / (2 * (sigma ** 2)))
            kde_scores[cand] += weight * kernel_val
    norm_kde = z_normalize(kde_scores)
    dealer_scores = {i: 0.0 for i in range(37)}
    if n_total >= 12:
        steps = [wheel_step(history[i - 1], history[i]) for i in range(max(1, n_total - 30), n_total)]
        step_counts = Counter(steps)
        total_steps = len(steps)
        for cand in range(37):
            step = wheel_step(last_num, cand)
            prob_step = (step_counts.get(step, 0) + 0.6) / (total_steps + 18.5)
            dealer_scores[cand] = prob_step - (1.0 / 37.0)
    norm_dealer = z_normalize(dealer_scores)
    fib_scores = {i: 0.0 for i in range(37)}
    fib_windows = [(8, 2.5), (13, 2.0), (21, 1.6), (34, 1.2), (55, 0.9), (89, 0.6)]
    for w_size, w_importance in fib_windows:
        w_history = history[-w_size:] if n_total >= w_size else history
        counts = Counter(w_history)
        w_len = len(w_history)
        for cand in range(37):
            prob = (counts.get(cand, 0) + 1.0) / (w_len + 37.0)
            fib_scores[cand] += w_importance * (prob - (1.0 / 37.0))
    norm_fib = z_normalize(fib_scores)
    markov_scores = {i: 0.0 for i in range(37)}
    t1_counts = Counter()
    for i in range(n_total - 1):
        if history[i] == last_num:
            t1_counts[history[i + 1]] += 1
    t1_total = sum(t1_counts.values())
    if t1_total > 0:
        for cand in range(37):
            p = (t1_counts.get(cand, 0) + 0.5) / (t1_total + 18.5)
            markov_scores[cand] += (p - 1.0 / 37.0)
    if n_total >= 3:
        last_pair = (history[-2], history[-1])
        t2_counts = Counter()
        for i in range(n_total - 2):
            if (history[i], history[i + 1]) == last_pair:
                t2_counts[history[i + 2]] += 1
        t2_total = sum(t2_counts.values())
        if t2_total > 0:
            for cand in range(37):
                p2 = (t2_counts.get(cand, 0) + 0.5) / (t2_total + 18.5)
                markov_scores[cand] += 0.7 * (p2 - 1.0 / 37.0)
    norm_markov = z_normalize(markov_scores)
    sector_scores = {i: 0.0 for i in range(37)}
    recent_30 = history[-30:]
    for s_name, s_nums in SECTORS.items():
        actual = sum(1 for n in recent_30 if n in s_nums)
        expected = len(recent_30) * (len(s_nums) / 37.0)
        heat = (actual - expected) / math.sqrt(expected) if expected > 0 else 0
        for num in s_nums:
            sector_scores[num] += heat
    norm_sector = z_normalize(sector_scores)
    recent_50 = history[-50:]
    c50 = Counter(recent_50)
    entropy = -sum((cnt / 50.0) * math.log2(cnt / 50.0) for cnt in c50.values() if cnt > 0)
    max_entropy = math.log2(37.0)
    entropy_ratio = entropy / max_entropy if max_entropy > 0 else 1.0
    entropy_boost = {i: 0.0 for i in range(37)}
    if entropy_ratio < 0.92:
        for cand in range(37):
            entropy_boost[cand] = c50.get(cand, 0) / 50.0
    norm_entropy = z_normalize(entropy_boost)
    gap_scores = {}
    gaps = {}
    for num in range(37):
        try:
            last_pos = len(history) - 1 - history[::-1].index(num)
            gaps[num] = len(history) - 1 - last_pos
        except ValueError:
            gaps[num] = len(history)
    avg_gap = sum(gaps.values()) / 37.0
    for num in range(37):
        g = gaps[num]
        gap_scores[num] = math.log1p(max(0, g - avg_gap))
    norm_gap = z_normalize(gap_scores)
    final_scores = {}
    for num in range(37):
        final_scores[num] = (
            weights["circular_kde"] * norm_kde[num] +
            weights["dealer_signature"] * norm_dealer[num] +
            weights["fibonacci_momentum"] * norm_fib[num] +
            weights["markov_clusters"] * norm_markov[num] +
            weights["sector_resonance"] * norm_sector[num] +
            weights["entropy_gating"] * norm_entropy[num] +
            weights["gap_acceleration"] * norm_gap[num]
        )
    ranked = sorted(range(37), key=lambda x: final_scores[x], reverse=True)
    return ranked[:PICK_COUNT]

def update_adaptive_weights(chat_id, history, prediction, result_number, hit):
    try:
        user = get_user(chat_id)
        try:
            model_weights = json.loads(user.get("model_weights") or "{}")
        except Exception:
            model_weights = {}
        default_weights = {
            "circular_kde": 1.40,
            "dealer_signature": 1.30,
            "fibonacci_momentum": 1.25,
            "markov_clusters": 1.15,
            "sector_resonance": 1.10,
            "entropy_gating": 0.95,
            "gap_acceleration": 0.85
        }
        current_weights = {**default_weights, **model_weights}
        lr = 0.08
        multiplier = (1.0 + lr) if hit else (1.0 - (lr * 0.5))
        for key in current_weights:
            current_weights[key] = max(0.1, min(current_weights[key] * multiplier, 3.5))
        save_user(chat_id, model_weights=current_weights)
        return current_weights
    except Exception:
        log.exception("Update weights failed")
        return {}

def create_prediction(chat_id, history, horizon):
    user = get_user(chat_id)
    try:
        model_weights = json.loads(user.get("model_weights") or "{}")
    except Exception:
        model_weights = {}
    numbers = hyper_ai_prediction_engine(history, model_weights)
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
        update_adaptive_weights(chat_id, history, prediction, number, hit)
    return {"event": event, "history": history, "prediction": prediction, "spins_seen": spins_seen, "horizon": horizon}

def get_stats(chat_id):
    with connect_db() as con:
        rows = con.execute("SELECT status, COUNT(*) AS total FROM predictions WHERE chat_id=? GROUP BY status", (str(chat_id),)).fetchall()
    result = {row["status"]: row["total"] for row in rows}
    completed = result.get("hit", 0) + result.get("miss", 0)
    rate = result.get("hit", 0) / completed if completed else None
    return result, rate, completed

def help_message():
    return (
        "🧠 <b>بوت تحليل الروليت الأوروبية الذكي V3.0</b>\n\n"
        "<b>طريقة الاستخدام:</b>\n"
        "1. أرسل سجلاً من 100 رقم أو أكثر دفعة واحدة.\n"
        "2. سيرشح البوت أقوى 5 أرقام.\n"
        "3. أرسل كل نتيجة دورة جديدة كرقم منفرد.\n\n"
        "⚙️ <b>الأوامر:</b>\n"
        "/start - بدء جلسة جديدة وتصفير السجل\n"
        "/status - عرض الأرقام المرشحة والوضعية الحالية\n"
        "/stats - إحصاءات الجولات ومعدل الإصابة\n"
        "/horizon5 - اختبار لـ 5 دورات\n"
        "/horizon10 - اختبار لـ 10 دورات\n"
        "/help - المساعدة"
    )

def process_message(message, update_id):
    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    if not text:
        return
    if text in ("/start", "/help"):
        if text == "/start":
            reset_user(chat_id)
        send_message(chat_id, help_message())
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if text in ("/horizon5", "/horizon10"):
        if len(history) < MIN_HISTORY:
            send_message(chat_id, "⚠️ أرسل سجلاً من 100 رقم على الأقل أولاً.")
            return
        horizon = 5 if text == "/horizon5" else 10
        numbers = create_prediction(chat_id, history, horizon)
        formatted_nums = ", ".join(map(str, numbers))
        send_message(chat_id, f"🎯 تم ضبط فترة الاختبار على {horizon} دورات\nالأرقام الخمسة المرشحة: <b>[{formatted_nums}]</b>")
        return
    if text == "/status":
        prediction = json.loads(user["prediction"])
        pred_str = ", ".join(map(str, prediction)) if prediction else "لا يوجد"
        send_message(
            chat_id,
            f"📊 <b>حالة الجلسة:</b>\n"
            f"• الأرقام المسجلة: <b>{len(history)}</b>\n"
            f"• آخر رقم: <b>{history[-1] if history else 'لا يوجد'}</b>\n"
            f"• الأرقام المرشحة: <b>[{pred_str}]</b>\n"
            f"• فترة الاختبار: <b>{user['horizon']}</b> دورات\n"
            f"• الدورة الحالية: <b>{user['spins_seen']}</b>"
        )
        return
    if text == "/stats":
        stats, rate, completed = get_stats(chat_id)
        rate_text = f"{rate * 100:.1f}%" if rate is not None else "لا توجد بيانات كافية"
        send_message(
            chat_id,
            f"📈 <b>إحصاءات الأداء:</b>\n"
            f"• إجمالي الجولات: <b>{completed}</b>\n"
            f"• الجولات المصيبة: <b>{stats.get('hit', 0)}</b>\n"
            f"• الجولات الفائتة: <b>{stats.get('miss', 0)}</b>\n"
            f"• معدل النجاح: <b>{rate_text}</b>"
        )
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as error:
        send_message(chat_id, f"⚠️ {error}\nأرسل أرقاماً صحيحة بين 0 و 36.")
        return
    if not numbers:
        return
    if len(numbers) >= MIN_HISTORY:
        pred = create_prediction(chat_id, numbers, DEFAULT_HORIZON)
        save_user(chat_id, history=numbers, prediction=pred, horizon=DEFAULT_HORIZON, spins_seen=0)
        pred_str = ", ".join(map(str, pred))
        send_message(
            chat_id,
            f"✅ <b>تم تحليل السجل بنجاح بواسطة محرك الذكاء V3.0</b>\n"
            f"• عدد الأرقام في السجل: <b>{len(numbers)}</b>\n"
            f"• آخر رقم مسجل: <b>{numbers[-1]}</b>\n"
            f"• 🎯 <b>أقوى 5 أرقام مرشحة:</b> <b>[{pred_str}]</b>\n"
            f"• فترة الاختبار: <b>{DEFAULT_HORIZON}</b> دورات\n\n"
            f"أرسل الآن كل دورة جديدة كرقم منفرد."
        )
        return
    if len(numbers)!= 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} أرقام.\nللبدء أرسل 100 رقم على الأقل دفعة واحدة، ثم أرسل كل نتيجة جديدة وحدها.")
        return
    number = numbers[0]
    result = record_result(chat_id, update_id, number)
    if result is None:
        send_message(chat_id, "⚠️ تعذر تسجيل النتيجة أو أن السجل الأولي غير مكتمل.")
        return
    event = result["event"]
    prediction = result["prediction"]
    spins_seen = result["spins_seen"]
    horizon = result["horizon"]
    history = result["history"]
    curr_pred_str = ", ".join(map(str, prediction))
    if event == "hit":
        new_pred = create_prediction(chat_id, history, horizon)
        new_pred_str = ", ".join(map(str, new_pred))
        send_message(
            chat_id,
            f"🟢 <b>إصابة مباشرة!</b> ظهر الرقم <b>{number}</b> ضمن التوقعات <b>[{curr_pred_str}]</b> في الدورة <b>{spins_seen}</b>.\n\n"
            f"🎯 <b>الأرقام الـ 5 المرشحة للجولة الجديدة:</b> <b>[{new_pred_str}]</b>"
        )
    elif event == "expired":
        new_pred = create_prediction(chat_id, history, horizon)
        new_pred_str = ", ".join(map(str, new_pred))
        send_message(
            chat_id,
            f"🔴 انتهت <b>{horizon}</b> دورات دون إصابة (آخر رقم: <b>{number}</b>).\nتم تحديث الأوزان وإعادة التحليل.\n\n"
            f"🎯 <b>الأرقام الـ 5 المرشحة الجديدة:</b> <b>[{new_pred_str}]</b>"
        )
    else:
        send_message(
            chat_id,
            f"📍 تم تسجيل الرقم: <b>{number}</b> | الدورة: <b>{spins_seen}/{horizon}</b>\n"
            f"الأرقام المستهدفة الحالية: <b>[{curr_pred_str}]</b>"
        )

@app.get("/")
def home():
    return "Roulette AI V3.0 is running.", 200

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
        log.warning("BOT_TOKEN is not set.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
