import os
import re
import json
import time
import hmac
import sqlite3
import logging
from collections import Counter, defaultdict

import requests
from flask import Flask, request, abort

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_v24_audited")
HTTP = requests.Session()

WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
    11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
    22, 18, 29, 7, 28, 12, 35, 3, 26
]
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
WHEEL_SIZE = 37

def wheel_dist(a, b):
    d = abs(WHEEL_INDEX[a] - WHEEL_INDEX[b]) % WHEEL_SIZE
    return min(d, WHEEL_SIZE - d)

def wheel_step(a, b):
    d = (WHEEL_INDEX[b] - WHEEL_INDEX[a]) % WHEEL_SIZE
    if d > WHEEL_SIZE / 2:
        d -= WHEEL_SIZE
    return int(d)

def neighbors(c, r=2):
    idx = WHEEL_INDEX[c]
    return [
        WHEEL[(idx + offset) % WHEEL_SIZE]
        for offset in range(-r, r + 1)
    ]

def decay_weights(n, halflife=40.0):
    return [
        0.5 ** ((n - 1 - i) / halflife)
        for i in range(n)
    ]

def score_frequency(history, lookback=150, halflife=35.0):
    recent = history[-lookback:]
    weights = decay_weights(len(recent), halflife)
    scores = [0.0] * 37

    for number, weight in zip(recent, weights):
        scores[number] += weight

    total = sum(scores) or 1.0
    return [score / total for score in scores]

def score_neighbor_affinity(history, lookback=120):
    recent = history[-lookback:]

    if len(recent) < 10:
        return [0.0] * 37, [0.0] * 37

    near1 = [0.0] * 37
    near2 = [0.0] * 37
    weights = decay_weights(len(recent), 30.0)

    for i, number in enumerate(recent):
        for candidate in range(37):
            distance = wheel_dist(candidate, number)

            if distance == 0:
                continue

            if distance <= 1:
                near1[candidate] += weights[i]

            if distance <= 2:
                near2[candidate] += weights[i]

    total1 = sum(near1) or 1.0
    total2 = sum(near2) or 1.0

    return (
        [x / total1 for x in near1],
        [x / total2 for x in near2]
    )

def score_step_distribution(history, lookback=120):
    if len(history) < 20:
        return [1.0 / 37] * 37

    segment = history[-lookback:]
    steps = [
        wheel_step(segment[i - 1], segment[i])
        for i in range(1, len(segment))
    ]

    step_counts = Counter(steps)
    total = sum(step_counts.values()) or 1
    last = history[-1]
    scores = [0.0] * 37

    for candidate in range(37):
        step = wheel_step(last, candidate)
        scores[candidate] = (
            step_counts.get(step, 0) + 0.3
        ) / (total + 0.3 * 37)

    total_score = sum(scores) or 1.0
    return [score / total_score for score in scores]

def score_direction(history, lookback=40):
    if len(history) < 5:
        return 0.5, 0.5

    segment = history[-lookback:]
    steps = [
        wheel_step(segment[i - 1], segment[i])
        for i in range(1, len(segment))
    ]
    steps = [step for step in steps if step!= 0]

    if not steps:
        return 0.5, 0.5

    clockwise = sum(1 for step in steps if step > 0)
    counterclockwise = len(steps) - clockwise

    return (
        clockwise / len(steps),
        counterclockwise / len(steps)
    )

def score_markov_position(history, lookback=200):
    if len(history) < 30:
        return [1.0 / 37] * 37

    segment = history[-lookback:]
    transitions = defaultdict(Counter)

    for i in range(1, len(segment)):
        previous = WHEEL_INDEX[segment[i - 1]]
        current = WHEEL_INDEX[segment[i]]
        transitions[previous][current] += 1

    last_position = WHEEL_INDEX[history[-1]]
    row = transitions.get(last_position, Counter())
    total = sum(row.values())

    scores = [
        (row.get(position, 0) + 0.5) / (total + 0.5 * 37)
        for position in range(37)
    ]

    total_score = sum(scores) or 1.0
    return [score / total_score for score in scores]

