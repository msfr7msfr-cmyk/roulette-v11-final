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

MIN_HISTORY = 100
MAX_SPINS_LOCK = 2

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_15_tri_sectors")
HTTP = requests.Session()

WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
    5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
WHEEL_SIZE = 37

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
            sec1 TEXT NOT NULL DEFAULT '[]',
            sec2 TEXT NOT NULL DEFAULT '[]',
            sec3 TEXT NOT NULL DEFAULT '[]',
            prediction TEXT NOT NULL DEFAULT '[]',
            spins_seen INTEGER NOT NULL DEFAULT 0,
            hits INTEGER NOT NULL DEFAULT 0,
            misses INTEGER NOT NULL DEFAULT 0
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
    allowed = {"history", "sec1", "sec2", "sec3", "prediction", "spins_seen", "hits", "misses"}
    fields = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in ("history", "sec1", "sec2", "sec3", "prediction"):
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
            INSERT INTO users(chat_id, history, sec1, sec2, sec3, prediction, spins_seen, hits, misses)
            VALUES(?, '[]', '[]', '[]', '[]', '[]', 0, 0, 0)
            ON CONFLICT(chat_id) DO UPDATE SET
                history='[]', sec1='[]', sec2='[]', sec3='[]', prediction='[]', spins_seen=0, hits=0, misses=0
        """, (str(chat_id),))

def send_message(chat_id, text):
    if not TOKEN:
        log.error("BOT_TOKEN is missing")
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
            log.error("Telegram API Error (%s): %s", response.status_code, response.text)
            HTTP.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
            return False
        return True
    except Exception:
        log.exception("Failed to send Telegram message")
        return False

def parse_numbers(text):
    tokens = [x for x in re.split(r"[\s,;،\n]+", text.strip()) if x]
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

def wheel_distance(a, b):
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

def get_wheel_neighbors(center_num, offset_range=2):
    idx = WHEEL_INDEX[center_num]
    return [WHEEL[(idx + offset) % WHEEL_SIZE] for offset in range(-offset_range, offset_range + 1)]

def z_normalize(scores_dict):
    values = list(scores_dict.values())
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std = math.sqrt(variance) if variance > 1e-9 else 1.0
    return {k: (v - mean) / std for k, v in scores_dict.items()}

def calculate_tri_sectors_15(history):
    if not history:
        return WHEEL[:5], WHEEL[5:10], WHEEL[10:15], WHEEL[:15]

    n_total = len(history)
    last_num = history[-1]

    recent_20 = history[-20:]

    heat_scores = {i: 0.0 for i in range(37)}
    sigma = 1.8
    for idx, num in enumerate(recent_20):
        w = math.exp((idx - len(recent_20)) / 7.0)
        for cand in range(37):
            d = wheel_distance(num, cand)
            heat_scores[cand] += w * math.exp(-(d ** 2) / (2 * (sigma ** 2)))
    norm_heat = z_normalize(heat_scores)

    step_scores = {i: 0.0 for i in range(37)}
    if n_total >= 10:
        steps = [wheel_step(history[i - 1], history[i]) for i in range(max(1, n_total - 25), n_total)]
        step_counts = Counter(steps)
        total_steps = len(steps)
        for cand in range(37):
            diff = wheel_step(last_num, cand)
            p = (step_counts.get(diff, 0) + 0.5) / (total_steps + 18.5)
            step_scores[cand] = p
    norm_step = z_normalize(step_scores)

    final_scores = {}
    for num in range(37):
        final_scores[num] = (1.5 * norm_heat[num]) + (1.3 * norm_step[num])

    ranked = sorted(range(37), key=lambda x: final_scores[x], reverse=True)

    anchor_1 = ranked[0]
    sec1 = get_wheel_neighbors(anchor_1, offset_range=2)

    sec2 = []
    for cand in ranked[1:]:
        cand_cluster = get_wheel_neighbors(cand, offset_range=2)
        overlap = len(set(cand_cluster).intersection(set(sec1)))
        if overlap <= 1:
            sec2 = cand_cluster
            break
    if not sec2:
        sec2 = get_wheel_neighbors(ranked[1], offset_range=2)

    sec3 = []
    used = set(sec1 + sec2)
    for cand in ranked[2:]:
        cand_cluster = get_wheel_neighbors(cand, offset_range=2)
        overlap = len(set(cand_cluster).intersection(used))
        if overlap <= 1:
            sec3 = cand_cluster
            break
    if not sec3:
        remaining = [n for n in ranked if n not in used]
        sec3 = remaining[:5]

    combined = list(dict.fromkeys(sec1 + sec2 + sec3))
    if len(combined) < 15:
        for n in ranked:
            if n not in combined:
                combined.append(n)
            if len(combined) == 15:
                break
    final_15 = combined[:15]

    part1 = final_15[0:5]
    part2 = final_15[5:10]
    part3 = final_15[10:15]

    return part1, part2, part3, final_15

def record_spin(chat_id, update_id, number):
    with connect_db() as con:
        try:
            con.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
        except sqlite3.IntegrityError:
            return None

        row = con.execute("SELECT * FROM users WHERE chat_id =?", (str(chat_id),)).fetchone()
        if row is None:
            return None
        user = dict(row)
        history = json.loads(user["history"])
        prediction = json.loads(user["prediction"])
        sec1 = json.loads(user["sec1"])
        sec2 = json.loads(user["sec2"])
        sec3 = json.loads(user["sec3"])
        spins_seen = user["spins_seen"]

        if len(history) < MIN_HISTORY:
            return None

        history.append(number)
        spins_seen += 1
        hit = number in prediction
        hits = user["hits"] + (1 if hit else 0)
        misses = user["misses"]

        if hit or spins_seen >= MAX_SPINS_LOCK:
            if not hit:
                misses += 1
            new_s1, new_s2, new_s3, new_pred = calculate_tri_sectors_15(history)
            new_spins_seen = 0
            event = "hit" if hit else "expired"
        else:
            new_s1, new_s2, new_s3, new_pred = sec1, sec2, sec3, prediction
            new_spins_seen = spins_seen
            event = "continue"

        con.execute(
            "UPDATE users SET history =?, sec1 =?, sec2 =?, sec3 =?, prediction =?, spins_seen =?, hits =?, misses =? WHERE chat_id =?",
            (json.dumps(history), json.dumps(new_s1), json.dumps(new_s2), json.dumps(new_s3), json.dumps(new_pred), new_spins_seen, hits, misses, str(chat_id))
        )

        return {
            "event": event,
            "number": number,
            "old_s1": sec1,
            "old_s2": sec2,
            "old_s3": sec3,
            "old_pred": prediction,
            "new_s1": new_s1,
            "new_s2": new_s2,
            "new_s3": new_s3,
            "new_pred": new_pred,
            "spins_seen": spins_seen,
            "hits": hits,
            "misses": misses,
            "total": hits + misses
        }

def help_message():
    return (
        "🎯 <b>بوت القناص الثلاثي (15 رقماً مقسمة / لفتين فقط) V14.0</b>\n\n"
        "<b>طريقة الاستخدام:</b>\n"
        "1. أرسل سجلاً من 100 رقم أو أكثر دفعة واحدة.\n"
        "2. يرصد البوت <b>3 مجموعات ملونة (كل مجموعة 5 أرقام)</b> لتسهيل الرهان السريع.\n"
        "3. يستمر الهجوم لـ <b>لفتين فقط</b> مع خروج فوري عند الإصابة 🎯.\n"
        "4. أرسل كل نتيجة دورة لمتابعة العداد.\n\n"
        "⚙️ <b>الأوامر:</b>\n"
        "/start - بدء جلسة جديدة وتصفير السجل\n"
        "/status - عرض المجموعات الثلاث والمحاولة الحالية\n"
        "/stats - إحصاءات الدقة ومعدل الإصابة\n"
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

    if text == "/status":
        sec1 = json.loads(user["sec1"])
        sec2 = json.loads(user["sec2"])
        sec3 = json.loads(user["sec3"])
        spins_seen = user["spins_seen"]
        send_message(
            chat_id,
            f"📊 <b>حالة الجلسة الحية:</b>\n"
            f"• الأرقام المسجلة: <b>{len(history)}</b>\n"
            f"• آخر رقم سقط: <b>{history[-1] if history else 'لا يوجد'}</b>\n\n"
            f"🔵 <b>المجموعة الأولى (5):</b> <code>{sec1}</code>\n"
            f"🟢 <b>المجموعة الثانية (5):</b> <code>{sec2}</code>\n"
            f"🟡 <b>المجموعة الثالثة (5):</b> <code>{sec3}</code>\n\n"
            f"⏳ <b>العداد:</b> <b>المحاولة ({spins_seen}/{MAX_SPINS_LOCK})</b>"
        )
        return

    if text == "/stats":
        hits = user["hits"]
        misses = user["misses"]
        total = hits + misses
        rate = (hits / total * 100) if total > 0 else 0
        send_message(
            chat_id,
            f"📈 <b>إحصاءات القناص V14.0:</b>\n"
            f"• إجمالي الجولات: <b>{total}</b>\n"
            f"• الإصابات الناجحة (15 رقماً): <b>{hits}</b>\n"
            f"• الجولات المنتهية: <b>{misses}</b>\n"
            f"• نسبة الدقة: <b>{rate:.1f}%</b>"
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
        s1, s2, s3, pred = calculate_tri_sectors_15(numbers)
        save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3, prediction=pred, spins_seen=0, hits=0, misses=0)
        send_message(
            chat_id,
            f"✅ <b>تم تفعيل نظام المجموعات الثلاث V14.0 (15 رقماً / لفتين فقط)</b>\n"
            f"• عدد الأرقام في السجل: <b>{len(numbers)}</b>\n"
            f"• آخر رقم مسجل: <b>{numbers[-1]}</b>\n\n"
            f"🔵 <b>المجموعة 1 (الأساسية):</b> <code>{s1}</code>\n"
            f"🟢 <b>المجموعة 2 (المقابلة):</b> <code>{s2}</code>\n"
            f"🟡 <b>المجموعة 3 (الصاعدة):</b> <code>{s3}</code>\n\n"
            f"⏳ <b>فترة الهجوم:</b> لفتين فقط (المحاولة 0/2)\n"
            f"أرسل نتيجة اللفة التالية الآن."
        )
        return

    if len(numbers)!= 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} أرقام.\nللبدء أرسل 100 رقم على الأقل دفعة واحدة، ثم أرسل كل دورة كرقم منفرد.")
        return

    number = numbers[0]
    res = record_spin(chat_id, update_id, number)
    if res is None:
        send_message(chat_id, "⚠️ تعذر تسجيل النتيجة أو أن السجل الأولي غير مكتمل.")
        return

    if res["event"] == "hit":
        send_message(
            chat_id,
            f"🟢 <b>إصابة قناص مباشرة! 🎯</b> (في المحاولة {res['spins_seen']}/{MAX_SPINS_LOCK})\n"
            f"سقط الرقم <b>{number}</b> داخل الـ 15 رقماً المستهدفة!\n\n"
            f"🎯 <b>الأهداف الـ 15 الجديدة للهجوم القادم:</b>\n"
            f"🔵 <b>المجموعة 1:</b> <code>{res['new_s1']}</code>\n"
            f"🟢 <b>المجموعة 2:</b> <code>{res['new_s2']}</code>\n"
            f"🟡 <b>المجموعة 3:</b> <code>{res['new_s3']}</code>\n\n"
            f"⏳ <b>العداد:</b> لفتين جديدتين (0/2)"
        )
    elif res["event"] == "expired":
        send_message(
            chat_id,
            f"🔴 انتهت اللفتان (آخر رقم: <b>{number}</b>).\n"
            f"تم تحديث القطاعات الثلاثة فوراً للهجوم الجديد:\n\n"
            f"🔵 <b>المجموعة 1:</b> <code>{res['new_s1']}</code>\n"
            f"🟢 <b>المجموعة 2:</b> <code>{res['new_s2']}</code>\n"
            f"🟡 <b>المجموعة 3:</b> <code>{res['new_s3']}</code>\n\n"
            f"⏳ <b>العداد:</b> لفتين جديدتين (0/2)"
        )
    else:
        send_message(
            chat_id,
            f"📍 تم تسجيل الرقم: <b>{number}</b> | ⏳ المحاولة (<b>{res['spins_seen']}/{MAX_SPINS_LOCK}</b>)\n\n"
            f"🎯 <b>مستمرون في اللفة الثانية الأخيرة:</b>\n"
            f"🔵 <b>المجموعة 1:</b> <code>{res['old_s1']}</code>\n"
            f"🟢 <b>المجموعة 2:</b> <code>{res['old_s2']}</code>\n"
            f"🟡 <b>المجموعة 3:</b> <code>{res['old_s3']}</code>"
        )

@app.get("/")
def home():
    return "Roulette Tri-Sectors 15 is running.", 200

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
