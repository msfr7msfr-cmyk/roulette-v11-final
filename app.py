# -*- coding: utf-8 -*-
"""Roulette bot — V132 (Color Streak + Global AI Trend + Percentages)."""
from __future__ import annotations
import hmac, html, json, logging, os, re, secrets, sqlite3, time, unicodedata
from typing import Any
import requests
from flask import Flask, abort, request

BOT_VERSION = "V132"
WINDOW_SIZE = 200
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

WHEEL_SIZE = 37
WHEEL_INDEX = {n: i for i, n in enumerate(range(37))}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}

def parse_numbers(text: str) -> list[int]:
    normalized = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text).strip()
    tokens = [t for t in re.split(r"[\s,;،؛|]+", normalized) if t]
    nums: list[int] = []
    for token in tokens:
        if re.fullmatch(r"\d{1,2}", token):
            n = int(token)
            if n not in WHEEL_INDEX: raise ValueError(f"الرقم {n} خارج النطاق (0-36)")
            nums.append(n); continue
        if re.fullmatch(r"\d{3,}", token):
            i, chunk, ok = 0, [], True
            while i < len(token):
                two = token[i:i+2]
                if len(two) == 2 and int(two) <= 36: chunk.append(int(two)); i += 2
                elif int(token[i]) <= 36: chunk.append(int(token[i])); i += 1
                else: ok = False; break
            if ok and chunk: nums.extend(chunk); continue
        raise ValueError(f"خطأ في الرمز: {token}")
    return nums

def analyze_colors(history: list[int]):
    if len(history) < 10: return "السجل قصير جداً", None
    recent = history[-WINDOW_SIZE:] if len(history) >= WINDOW_SIZE else history[:]
    last_num = recent[-1] if recent else 0
    global_red = sum(1 for n in recent if n in RED_NUMBERS)
    global_black = sum(1 for n in recent if n in BLACK_NUMBERS)
    global_zero = sum(1 for n in recent if n == 0)
    total_global = len(recent)
    global_red_pct = (global_red / total_global) * 100 if total_global else 0
    global_black_pct = (global_black / total_global) * 100 if total_global else 0
    global_trend = "RED" if global_red > global_black else "BLACK" if global_black > global_red else "EQUAL"
    next_colors = []
    for i in range(len(recent) - 1):
        if recent[i] == last_num:
            nxt = recent[i+1]
            if nxt in RED_NUMBERS: next_colors.append("RED")
            elif nxt in BLACK_NUMBERS: next_colors.append("BLACK")
            else: next_colors.append("ZERO")
    local_red = next_colors.count("RED")
    local_black = next_colors.count("BLACK")
    local_zero = next_colors.count("ZERO")
    total_local = len(next_colors)
    local_red_pct = (local_red / total_local) * 100 if total_local else 0
    local_black_pct = (local_black / total_local) * 100 if total_local else 0
    local_trend = None
    if local_black > local_red: local_trend = "BLACK"
    elif local_red > local_black: local_trend = "RED"
    final_prediction = None
    if local_trend and global_trend != "EQUAL":
        if local_trend == global_trend: final_prediction = local_trend
        else: final_prediction = global_trend
    elif local_trend: final_prediction = local_trend
    else: final_prediction = global_trend
    result = f"🧠 <b>الذكاء الاصطناعي (آخر {total_global} لفة):</b>\n"
    result += f"🔴 أحمر: {global_red_pct:.1f}%\n"
    result += f"⚫ أسود: {global_black_pct:.1f}%\n"
    if global_zero > 0: result += f"🟢 صفر: {(global_zero/total_global)*100:.1f}%\n"
    result += f"📈 الاتجاه العام: {'🔴 أحمر' if global_trend == 'RED' else '⚫ أسود' if global_trend == 'BLACK' else '⚖️ متعادل'}\n\n"
    result += f"🔍 <b>تحليل ما بعد الرقم {last_num}:</b>\n"
    if total_local > 0:
        result += f"ظهر {total_local} مرات في السجل.\n"
        result += f"🔴 أحمر: {local_red_pct:.1f}%\n"
        result += f"⚫ أسود: {local_black_pct:.1f}%\n"
        if local_zero > 0: result += f"🟢 صفر: {(local_zero/total_local)*100:.1f}%\n"
    else: result += "لم يظهر هذا الرقم سابقاً في النافذة.\n"
    result += "\n"
    if final_prediction == "RED": result += "🎯 <b>التوقع النهائي للذكاء الاصطناعي: 🔴 أحمر</b>"
    elif final_prediction == "BLACK": result += "🎯 <b>التوقع النهائي للذكاء الاصطناعي: ⚫ أسود</b>"
    else: result += "🎯 <b>التوقع النهائي: ⚖️ لا يوجد اتجاه واضح</b>"
    return result, final_prediction

def connect_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, timeout=20); c.row_factory = sqlite3.Row; return c
def init_db() -> None:
    with connect_db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("""CREATE TABLE IF NOT EXISTS users (chat_id TEXT PRIMARY KEY, history TEXT NOT NULL DEFAULT '[]', prediction TEXT NOT NULL DEFAULT '[]', pred_color TEXT, hits INTEGER NOT NULL DEFAULT 0, misses INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY, ts INTEGER NOT NULL);""")
        c.execute("DELETE FROM updates_seen WHERE ts < ?", (int(time.time()) - 7*86400,))
def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None: c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),)); c.commit(); row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)
def save_user(chat_id: str, **vals: Any) -> None:
    allowed={"history","prediction","pred_color","hits","misses"}; json_f={"history","prediction"}; fields,params=[],[]
    for k,v in vals.items():
        if k not in allowed: continue
        if k in json_f: v=json.dumps(v, ensure_ascii=False)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as c: c.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)
