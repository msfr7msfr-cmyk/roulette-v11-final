# -*- coding: utf-8 -*-
"""Roulette bot — V101 (Top 2 Sectors: Play ALL numbers in them)."""
from __future__ import annotations
import hmac, html, json, logging, os, re, secrets, sqlite3, time, unicodedata
from collections import Counter
from typing import Any
import requests
from flask import Flask, abort, request
BOT_VERSION = "V101"
WINDOW_SIZE = 50
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
PORT = int(os.getenv("PORT", "5000"))
app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()
WHEEL = (0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26,)
WHEEL_SIZE = 37
WHEEL_INDEX = {n: i for i, n in enumerate(WHEEL)}
PICK_EMOJI = ("🟢","🔵","🟡","🟠","🔴","🟣","⚫","⚪","🟤","🔘")
def parse_numbers(text: str) -> list[int]:
    normalized = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text).strip()
    tokens = [t for t in re.split(r"[\s,;،؛|]+", normalized) if t]
    nums=[]
    for token in tokens:
        if re.fullmatch(r"\d{1,2}", token):
            n=int(token)
            if n not in WHEEL_INDEX: raise ValueError(f"الرقم {n} خارج النطاق (0-36)")
            nums.append(n); continue
        if re.fullmatch(r"\d{3,}", token):
            i, chunk, ok=0,[],True
            while i<len(token):
                two=token[i:i+2]
                if len(two)==2 and int(two)<=36: chunk.append(int(two)); i+=2
                elif int(token[i])<=36: chunk.append(int(token[i])); i+=1
                else: ok=False; break
            if ok and chunk: nums.extend(chunk); continue
        raise ValueError(f"خطأ في الرمز: {token}")
    return nums
def pick_numbers(history: list[int], window: int = WINDOW_SIZE):
    recent = history[-window:] if len(history) >= window else history[:]
    if not recent: return [], [], "empty"
    counts=Counter(recent)
    num_sectors=8; sector_size=WHEEL_SIZE//num_sectors
    sectors=[]
    for i in range(num_sectors):
        start=i*sector_size; end=start+sector_size
        sector_nums=list(WHEEL[start:end])
        if i==num_sectors-1: sector_nums=list(WHEEL[start:])
        sectors.append(sector_nums)
    sector_scores=[]
    for idx, sec in enumerate(sectors):
        score=sum(counts.get(n, 0) for n in sec)
        sector_scores.append((idx, sec, score))
    sector_scores.sort(key=lambda x: -x[2])
    top_sectors=sector_scores[:2]
    picked=[]
    for idx, sec, score in top_sectors:
        for n in sec:
            if n!=0 and n not in picked: picked.append(n)
    picked_counts=[counts.get(n, 0) for n in picked]
    sec1="، ".join(str(n) for n in top_sectors[0][1])
    sec2="، ".join(str(n) for n in top_sectors[1][1])
    mode=f"القوس الأول: ({sec1}) | القوس الثاني: ({sec2})"
    return picked, picked_counts, mode
def connect_db():
    c=sqlite3.connect(DB_FILE, timeout=20); c.row_factory=sqlite3.Row; return c
def init_db():
    with connect_db() as c:
        c.execute("PRAGMA journal_mode=WAL;")
        c.executescript("CREATE TABLE IF NOT EXISTS users (chat_id TEXT PRIMARY KEY, history TEXT NOT NULL DEFAULT '[]', prediction TEXT NOT NULL DEFAULT '[]', hits INTEGER NOT NULL DEFAULT 0, misses INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY, ts INTEGER NOT NULL);")
        c.execute("DELETE FROM updates_seen WHERE ts < ?", (int(time.time())-7*86400,))
def get_user(chat_id: str):
    with connect_db() as c:
        row=c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            c.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),)); c.commit()
            row=c.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)
def save_user(chat_id: str, **vals):
    allowed={"history","prediction","hits","misses"}; json_f={"history","prediction"}
    fields, params=[], []
    for k,v in vals.items():
        if k not in allowed: continue
        if k in json_f: v=json.dumps(v, ensure_ascii=False)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as c: c.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)
def reset_user(chat_id: str):
    with connect_db() as c: c.execute("INSERT INTO users(chat_id) VALUES(?) ON CONFLICT(chat_id) DO UPDATE SET history='[]', prediction='[]', hits=0, misses=0", (str(chat_id),))
def claim_update(update_id: str):
    with connect_db() as c:
        try: c.execute("INSERT INTO updates_seen(update_id, ts) VALUES(?, ?)", (str(update_id), int(time.time()))); return True
        except sqlite3.IntegrityError: return False
