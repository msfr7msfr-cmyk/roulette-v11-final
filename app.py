import os, re, json, time, hmac, sqlite3, logging
from collections import Counter, defaultdict
from flask import Flask, request, abort
import requests

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_stats")
HTTP = requests.Session()

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL)}
WHEEL_SIZE = 37

def wheel_dist(a,b):
    d = abs(WHEEL_INDEX[a]-WHEEL_INDEX[b]) % WHEEL_SIZE
    return min(d, WHEEL_SIZE-d)

def neighbors(c, r=2):
    idx = WHEEL_INDEX[c]
    return [WHEEL[(idx+o)%WHEEL_SIZE] for o in range(-r, r+1)]

def _decay_weights(n, halflife=40.0):
    return [0.5**((n-1-i)/halflife) for i in range(n)]

def _score_frequency(history, lookback=150, halflife=30.0):
    recent = history[-lookback:]
    w = _decay_weights(len(recent), halflife)
    score = [0.0]*37
    for num, weight in zip(recent, w):
        score[num] += weight
    total = sum(score) or 1.0
    return [s/total for s in score]

def _score_hot_sectors(history, lookback=60, sector_size=5):
    recent = history[-lookback:]
    if not recent:
        return [1.0/37]*37
    w = _decay_weights(len(recent), 20.0)
    activity = [0.0]*37
    for num, weight in zip(recent, w):
        for cand in neighbors(num, sector_size//2):
            activity[cand] += weight
    total = sum(activity) or 1.0
    return [a/total for a in activity]

def _combine_scores(history):
    f = _score_frequency(history)
    h = _score_hot_sectors(history)
    W = {"freq":0.6, "hot":0.4}
    score = [W["freq"]*f[i] + W["hot"]*h[i] for i in range(37)]
    t = sum(score) or 1.0
    return [x/t for x in score]

def _select_top20(history, scores):
    ranked = sorted(range(37), key=lambda x: scores[x], reverse=True)
    chosen, used = [], set()
    for cand in ranked:
        if len(chosen) >= 20: break
        too_close = sum(1 for c in chosen if wheel_dist(c,cand) <= 1)
        if too_close >= 3: continue
        chosen.append(cand); used.add(cand)
    for cand in ranked:
        if len(chosen) >= 20: break
        if cand not in used:
            chosen.append(cand); used.add(cand)
    return chosen

def calculate_v23(history):
    if not history:
        return WHEEL[:5], WHEEL[5:10], WHEEL[10:15], WHEEL[15:20], WHEEL[:20]
    scores = _combine_scores(history)
    top20 = _select_top20(history, scores)
    sectors, used = [], set()
    for center in top20:
        if len(sectors) >= 4: break
        if center in used: continue
        cluster = [x for x in neighbors(center,2) if x in top20 and x not in used]
        for x in top20:
            if len(cluster) >= 5: break
            if x not in used and x not in cluster:
                cluster.append(x)
        cluster = cluster[:5]
        if len(cluster) == 5:
            sectors.append(cluster); used.update(cluster)
    while len(sectors) < 4:
        rem = [x for x in top20 if x not in used]
        if not rem: break
        cluster = rem[:5]
        sectors.append(cluster); used.update(cluster)
    s1,s2,s3,s4 = sectors[0], sectors[1], sectors[2], sectors[3]
    final = []
    for x in s1+s2+s3+s4:
        if x not in final: final.append(x)
    for x in top20:
        if len(final) >= 20: break
        if x not in final: final.append(x)
    return s1,s2,s3,s4,final[:20]

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
            sec4 TEXT NOT NULL DEFAULT '[]',
            prediction TEXT NOT NULL DEFAULT '[]',
            hits INTEGER NOT NULL DEFAULT 0,
            misses INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY);
        """)

init_db()

def get_user(chat_id):
    with connect_db() as con:
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            con.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            con.commit()
            row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id, **vals):
    allowed = {"history","sec1","sec2","sec3","sec4","prediction","hits","misses"}
    fields, params = [], []
    for k,v in vals.items():
        if k not in allowed: continue
        if k in ("history","sec1","sec2","sec3","sec4","prediction"): v = json.dumps(v)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as con:
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)
        con.commit()

def reset_user(chat_id):
    with connect_db() as con:
        con.execute("""INSERT INTO users(chat_id) VALUES(?)
            ON CONFLICT(chat_id) DO UPDATE SET history='[]',sec1='[]',sec2='[]',sec3='[]',sec4='[]',prediction='[]',hits=0,misses=0""",
            (str(chat_id),))
        con.commit()

def send_message(chat_id, text):
    if not TOKEN: return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = HTTP.post(url, json={"chat_id":chat_id,"text":text,"disable_web_page_preview":True,"parse_mode":"HTML"}, timeout=15)
        if not r.ok:
            log.error("Telegram error: %s", r.text)
            return False
        return True
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False

def parse_numbers(text):
    tokens = [x for x in re.split(r"[\s,;،\n]+", text.strip()) if x]
    nums = []
    for t in tokens:
        if not re.fullmatch(r"\d+", t): raise ValueError(f"خطأ في الرمز: {t}")
        n = int(t)
        if not 0 <= n <= 36: raise ValueError(f"الرقم {n} خارج نطاق الروليت (0-36)")
        nums.append(n)
    return nums

def record_spin(chat_id, update_id, number):
    with connect_db() as con:
        try:
            con.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
            con.commit()
        except sqlite3.IntegrityError:
            return None
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None: return None
        user = dict(row)
        history = json.loads(user["history"])
        pred = json.loads(user["prediction"])
        if len(history) < MIN_HISTORY: return None
        hit = number in pred if pred else False
        hits = user["hits"] + (1 if hit else 0)
        misses = user["misses"] + (0 if hit else 1)
        history.append(number)
        ns1,ns2,ns3,ns4,npred = calculate_v23(history)
        con.execute("""UPDATE users SET history=?,sec1=?,sec2=?,sec3=?,sec4=?,prediction=?,hits=?,misses=? WHERE chat_id=?""",
                    (json.dumps(history), json.dumps(ns1), json.dumps(ns2), json.dumps(ns3), json.dumps(ns4), json.dumps(npred), hits, misses, str(chat_id)))
        con.commit()
        return {"hit":hit,"number":number,"new_s1":ns1,"new_s2":ns2,"new_s3":ns3,"new_s4":ns4,"new_pred":npred,"hits":hits,"misses":misses}

def help_message():
    return ("🎯 <b>بوت إحصاء الروليت V23</b>\n\n"
            "⚠️ <b>تنبيه صادق:</b> كل لفة روليت مستقلة وعشوائية، ولا يمكن لأي نظام التنبؤ بالرقم القادم بدقة.\n"
            "هذا البوت يحلل السجل ويعرض أرقاماً 'ساخنة' إحصائياً فقط، ولا يضمن أي نتيجة.\n\n"
            "1. أرسل 100 رقم على الأقل لتفعيل التحليل.\n"
            "2. كل رقم جديد يُحدّث الإحصاءات.\n\n"
            "/start - إعادة تعيين\n"
            "/status - عرض القطاعات\n"
            "/stats - إحصائيات الدقة\n"
            "/help - مساعدة")

def process_message(message, update_id):
    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    if not text: return
    if text in ("/start","/help"):
        if text == "/start": reset_user(chat_id)
        send_message(chat_id, help_message())
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if text == "/status":
        s1 = json.loads(user["sec1"]); s2 = json.loads(user["sec2"])
        s3 = json.loads(user["sec3"]); s4 = json.loads(user.get("sec4","[]"))
        send_message(chat_id, f"📊 <b>الأهداف الـ 20 الحالية:</b>\nآخر رقم: <b>{history[-1] if history else 'لا يوجد'}</b>\n\n🔵 القطاع 1: <code>{s1}</code>\n🟢 القطاع 2: <code>{s2}</code>\n🟡 القطاع 3: <code>{s3}</code>\n🟣 القطاع 4: <code>{s4}</code>")
        return
    if text == "/stats":
        h = user["hits"]; m = user["misses"]; tot = h+m
        rate = (h/tot*100) if tot else 0
        exp = 20/37*100
        send_message(chat_id, f"📈 <b>إحصائيات:</b>\nإجمالي اللفات: <b>{tot}</b> | إصابات: <b>{h}</b>\nالدقة: <b>{rate:.1f}%</b>\nالمتوقعة عشوائياً: <b>{exp:.1f}%</b>\nالفرق: <b>{rate-exp:+.1f}%</b>")
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send_message(chat_id, f"⚠️ {e}")
        return
    if not numbers: return
    if len(numbers) >= MIN_HISTORY:
        s1,s2,s3,s4,pred = calculate_v23(numbers)
        save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3, sec4=s4, prediction=pred, hits=0, misses=0)
        send_message(chat_id, f"✅ <b>تم تفعيل التحليل</b>\nحجم السجل: <b>{len(numbers)}</b>\nآخر رقم: <b>{numbers[-1]}</b>\n\n🔵 <b>القطاع 1:</b> <code>{s1}</code>\n🟢 <b>القطاع 2:</b> <code>{s2}</code>\n🟡 <b>القطاع 3:</b> <code>{s3}</code>\n🟣 <b>القطاع 4:</b> <code>{s4}</code>")
        return
    if len(numbers)!= 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} رقم.\nأرسل سجل تاريخي يحتوي على 100 رقم على الأقل للبدء أولاً.")
        return
    number = numbers[0]
    res = record_spin(chat_id, update_id, number)
    if res is None:
        send_message(chat_id, "⚠️ سجل غير مكتمل أو تم معالجة الرقم مسبقاً.")
        return
    icon = "🟢 <b>إصابة</b>" if res["hit"] else "🔴 <b>تسجيل رقم:</b>"
    send_message(chat_id, f"{icon} <b>{number}</b>\n\n🎯 <b>الأهداف الجديدة الـ 20:</b>\n🔵 <code>{res['new_s1']}</code>\n🟢 <code>{res['new_s2']}</code>\n🟡 <code>{res['new_s3']}</code>\n🟣 <code>{res['new_s4']}</code>")

@app.get("/")
def home():
    return "Roulette V23 stats bot is running.", 200

@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        if not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token",""), WEBHOOK_SECRET): abort(403)
    upd = request.get_json(silent=True)
    if not isinstance(upd, dict): return "ok", 200
    msg = upd.get("message")
    if not isinstance(msg, dict): return "ok", 200
    try:
        process_message(msg, str(upd.get("update_id", time.time_ns())))
    except:
        log.exception("Error processing webhook update")
    return "ok", 200

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