def reset_user(chat_id: str) -> None:
    with connect_db() as c: c.execute("""INSERT INTO users(chat_id) VALUES(?) ON CONFLICT(chat_id) DO UPDATE SET history='[]', prediction='[]', pred_color=NULL, hits=0, misses=0""", (str(chat_id),))
def claim_update(update_id: str) -> bool:
    with connect_db() as c:
        try: c.execute("INSERT INTO updates_seen(update_id, ts) VALUES(?, ?)", (str(update_id), int(time.time()))); return True
        except sqlite3.IntegrityError: return False
def send(chat_id: str, text: str) -> bool:
    if not TOKEN: return False
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload={"chat_id":chat_id,"text":text,"disable_web_page_preview":True,"parse_mode":"HTML"}
    try:
        r=HTTP.post(url, json=payload, timeout=15)
        if r.ok: return True
        payload.pop("parse_mode", None); return HTTP.post(url, json=payload, timeout=15).ok
    except requests.RequestException: log.exception("send failed"); return False

def help_text() -> str: return f"<b>بوت الروليت — {BOT_VERSION}</b>\n\nالمنطق:\n• يحلل الاتجاه العام لآخر {WINDOW_SIZE} لفة (ذكاء اصطناعي)\n• يحلل ما بعد الرقم الأخير بالنسب المئوية\n• يعطيك التوقع النهائي ويفحصه فوراً\n\n/start /status /stats /help"
def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    analysis, color = analyze_colors(numbers)
    save_user(chat_id, history=numbers, prediction=[], pred_color=color, hits=0, misses=0)
    send(chat_id, f"<b>{BOT_VERSION} — تم التفعيل</b>\nالسجل: <b>{len(numbers)}</b> رقم | آخر رقم: <b>{numbers[-1]}</b>\n\n{analysis}")
def handle_spin(chat_id: str, update_id: str, number: int) -> None:
    if not claim_update(update_id): send(chat_id, f"⚠️ {BOT_VERSION}: هذه الدورة سُجّلت مسبقاً."); return
    user=get_user(chat_id); history=json.loads(user["history"]); old_pred_color=user.get("pred_color")
    if len(history)<10: send(chat_id, f"⚠️ {BOT_VERSION}: أرسل السجل أولاً."); return
    hit_color = False
    if old_pred_color in ("RED","BLACK"):
        actual_color = "RED" if number in RED_NUMBERS else ("BLACK" if number in BLACK_NUMBERS else "ZERO")
        if actual_color == old_pred_color: hit_color = True
    history.append(number)
    analysis, new_color = analyze_colors(history)
    hits = int(user["hits"]) + int(hit_color)
    misses = int(user["misses"]) + int(not hit_color and old_pred_color in ("RED","BLACK"))
    save_user(chat_id, history=history, prediction=[], pred_color=new_color, hits=hits, misses=misses)
    if old_pred_color in ("RED","BLACK"): label = "✅ إصابة لون!" if hit_color else "❌ خطأ (اللون لم يطابق)"
    else: label = "⏳ لا يوجد توقع سابق"
    send(chat_id, f"<b>{BOT_VERSION} — {label} ({number})</b>\n\n{analysis}")
def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history)<10: send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً."); return
    analysis, color = analyze_colors(history)
    send(chat_id, f"<b>{BOT_VERSION} — الحالة</b>\nآخر رقم: <b>{history[-1]}</b>\n\n{analysis}")
def handle_stats(chat_id: str, user: dict[str, Any]) -> None:
    h,m=int(user["hits"]),int(user["misses"]); tot=h+m; rate=(h/tot*100) if tot else 0.0
    send(chat_id, f"<b>{BOT_VERSION} — الإحصاءات</b>\nاللفات: <b>{tot}</b> | إصابات لون: <b>{h}</b> | أخطاء: <b>{m}</b>\nالنسبة: <b>{rate:.1f}%</b>")

def process(message: dict[str, Any], update_id: str) -> None:
    chat=message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat: return
    chat_id=str(chat["id"]); text=(message.get("text") or "").strip()
    if not text: return
    if text in ("/start","/help"):
        if text=="/start": reset_user(chat_id)
        send(chat_id, help_text()); return
    user=get_user(chat_id); history=json.loads(user["history"])
    if text=="/status": handle_status(chat_id, user, history); return
    if text=="/stats": handle_stats(chat_id, user); return
    try: numbers=parse_numbers(text)
    except ValueError as e: send(chat_id, f"⚠️ {BOT_VERSION}: {html.escape(str(e))}"); return
    if not numbers: return
    if len(numbers)>=10: handle_new_history(chat_id, numbers); return
    if len(numbers)==1 and len(history)>=10: handle_spin(chat_id, update_id, numbers[0]); return
    if len(numbers)==1 and len(history)<10: send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (10 أرقام على الأقل)."); return
    send(chat_id, f"{BOT_VERSION}: أرسل رقماً واحداً، أو سجلاً كاملاً للبدء.")
@app.get("/")
def home() -> tuple[str, int]: return f"ok {BOT_VERSION}", 200
@app.post("/telegram-webhook")
def webhook() -> tuple[str, int]:
    if WEBHOOK_SECRET:
        token=request.headers.get("X-Telegram-Bot-Api-Secret-Token","")
        if not hmac.compare_digest(token, WEBHOOK_SECRET): abort(403)
    update=request.get_json(silent=True)
    if not isinstance(update, dict): return "ok",200
    msg=update.get("message")
    if not isinstance(msg, dict): return "ok",200
    uid=str(update.get("update_id") or secrets.token_hex(8))
    try: process(msg, uid)
    except Exception: log.exception("handler error")
    return "ok",200
init_db()
if __name__=="__main__": app.run(host="0.0.0.0", port=PORT)
