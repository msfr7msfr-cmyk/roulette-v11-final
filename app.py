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
MAX_SPINS_LOCK = 4

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_10_sniper")
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
    allowed = {"history", "prediction", "spins_seen", "hits", "misses"}
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
            INSERT INTO users(chat_id, history, prediction, spins_seen, hits, misses)
            VALUES(?, '[]', '[]', 0, 0, 0)
            ON CONFLICT(chat_id) DO UPDATE SET
                history='[]', prediction='[]', spins_seen=0, hits=0, misses=0
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

def calculate_dual_sector_10(history):
    if not history:
        return WHEEL[:10]

    n_total = len(history)
    last_num = history[-1]

    blocked_cluster = set(get_wheel_neighbors(last_num, offset_range=2))

    recent_15 = history[-15:]
    recent_40 = history[-40:]

    heat_scores = {i: 0.0 for i in range(37)}
    sigma = 1.8
    for idx, num in enumerate(recent_15):
        w = math.exp((idx - len(recent_15)) / 8.0)
        for cand in range(37):
            if cand in blocked_cluster:
                continue
            d = wheel_distance(num, cand)
            heat_scores[cand] += w * math.exp(-(d ** 2) / (2 * (sigma ** 2)))
    norm_heat = z_normalize(heat_scores)

    step_scores = {i: 0.0 for i in range(37)}
    if n_total >= 10:
        steps = [wheel_step(history[i - 1], history[i]) for i in range(max(1, n_total - 25), n_total)]
        step_counts = Counter(steps)
        total_steps = len(steps)
        for cand in range(37):
            if cand in blocked_cluster:
                continue
            diff = wheel_step(last_num, cand)
            p = (step_counts.get(diff, 0) + 0.5) / (total_steps + 18.5)
            step_scores[cand] = p
    norm_step = z_normalize(step_scores)

    final_scores = {}
    for num in range(37):
        if num in blocked_cluster:
            final_scores[num] = -9999.0
        else:
            final_scores[num] = (1.6 * norm_heat[num]) + (1.4 * norm_step[num])

    ranked = sorted(range(37), key=lambda x: final_scores[x], reverse=True)

    anchor_1 = ranked[0]
    cluster_1 = get_wheel_neighbors(anchor_1, offset_range=2)

    cluster_2 = []
    for cand in ranked[1:]:
        if cand not in cluster_1:
            temp_cluster = get_wheel_neighbors(cand, offset_range=2)
            for num in temp_cluster:
                if num not in cluster_1 and num not in cluster_2:
                    cluster_2.append(num)
                if len(cluster_1) + len(cluster_2) == 10:
                    break
        if len(cluster_1) + len(cluster_2) == 10:
            break

    final_10 = cluster_1 + cluster_2
    return final_10[:10]

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
            new_pred = calculate_dual_sector_10(history)
            new_spins_seen = 0
            event = "hit" if hit else "expired"
        else:
            new_pred = prediction
            new_spins_seen = spins_seen
            event = "continue"

        con.execute(
            "UPDATE users SET history =?, prediction =?, spins_seen =?, hits =?, misses =? WHERE chat_id =?",
            (json.dumps(history), json.dumps(new_pred), new_spins_seen, hits, misses, str(chat_id))
        )

        return {
            "event": event,
            "number": number,
            "old_pred": prediction,
            "new_pred": new_pred,
            "spins_seen": spins_seen,
            "hits": hits,
            "misses": misses,
            "total": hits + misses
        }

