# -*- coding: utf-8 -*-
"""Roulette bot — V121 (Streets 4-9, 40 spins, Warning if whole street missing)."""
from __future__ import annotations
import hmac, html, json, logging, os, re, secrets, sqlite3, time, unicodedata
from collections import Counter
from typing import Any
import requests
from flask import Flask, abort, request

BOT_VERSION = "V121"
WINDOW_HORIZONTAL = 100
WINDOW_VERTICAL = 40
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
COLUMNS = [{"id":1,"name":"البرج 1","nums":[1,4,7,10,13,16,19,22,25,28,31,34]},{"id":2,"name":"البرج 2","nums":[2,5,8,11,14,17,20,23,26,29,32,35]},{"id":3,"name":"البرج 3","nums":[3,6,9,12,15,18,21,24,27,30,33,36]}]
STREETS = [{"id":4,"name":"عمود 4","emoji":"🟣","nums":[4,14,24,34]},{"id":5,"name":"عمود 5","emoji":"🟢","nums":[5,15,25,35]},{"id":6,"name":"عمود 6","emoji":"🔵","nums":[6,16,26,36]},{"id":7,"name":"عمود 7","emoji":"🟡","nums":[7,17,27]},{"id":8,"name":"عمود 8","emoji":"🟠","nums":[8,18,28]},{"id":9,"name":"عمود 9","emoji":"🔴","nums":[9,19,29]}]

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

def pick_numbers(history: list[int]):
    if not history: return {}, {}, "السجل فارغ"
    recent_ver = history[-WINDOW_VERTICAL:] if len(history) >= WINDOW_VERTICAL else history[:]
    counts_ver = Counter(recent_ver)
    missing_ver = {}
    for st in STREETS:
        missing = [n for n in st["nums"] if counts_ver.get(n, 0) == 0]
        if 2 <= len(missing) <= 4:
            is_whole_missing = (len(missing) == len(st["nums"]))
            missing_ver[st["id"]] = {"name": st["name"], "emoji": st["emoji"], "missing": missing, "whole": is_whole_missing}
    recent_hor = history[-WINDOW_HORIZONTAL:] if len(history) >= WINDOW_HORIZONTAL else history[:]
    counts_hor = Counter(recent_hor)
    missing_hor = {}
    for col in COLUMNS:
        missing = [n for n in col["nums"] if counts_hor.get(n, 0) == 0]
        missing_hor[col["id"]] = {"name": col["name"], "missing": missing}
    return missing_hor, missing_ver, "مهمتان: الأعمدة (40) والأبراج (100)"

def connect_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, timeout=20); c.row_factory = sqlite3.Row; return c
def init_db() -> None:
    with connect_db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("""CREATE TABLE IF NOT EXISTS users (chat_id TEXT PRIMARY KEY, history TEXT NOT NULL DEFAULT '[]', prediction TEXT NOT NULL DEFAULT '[]', hits INTEGER NOT NULL DEFAULT 0, misses INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY, ts INTEGER NOT NULL);""")
        c.execute("DELETE FROM updates_seen WHERE ts < ?", (int(time.time()) - 7*86400,))
def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as c:
        row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None: c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),)); c.commit(); row = c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)
def save_user(chat_id: str, **vals: Any) -> None:
    allowed={"history","prediction","hits","misses"}; json_f={"history","prediction"}; fields,params=[],[]
    for k,v in vals.items():
        if k not in allowed: continue
        if k in json_f: v=json.dumps(v, ensure_ascii=False)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as c: c.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)
def reset_user(chat_id: str) -> None:
    with connect_db() as c: c.execute("""INSERT INTO users(chat_id) VALUES(?) ON CONFLICT(chat_id) DO UPDATE SET history='[]', prediction='[]', hits=0, misses=0""", (str(chat_id),))
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
def fmt_picks(missing_hor: dict, missing_ver: dict, mode: str) -> str:
    lines=[f"<b>{BOT_VERSION} — {mode}</b>",""]
    lines.append("🔽 <b>المهمة الأولى: الأعمدة الرأسية (آخر 40 لفة)</b>")
    if missing_ver:
        for sid in sorted(missing_ver.keys()):
            info=missing_ver[sid]; nums_str="، ".join(map(str, info["missing"]))
            if info["whole"]: lines.append(f"{info['emoji']} <b>{info['name']} 🚨 (العمود كامل غائب):</b> {nums_str}")
            else: lines.append(f"{info['emoji']} <b>{info['name']}:</b> {nums_str}")
    else:
        lines.append("<i>لا يوجد أعمدة مفقودة (2-4) حالياً.</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔼 <b>المهمة الثانية: الأبراج الأفقية (آخر 100 لفة)</b>")
    for cid in sorted(missing_hor.keys()):
        info=missing_hor[cid]; nums_str="، ".join(map(str, info["missing"])) if info["missing"] else "ظهر بالكامل"; lines.append(f"🔸 <b>{info['name']}:</b> {nums_str}")
    return "\n".join(lines)
def help_text() -> str: return f"<b>بوت الروليت — {BOT_VERSION}</b>\n\nالمنطق (مهمتان):\n1. الأعمدة (4-9): آخر {WINDOW_VERTICAL} لفة (يعرض فقط المفقود 2-4)\n2. الأبراج الثلاثة: آخر {WINDOW_HORIZONTAL} لفة (يعرض كل المفقود)\n\n/start /status /stats /help"
def handle_new_history(chat_id: str, numbers: list[int]) -> None:
    hor, ver, mode = pick_numbers(numbers)
    save_user(chat_id, history=numbers, prediction=[], hits=0, misses=0)
    send(chat_id, f"<b>{BOT_VERSION} — تم التفعيل</b>\nالسجل: <b>{len(numbers)}</b> رقم | آخر رقم: <b>{numbers[-1]}</b>\n\n{fmt_picks(hor, ver, mode)}")
def handle_spin(chat_id: str, update_id: str, number: int) -> None:
    if not claim_update(update_id): send(chat_id, f"⚠️ {BOT_VERSION}: هذه الدورة سُجّلت مسبقاً."); return
    user=get_user(chat_id); history=json.loads(user["history"])
    if len(history)<10: send(chat_id, f"⚠️ {BOT_VERSION}: أرسل السجل أولاً."); return
    history.append(number)
    hor, ver, mode = pick_numbers(history)
    save_user(chat_id, history=history, prediction=[], hits=int(user["hits"]), misses=int(user["misses"]))
    send(chat_id, f"<b>{BOT_VERSION} — اللفة: {number}</b>\n\n{fmt_picks(hor, ver, mode)}")
def handle_status(chat_id: str, user: dict[str, Any], history: list[int]) -> None:
    if len(history)<10: send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً."); return
    hor, ver, mode = pick_numbers(history)
    send(chat_id, f"<b>{BOT_VERSION} — الحالة</b>\nآخر رقم: <b>{history[-1]}</b>\nإجمالي السجل: <b>{len(history)}</b>\n\n{fmt_picks(hor, ver, mode)}")
def handle_stats(chat_id: str, user: dict[str, Any]) -> None:
    send(chat_id, f"<b>{BOT_VERSION} — الإحصاءات</b>\nالبوت يركز على عرض المفقود من الأعمدة (2-4) والأبراج الثلاثة.")
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
    if len(numbers)==1 and len(history)<10: send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (100 رقم على الأقل)."); return
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