def score_hot_sectors(history, lookback=60, sector_size=5):
    recent = history[-lookback:]

    if not recent:
        return [1.0 / 37] * 37

    weights = decay_weights(len(recent), 25.0)
    activity = [0.0] * 37

    for number, weight in zip(recent, weights):
        for candidate in neighbors(number, sector_size // 2):
            activity[candidate] += weight

    total = sum(activity) or 1.0
    return [value / total for value in activity]

def combine_scores(history):
    if not history:
        return [1.0 / 37] * 37

    frequency = score_frequency(history)
    near1, near2 = score_neighbor_affinity(history)
    steps = score_step_distribution(history)
    p_cw, p_ccw = score_direction(history)
    markov = score_markov_position(history)
    hot = score_hot_sectors(history)

    weights = {
        "freq": 0.15,
        "near1": 0.15,
        "near2": 0.10,
        "step": 0.20,
        "markov": 0.20,
        "hot": 0.15,
        "dir": 0.05
    }

    scores = [0.0] * 37
    last = history[-1]

    for i in range(37):
        scores[i] = (
            weights["freq"] * frequency[i]
            + weights["near1"] * near1[i]
            + weights["near2"] * near2[i]
            + weights["step"] * steps[i]
            + weights["markov"] * markov[i]
            + weights["hot"] * hot[i]
        )

        distance = wheel_step(last, WHEEL[i])

        if distance > 0:
            scores[i] += (
                weights["dir"] * p_cw
                / (1 + abs(distance))
            )
        elif distance < 0:
            scores[i] += (
                weights["dir"] * p_ccw
                / (1 + abs(distance))
            )

    total = sum(scores) or 1.0
    return [score / total for score in scores]

def backtest_accuracy(history, top_n=20, test_len=100):
    if len(history) < test_len + MIN_HISTORY:
        return None

    hits = 0
    start = len(history) - test_len

    for t in range(start, len(history)):
        training = history[:t]
        scores = combine_scores(training)

        top = set(
            sorted(
                range(37),
                key=lambda number: scores[number],
                reverse=True
            )[:top_n]
        )

        hits += int(history[t] in top)

    return hits / test_len

def select_top20(history, scores):
    ranked = sorted(
        range(37),
        key=lambda number: scores[number],
        reverse=True
    )

    chosen = []
    used = set()

    for candidate in ranked:
        if len(chosen) >= 20:
            break

        if candidate in used:
            continue

        too_close = sum(
            1 for number in chosen
            if wheel_dist(number, candidate) <= 1
        )

        if too_close >= 3:
            continue

        chosen.append(candidate)
        used.add(candidate)

    if len(chosen) < 20:
        for candidate in ranked:
            if candidate not in used:
                chosen.append(candidate)
                used.add(candidate)

            if len(chosen) >= 20:
                break

    return chosen

def calculate_v24(history):
    if any(
        type(number) is not int or not 0 <= number <= 36
        for number in history
    ):
        raise ValueError("يجب أن تكون الأرقام أعدادًا صحيحة بين 0 و36")

    if not history:
        return (
            WHEEL[:5],
            WHEEL[5:10],
            WHEEL[10:15],
            WHEEL[15:20],
            WHEEL[:20]
        )

    scores = combine_scores(history)
    top20 = select_top20(history, scores)

    sectors = []
    used = set()

    for center in top20:
        if len(sectors) >= 4:
            break

        if center in used:
            continue

        cluster = [
            number for number in neighbors(center, 2)
            if number in top20 and number not in used
        ]

        if len(cluster) < 5:
            for number in top20:
                if number not in used and number not in cluster:
                    cluster.append(number)

                if len(cluster) >= 5:
                    break

        cluster = cluster[:5]

        if len(cluster) == 5:
            sectors.append(cluster)
            used.update(cluster)

    while len(sectors) < 4:
        remaining = [
            number for number in top20
            if number not in used
        ]

        if not remaining:
            break

        cluster = [remaining[0]]
        used.add(remaining[0])

        for number in top20:
            if number not in used and len(cluster) < 5:
                cluster.append(number)
                used.add(number)

        sectors.append(cluster)

    while len(sectors) < 4:
        remaining = [
            number for number in top20
            if number not in used
        ]

        if not remaining:
            break

        cluster = remaining[:5]
        sectors.append(cluster)
        used.update(cluster)

    s1, s2, s3, s4 = sectors[:4]

    final = []
    seen = set()

    for number in s1 + s2 + s3 + s4:
        if number not in seen:
            final.append(number)
            seen.add(number)

    for number in top20:
        if len(final) >= 20:
            break

        if number not in seen:
            final.append(number)
            seen.add(number)

    return s1, s2, s3, s4, final[:20]

def connect_db():
    con = sqlite3.connect(DB_FILE, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect_db() as con:
        con.execute("PRAGMA journal_mode=WAL")

        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY,
            history TEXT NOT NULL DEFAULT '[]',
            sec1 TEXT NOT NULL DEFAULT '[]',
            sec2 TEXT NOT NULL DEFAULT '[]',
            sec3 TEXT NOT NULL DEFAULT '[]',
            sec4 TEXT NOT NULL DEFAULT '[]',
            prediction TEXT NOT NULL DEFAULT '[]',
            hits INTEGER NOT NULL DEFAULT 0,
            misses INTEGER NOT NULL DEFAULT 0,
            total_bet INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS updates_seen (
            update_id TEXT PRIMARY KEY
        );
        """)

        existing = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        if "sec4" not in existing:
            con.execute(
                "ALTER TABLE users ADD COLUMN sec4 TEXT NOT NULL DEFAULT '[]'"
            )

        if "total_bet" not in existing:
            con.execute(
                "ALTER TABLE users ADD COLUMN total_bet INTEGER NOT NULL DEFAULT 0"
            )

init_db()

def get_user(chat_id):
    with connect_db() as con:
        row = con.execute(
            "SELECT * FROM users WHERE chat_id=?",
            (str(chat_id),)
        ).fetchone()

        if row is None:
            con.execute(
                "INSERT INTO users(chat_id) VALUES(?)",
                (str(chat_id),)
            )

            row = con.execute(
                "SELECT * FROM users WHERE chat_id=?",
                (str(chat_id),)
            ).fetchone()

        return dict(row)

def save_user(chat_id, **values):
    allowed = {
        "history", "sec1", "sec2", "sec3", "sec4",
        "prediction", "hits", "misses", "total_bet"
    }

    fields = []
    params = []

    for key, value in values.items():
        if key not in allowed:
            continue

        if key in {
            "history", "sec1", "sec2", "sec3",
            "sec4", "prediction"
        }:
            value = json.dumps(value)

        fields.append(f"{key}=?")
        params.append(value)

    if not fields:
        return

    params.append(str(chat_id))

    with connect_db() as con:
        con.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?",
            params
        )

def reset_user(chat_id):
    with connect_db() as con:
        con.execute("""
        INSERT INTO users (
            chat_id, history, sec1, sec2, sec3, sec4,
            prediction, hits, misses, total_bet
        )
        VALUES (?, '[]', '[]', '[]', '[]', '[]', '[]', 0, 0, 0)
        ON CONFLICT(chat_id) DO UPDATE SET
            history='[]',
            sec1='[]',
            sec2='[]',
            sec3='[]',
            sec4='[]',
            prediction='[]',
            hits=0,
            misses=0,
            total_bet=0
        """, (str(chat_id),))

def send_message(chat_id, text):
    if not TOKEN:
        log.error("BOT_TOKEN غير مضبوط")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        response = HTTP.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
                "parse_mode": "HTML"
            },
            timeout=15
        )

        if not response.ok:
            log.error("Telegram API error: %s", response.text)
            HTTP.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=15
            )
            return False

        return True

    except requests.RequestException:
        log.exception("تعذر إرسال الرسالة")
        return False

def parse_numbers(text):
    tokens = [
        token for token in re.split(r"[\s,;،\n]+", text.strip())
        if token
    ]

    numbers = []

    for token in tokens:
        if not re.fullmatch(r"\d+", token):
            raise ValueError(f"صيغة رقم غير صحيحة: {token}")

        number = int(token)

        if not 0 <= number <= 36:
            raise ValueError(f"الرقم {number} خارج النطاق 0-36")

        numbers.append(number)

    return numbers

def record_spin(chat_id, update_id, number):
    with connect_db() as con:
        try:
            con.execute(
                "INSERT INTO updates_seen(update_id) VALUES(?)",
                (str(update_id),)
            )
        except sqlite3.IntegrityError:
            return None

        row = con.execute(
            "SELECT * FROM users WHERE chat_id=?",
            (str(chat_id),)
        ).fetchone()

        if row is None:
            return None

        user = dict(row)
        history = json.loads(user["history"])
        prediction = json.loads(user["prediction"])

        if len(history) < MIN_HISTORY:
            return None

        hit = number in prediction if prediction else False

        hits = user["hits"] + int(hit)
        misses = user["misses"] + int(not hit)

        history.append(number)

        s1, s2, s3, s4, new_prediction = calculate_v24(history)

        con.execute("""
        UPDATE users SET
            history=?,
            sec1=?,
            sec2=?,
            sec3=?,
            sec4=?,
            prediction=?,
            hits=?,
            misses=?
        WHERE chat_id=?
        """, (
            json.dumps(history),
            json.dumps(s1),
            json.dumps(s2),
            json.dumps(s3),
            json.dumps(s4),
            json.dumps(new_prediction),
            hits,
            misses,
            str(chat_id)
        ))

        return {
            "hit": hit,
            "number": number,
            "new_s1": s1,
            "new_s2": s2,
            "new_s3": s3,
            "new_s4": s4,
            "new_pred": new_prediction,
            "hits": hits,
            "misses": misses
        }

def help_message():
    return (
        "🎯 <b>بوت الروليت V24</b>\n\n"
        "🧠 محرك ترتيب إحصائي تجريبي:\n"
        "• تكرار الأرقام مع ترجيح النتائج الحديثة\n"
        "• تحليل الجوار على عجلة الروليت\n"
        "• تحليل انتقالات الأرقام\n"
        "• تحليل اتجاه الحركة التاريخية\n"
        "• نموذج انتقالات ماركوف\n"
        "• تحليل القطاعات\n\n"
        "1. أرسل 100 رقم على الأقل لتفعيل النموذج.\n"
        "2. يمكنك إرسال الأرقام على دفعات.\n"
        "3. بعد التفعيل أرسل كل نتيجة جديدة منفردة.\n\n"
        "/start - إعادة ضبط السجل\n"
        "/status - الأهداف الحالية\n"
        "/stats - إحصاءات الأداء\n"
        "/backtest - الاختبار التاريخي\n"
        "/help - المساعدة\n\n"
        "⚠️ لا توجد خوارزمية تضمن نتيجة الروليت التالية."
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

    if text == "/status":
        sectors = [
            json.loads(user.get(f"sec{i}", "[]"))
            for i in range(1, 5)
        ]

        last = history[-1] if history else "لا يوجد"

        send_message(
            chat_id,
            f"📊 <b>الأهداف الحالية</b>\n"
            f"آخر رقم: <b>{last}</b>\n\n"
            f"🔵 القطاع 1: <code>{sectors[0]}</code>\n"
            f"🟢 القطاع 2: <code>{sectors[1]}</code>\n"
            f"🟡 القطاع 3: <code>{sectors[2]}</code>\n"
            f"🟣 القطاع 4: <code>{sectors[3]}</code>"
        )
        return

    if text == "/stats":
        hits = user["hits"]
        misses = user["misses"]
        total = hits + misses
        rate = hits / total * 100 if total else 0
        baseline = 20 / 37 * 100
        expected = total * 20 / 37

        send_message(
            chat_id,
            "📈 <b>تقرير الأداء V24</b>\n\n"
            f"إجمالي اللفات: <b>{total}</b>\n"
            f"الإصابات: <b>{hits}</b>\n"
            f"الإخفاقات: <b>{misses}</b>\n"
            f"التغطية الفعلية: <b>{rate:.1f}%</b>\n"
            f"خط الأساس العشوائي: <b>{baseline:.1f}%</b>\n"
            f"الإصابات المتوقعة عشوائيًا: <b>{expected:.1f}</b>\n"
            f"الفرق: <b>{rate - baseline:+.1f}</b> نقطة مئوية\n\n"
            "⚠️ الأداء السابق لا يضمن النتائج المستقبلية."
        )
        return

    if text == "/backtest":
        if len(history) < MIN_HISTORY + 30:
            send_message(
                chat_id,
                f"تحتاج إلى {MIN_HISTORY + 30} رقمًا على الأقل "
                "لإجراء اختبار خلفي أولي."
            )
            return

        test_len = min(100, len(history) - MIN_HISTORY)
        accuracy = backtest_accuracy(
            history,
            top_n=20,
            test_len=test_len
        )

        if accuracy is None:
            send_message(chat_id, "السجل غير كافٍ للاختبار.")
            return

        baseline = 20 / 37

        send_message(
            chat_id,
            f"🧪 <b>الاختبار التاريخي</b>\n"
            f"عدد اللفات المختبرة: <b>{test_len}</b>\n"
            f"تغطية النموذج: <b>{accuracy * 100:.1f}%</b>\n"
            f"خط الأساس العشوائي: <b>{baseline * 100:.1f}%</b>\n"
            f"الفرق: <b>{(accuracy - baseline) * 100:+.1f}</b> "
            "نقطة مئوية\n\n"
            "هذا اختبار تاريخي وليس ضمانًا للمستقبل."
        )
        return

    try:
        numbers = parse_numbers(text)
    except ValueError as error:
        send_message(chat_id, f"⚠️ {error}")
        return

    if not numbers:
        return

    if len(numbers) >= MIN_HISTORY:
        s1, s2, s3, s4, prediction = calculate_v24(numbers)

        save_user(
            chat_id,
            history=numbers,
            sec1=s1,
            sec2=s2,
            sec3=s3,
            sec4=s4,
            prediction=prediction,
            hits=0,
            misses=0
        )

        send_message(
            chat_id,
            "✅ <b>تم تفعيل V24</b>\n"
            f"حجم السجل: <b>{len(numbers)}</b>\n"
            f"آخر رقم: <b>{numbers[-1]}</b>\n\n"
            f"🔵 القطاع 1: <code>{s1}</code>\n"
            f"🟢 القطاع 2: <code>{s2}</code>\n"
            f"🟡 القطاع 3: <code>{s3}</code>\n"
            f"🟣 القطاع 4: <code>{s4}</code>"
        )
        return

    if len(history) < MIN_HISTORY:
        combined = history + numbers

        if len(combined) < MIN_HISTORY:
            save_user(chat_id, history=combined)

            send_message(
                chat_id,
                f"📥 تم حفظ {len(numbers)} رقمًا.\n"
                f"المجموع: <b>{len(combined)}/{MIN_HISTORY}</b>\n"
                "أرسل بقية الأرقام على دفعات."
            )
            return

        s1, s2, s3, s4, prediction = calculate_v24(combined)

        save_user(
            chat_id,
            history=combined,
            sec1=s1,
            sec2=s2,
            sec3=s3,
            sec4=s4,
            prediction=prediction,
            hits=0,
            misses=0
        )

        send_message(
            chat_id,
            "✅ <b>اكتمل السجل وتفعّل النموذج</b>\n"
            f"عدد الأرقام: <b>{len(combined)}</b>\n"
            f"آخر رقم: <b>{combined[-1]}</b>\n\n"
            f"🔵 القطاع 1: <code>{s1}</code>\n"
            f"🟢 القطاع 2: <code>{s2}</code>\n"
            f"🟡 القطاع 3: <code>{s3}</code>\n"
            f"🟣 القطاع 4: <code>{s4}</code>"
        )
        return

    if len(numbers)!= 1:
        send_message(
            chat_id,
            "بعد تفعيل النموذج، أرسل كل نتيجة جديدة منفردة."
        )
        return

    result = record_spin(chat_id, update_id, numbers[0])

    if result is None:
        send_message(
            chat_id,
            "⚠️ تعذر تسجيل اللفة. تحقق من السجل أو أعد المحاولة."
        )
        return

    icon = "🟢 <b>إصابة 🎯</b>" if result["hit"] else "🔴 <b>إخفاق</b>"

    send_message(
        chat_id,
        f"{icon}: <b>{result['number']}</b>\n\n"
        f"الإصابات: <b>{result['hits']}</b>\n"
        f"الإخفاقات: <b>{result['misses']}</b>\n\n"
        "🎯 <b>الأهداف الجديدة</b>\n"
        f"🔵 <code>{result['new_s1']}</code>\n"
        f"🟢 <code>{result['new_s2']}</code>\n"
        f"🟡 <code>{result['new_s3']}</code>\n"
        f"🟣 <code>{result['new_s4']}</code>"
    )

@app.get("/")
def home():
    return "Roulette V24 Statistical Engine is running.", 200

@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token", ""
        )

        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            abort(403)

    update = request.get_json(silent=True)

    if not isinstance(update, dict):
        return "ok", 200

    message = update.get("message")

    if not isinstance(message, dict):
        return "ok", 200

    try:
        process_message(
            message,
            str(update.get("update_id", time.time_ns()))
        )
    except Exception:
        log.exception("حدث خطأ أثناء معالجة تحديث تيليجرام")

    return "ok", 200

if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000"))
    )