def help_message():
    return (
        "🎯 <b>بوت قناص القطاعين (نظام الـ 10 أرقام المركزة) V12.0</b>\n\n"
        "<b>طريقة الاستخدام:</b>\n"
        "1. أرسل سجلاً من 100 رقم أو أكثر دفعة واحدة.\n"
        "2. يرصد البوت <b>أقوى قطاعين صاعدين (10 أرقام محكمة)</b> لتغطية ارتداد الكرة بنسبة 72%.\n"
        "3. يستمر الهجوم لـ 4 لفات كحد أقصى مع خروج فوري عند الإصابة 🎯.\n"
        "4. أرسل كل نتيجة دورة لمتابعة العداد.\n\n"
        "⚙️ <b>الأوامر:</b>\n"
        "/start - بدء جلسة جديدة وتصفير السجل\n"
        "/status - عرض الأرقام الـ 10 المستهدفة والمحاولة الحالية\n"
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
        prediction = json.loads(user["prediction"])
        spins_seen = user["spins_seen"]
        pred_str = ", ".join(map(str, prediction)) if prediction else "لا يوجد"
        send_message(
            chat_id,
            f"📊 <b>حالة الجلسة الحية (10 أرقام):</b>\n"
            f"• الأرقام المسجلة: <b>{len(history)}</b>\n"
            f"• آخر رقم سقط: <b>{history[-1] if history else 'لا يوجد'}</b>\n"
            f"• 🛡️ <b>الـ 10 أرقام المستهدفة:</b> <b>[{pred_str}]</b>\n"
            f"• ⏳ <b>العداد:</b> <b>المحاولة ({spins_seen}/{MAX_SPINS_LOCK})</b>"
        )
        return

    if text == "/stats":
        hits = user["hits"]
        misses = user["misses"]
        total = hits + misses
        rate = (hits / total * 100) if total > 0 else 0
        send_message(
            chat_id,
            f"📈 <b>إحصاءات القناص V12.0:</b>\n"
            f"• إجمالي الجولات: <b>{total}</b>\n"
            f"• الإصابات الناجحة (10 أرقام): <b>{hits}</b>\n"
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
        pred = calculate_dual_sector_10(numbers)
        save_user(chat_id, history=numbers, prediction=pred, spins_seen=0, hits=0, misses=0)
        pred_str = ", ".join(map(str, pred))
        send_message(
            chat_id,
            f"✅ <b>تم تفعيل محرك الـ 10 أرقام المركزة V12.0</b>\n"
            f"• عدد الأرقام في السجل: <b>{len(numbers)}</b>\n"
            f"• آخر رقم مسجل: <b>{numbers[-1]}</b> (تم حظر قطاعه)\n\n"
            f"🛡️ <b>أقوى 10 أرقام مستهدفة للـ 4 لفات القادمة:</b>\n"
            f"👉 <b>[ {pred_str} ]</b>\n\n"
            f"⏳ <b>نافذة الهجوم:</b> 4 لفات متتالية (المحاولة 0/4)\n"
            f"أرسل نتيجة كل لفة منفردة الآن."
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

    curr_pred_str = ", ".join(map(str, res["old_pred"]))
    new_pred_str = ", ".join(map(str, res["new_pred"]))

    if res["event"] == "hit":
        send_message(
            chat_id,
            f"🟢 <b>إصابة قناص مباشرة! 🎯</b> (في المحاولة {res['spins_seen']}/{MAX_SPINS_LOCK})\n"
            f"سقط الرقم <b>{number}</b> داخل الـ 10 أرقام المستهدفة <b>[{curr_pred_str}]</b>!\n\n"
            f"🛡️ <b>الـ 10 أرقام الجديدة للـ 4 لفات القادمة:</b>\n"
            f"👉 <b>[ {new_pred_str} ]</b>"
        )
    elif res["event"] == "expired":
        send_message(
            chat_id,
            f"🔴 اكتملت 4 لفات دون إصابة (آخر رقم: <b>{number}</b>).\n"
            f"تم تحديث القطاعين وتوليد الـ 10 أرقام التالية.\n\n"
            f"🛡️ <b>الـ 10 أرقام الجديدة للـ 4 لفات القادمة:</b>\n"
            f"👉 <b>[ {new_pred_str} ]</b>"
        )
    else:
        send_message(
            chat_id,
            f"📍 تم تسجيل الرقم: <b>{number}</b> | ⏳ المحاولة (<b>{res['spins_seen']}/{MAX_SPINS_LOCK}</b>)\n\n"
            f"🎯 <b>مستمرون في نفس الـ 10 أرقام:</b>\n"
            f"👉 <b>[ {curr_pred_str} ]</b>"
        )

@app.get("/")
def home():
    return "Roulette Dual Sector 10 is running.", 200

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
