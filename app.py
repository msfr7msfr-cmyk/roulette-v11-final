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
PICK_COUNT = 1

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_single_sniper")
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
            prediction INTEGER NOT NULL DEFAULT -1,
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
    allowed = {"history", "prediction", "hits", "misses"}
    fields = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        if key == "history":
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
            INSERT INTO users(chat_id, history, prediction, hits, misses)
            VALUES(?, '[]', -1, 0, 0)
            ON CONFLICT(chat_id) DO UPDATE SET
                history='[]', prediction=-1, hits=0, misses=0
        """, (str(chat_id),))

def send_message(chat_id, text):
    if not TOKEN:
        log.error("BOT_TOKEN is missing")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        response = HTTP.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "parse_mode": "HTML"}, timeout=15)
        if not response.ok:
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

def calculate_single_sniper(history):
    if not history:
        return 0
    n_total = len(history)
    last_num = history[-1]
    heat_map = {i: 0.0 for i in range(37)}
    recent_spins = history[-35:]
    sigma = 1.6
    for idx, num in enumerate(recent_spins):
        w = math.exp((idx - len(recent_spins)) / 10.0)
        for cand in range(37):
            d = wheel_distance(num, cand)
            heat_map[cand] += w * math.exp(-(d ** 2) / (2 * (sigma ** 2)))
    step_scores = {i: 0.0 for i in range(37)}
    if n_total >= 10:
        steps = []
        for i in range(max(1, n_total - 25), n_total):
            ia = WHEEL_INDEX[history[i - 1]]
            ib = WHEEL_INDEX[history[i]]
            diff = (ib - ia) % WHEEL_SIZE
            if diff > WHEEL_SIZE / 2:
                diff -= WHEEL_SIZE
            steps.append(diff)
        step_counts = Counter(steps)
        total_steps = len(steps)
        for cand in range(37):
            ia = WHEEL_INDEX[last_num]
            ib = WHEEL_INDEX[cand]
            diff = (ib - ia) % WHEEL_SIZE
            if diff > WHEEL_SIZE / 2:
                diff -= WHEEL_SIZE
            step_scores[cand] = (step_counts.get(diff, 0) + 0.6) / (total_steps + 18.5)
    final_scores = {}
    for num in range(37):
        final_scores[num] = (1.8 * heat_map[num]) + (1.4 * step_scores[num])
    best_single_number = max(final_scores, key=final_scores.get)
    return best_single_number

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
        prediction = user["prediction"]
        if len(history) < MIN_HISTORY:
            return None
        history.append(number)
        hit = (number == prediction)
        hits = user["hits"] + (1 if hit else 0)
        misses = user["misses"] + (0 if hit else 1)
        new_pred = calculate_single_sniper(history)
        con.execute(
            "UPDATE users SET history =?, prediction =?, hits =?, misses =? WHERE chat_id =?",
            (json.dumps(history), new_pred, hits, misses, str(chat_id))
        )
        return {
            "hit": hit,
            "number": number,
            "old_pred": prediction,
            "new_pred": new_pred,
            "hits": hits,
            "misses": misses,
            "total": hits + misses
        }

def help_message():
    return (
        "🎯 <b>بوت القناص الذهبي (الرقم الواحد) V6.0</b>\n\n"
        "<b>طريقة الاستخدام:</b>\n"
        "1. أرسل سجلاً من 100 رقم أو أكثر دفعة واحدة.\n"
        "2. سيرشح البوت <b>رقماً واحداً فقط</b> ذو أعلى كثافة واحتمالية فيزيائية.\n"
        "3. أرسل كل نتيجة دورة كرقم منفرد ليتم تحديث الرقم الذهبي التالي فوراً.\n\n"
        "⚙️ <b>الأوامر:</b>\n"
        "/start - بدء جلسة جديدة وتصفير السجل\n"
        "/status - عرض الرقم المستهدف الحالي\n"
        "/stats - إحصاءات الدقة\n"
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
        prediction = user["prediction"]
        send_message(
            chat_id,
            f"📊 <b>حالة الجلسة الحية:</b>\n"
            f"• الأرقام المسجلة: <b>{len(history)}</b>\n"
            f"• آخر رقم سقط: <b>{history[-1] if history else 'لا يوجد'}</b>\n"
            f"• 🎯 <b>الرقم الذهبي المستهدف الآن:</b> <b>[{prediction if prediction!= -1 else 'لا يوجد'}]</b>"
        )
        return
    if text == "/stats":
        hits = user["hits"]
        misses = user["misses"]
        total = hits + misses
        rate = (hits / total * 100) if total > 0 else 0
        send_message(
            chat_id,
            f"📈 <b>إحصاءات الدقة:</b>\n"
            f"• إجمالي الرميات: <b>{total}</b>\n"
            f"• الإصابات المباشرة بالرقم الواحد: <b>{hits}</b>\n"
            f"• نسبة الإصابة: <b>{rate:.1f}%</b>"
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
        pred = calculate_single_sniper(numbers)
        save_user(chat_id, history=numbers, prediction=pred, hits=0, misses=0)
        send_message(
            chat_id,
            f"✅ <b>تم تفعيل محرك الرقم الواحد الذهبي V6.0</b>\n"
            f"• حجم السجل: <b>{len(numbers)}</b> رقم\n"
            f"• آخر رقم مسجل: <b>{numbers[-1]}</b>\n\n"
            f"🎯 <b>الرقم الذهبي المستهدف للدورة القادمة:</b>\n"
            f"👉 <b>[ {pred} ]</b>\n\n"
            f"أرسل الآن نتيجة الدورة التالية فور ظهورها."
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
    if res["hit"]:
        send_message(
            chat_id,
            f"🟢 <b>إصابة ذهبية مباشرة! 🎯</b>\n"
            f"ظهر الرقم المستهدف تماماً: <b>{number}</b>\n\n"
            f"🎯 <b>الرقم الذهبي للرمية القادمة:</b>\n"
            f"👉 <b>[ {res['new_pred']} ]</b>"
        )
    else:
        send_message(
            chat_id,
            f"📍 تم تسجيل الرقم: <b>{number}</b> (التوقع السابق كان: <b>{res['old_pred']}</b>)\n\n"
            f"🎯 <b>الرقم الذهبي للرمية القادمة:</b>\n"
            f"👉 <b>[ {res['new_pred']} ]</b>"
        )

@app.get("/")
def home():
    return "Roulette Single Sniper V6.0 is running.", 200

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