def send(chat_id: str, text: str):
    if not TOKEN: return False
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload={"chat_id":chat_id,"text":text,"disable_web_page_preview":True,"parse_mode":"HTML"}
    try:
        r=HTTP.post(url, json=payload, timeout=15)
        if r.ok: return True
        payload.pop("parse_mode", None)
        return HTTP.post(url, json=payload, timeout=15).ok
    except requests.RequestException: log.exception("send failed"); return False
def fmt_picks(picked, counts, mode):
    lines=[f"<b>{mode}</b>", ""]
    if not picked: lines.append("<i>لا توجد أرقام كافية بعد.</i>")
    else:
        for i,(n,c) in enumerate(zip(picked, counts)):
            emoji=PICK_EMOJI[i % len(PICK_EMOJI)]
            lines.append(f"{emoji} <b>{n}</b> — ظهر {c} مرات")
    return "\n".join(lines)
def help_text(): return f"<b>بوت الروليت — {BOT_VERSION} (التغطية الشاملة)</b>\n\nالمنطق:\n• يقسم العجلة إلى 8 أقواس\n• يحسب قوة كل قوس في آخر {WINDOW_SIZE} لفة\n• يختار كل أرقام أقوى قوسين (حوالي 9-10 أرقام)\n• يعرضها لك للرهان\n\n/start /status /stats /help"
def handle_new_history(chat_id: str, numbers: list[int]):
    picked, counts, mode=pick_numbers(numbers)
    save_user(chat_id, history=numbers, prediction=picked, hits=0, misses=0)
    send(chat_id, f"<b>{BOT_VERSION} — تم التفعيل</b>\nالسجل: <b>{len(numbers)}</b> رقم | آخر رقم: <b>{numbers[-1]}</b>\n\n<b>الأرقام للرهان ({len(picked)} أرقام):</b>\n{fmt_picks(picked, counts, mode)}",)
def handle_spin(chat_id: str, update_id: str, number: int):
    if not claim_update(update_id): send(chat_id, f"⚠️ {BOT_VERSION}: هذه الدورة سُجّلت مسبقاً."); return
    user=get_user(chat_id); history=json.loads(user["history"]); prediction=json.loads(user["prediction"])
    if len(history)<10: send(chat_id, f"⚠️ {BOT_VERSION}: أرسل السجل أولاً."); return
    hit=number in prediction; history.append(number)
    new_picks, new_counts, mode=pick_numbers(history)
    hits=int(user["hits"])+int(hit); misses=int(user["misses"])+int(not hit)
    save_user(chat_id, history=history, prediction=new_picks, hits=hits, misses=misses)
    label="✅ إصابة" if hit else "❌ خطأ"
    send(chat_id, f"<b>{BOT_VERSION} — {label}: {number}</b>\n\n<b>الأرقام للدورة التالية ({len(new_picks)} أرقام):</b>\n{fmt_picks(new_picks, new_counts, mode)}",)
def handle_status(chat_id, user, history):
    if len(history)<10: send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً."); return
    picked, counts, mode=pick_numbers(history)
    h,m=int(user["hits"]), int(user["misses"]); ev=h+m; rate=(h/ev*100) if ev else 0.0
    send(chat_id, f"<b>{BOT_VERSION} — الحالة</b>\nآخر رقم: <b>{history[-1]}</b>\nإجمالي السجل: <b>{len(history)}</b>\nالدقة: <b>{h}/{ev} ({rate:.1f}%)</b>\n\n<b>الأرقام الحالية ({len(picked)} أرقام):</b>\n{fmt_picks(picked, counts, mode)}",)
def handle_stats(chat_id, user):
    h,m=int(user["hits"]), int(user["misses"]); tot=h+m; rate=(h/tot*100) if tot else 0.0
    send(chat_id, f"<b>{BOT_VERSION} — الإحصاءات</b>\nاللفات: <b>{tot}</b> | إصابات: <b>{h}</b> | أخطاء: <b>{m}</b>\nالنسبة: <b>{rate:.1f}%</b>",)
def process(message, update_id: str):
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
    if len(numbers)==1 and len(history)<10: send(chat_id, f"{BOT_VERSION}: أرسل السجل أولاً (50 رقم على الأقل)."); return
    send(chat_id, f"{BOT_VERSION}: أرسل رقماً واحداً، أو سجلاً كاملاً للبدء.")
@app.get("/")
def home(): return f"ok {BOT_VERSION}", 200
@app.post("/telegram-webhook")
def webhook():
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
