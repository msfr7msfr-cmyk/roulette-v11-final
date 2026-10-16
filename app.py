import os
import re
import json
import time
import hmac
import sqlite3
import logging
import math
from collections import Counter, defaultdict
from flask import Flask, request, abort
import requests

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_v23_quantum")
HTTP = requests.Session()

WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
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
    return [WHEEL[(idx + o) % WHEEL_SIZE] for o in range(-r, r + 1)]

def _decay_weights(n, halflife=40.0):
    return [0.5 ** ((n - 1 - i) / halflife) for i in range(n)]

def _score_frequency(history, lookback=150, halflife=30.0):
    recent = history[-lookback:]
    w = _decay_weights(len(recent), halflife)
    score = [0.0] * 37
    for num, weight in zip(recent, w):
        score[num] += weight
    total = sum(score) or 1.0
    return [s / total for s in score]

def _score_neighbor_affinity(history, lookback=120):
    recent = history[-lookback:]
    if len(recent) < 10:
        return [1.0/37]*37, [1.0/37]*37
    near1 = [0.0] * 37
    near2 = [0.0] * 37
    w = _decay_weights(len(recent), 25.0)
    for i, num in enumerate(recent):
        for cand in range(37):
            d = wheel_dist(cand, num)
            if d == 0: continue
            if d <= 1: near1[cand] += w[i]
            if d <= 2: near2[cand] += w[i]
    s1 = sum(near1) or 1.0
    s2 = sum(near2) or 1.0
    return [x/s1 for x in near1], [x/s2 for x in near2]

def _score_step_distribution(history, lookback=120):
    if len(history) < 20:
        return [1.0/37]*37
    seg = history[-lookback:]
    steps = [wheel_step(seg[i-1], seg[i]) for i in range(1, len(seg))]
    step_counter = Counter(steps)
    total = sum(step_counter.values()) or 1
    last = history[-1]
    score = [0.0]*37
    for cand in range(37):
        s = wheel_step(last, cand)
        p = (step_counter.get(s, 0) + 0.5) / (total + 0.5 * 37)
        score[cand] = p
    t = sum(score) or 1.0
    return [x/t for x in score]

def _score_direction(history, lookback=50):
    if len(history) < 5:
        return 0.5, 0.5
    seg = history[-lookback:]
    steps = [wheel_step(seg[i-1], seg[i]) for i in range(1, len(seg))]
    steps = [s for s in steps if s!= 0]
    if not steps:
        return 0.5, 0.5
    cw = sum(1 for s in steps if s > 0)
    ccw = len(steps) - cw
    return cw/len(steps), ccw/len(steps)

def _score_markov_advanced(history, lookback=250):
    if len(history) < 40:
        return [1.0/37]*37
    seg = history[-lookback:]
    trans = defaultdict(Counter)
    trans2 = defaultdict(Counter)
    for i in range(1, len(seg)):
        p1 = WHEEL_INDEX[seg[i-1]]
        curr = WHEEL_INDEX[seg[i]]
        trans[p1][curr] += 1
        if i >= 2:
            p2 = WHEEL_INDEX[seg[i-2]]
            trans2[(p2, p1)][curr] += 1
    last_pos = WHEEL_INDEX[history[-1]]
    prev_pos = WHEEL_INDEX[history[-2]] if len(history) >= 2 else last_pos
    row = trans2.get((prev_pos, last_pos))
    if not row or sum(row.values()) < 3:
        row = trans.get(last_pos, Counter())
    total = sum(row.values())
    score = [0.0]*37
    for pos in range(37):
        score[pos] = (row.get(pos, 0) + 1.0) / (total + 1.0 * 37)
    t = sum(score) or 1.0
    return [x/t for x in score]

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

def _get_adaptive_weights(history):
    base_weights = {"freq": 0.15, "near1": 0.15, "near2": 0.10, "step": 0.20, "markov": 0.25, "hot": 0.10, "dir": 0.05}
    if len(history) < 50:
        return base_weights
    return base_weights

def _combine_scores(history):
    f = _score_frequency(history)
    n1, n2 = _score_neighbor_affinity(history)
    s = _score_step_distribution(history)
    p_cw, p_ccw = _score_direction(history)
    m = _score_markov_advanced(history)
    h = _score_hot_sectors(history)
    W = _get_adaptive_weights(history)
    score = [0.0]*37
    for i in range(37):
        score[i] = (W["freq"]*f[i] + W["near1"]*n1[i] + W["near2"]*n2[i] +
                    W["step"]*s[i] + W["markov"]*m[i] + W["hot"]*h[i])
        last = history[-1]
        d = wheel_step(last, WHEEL[i])
        if d > 0:
            score[i] += W["dir"] * p_cw * (1.0 / (1 + abs(d)))
        elif d < 0:
            score[i] += W["dir"] * p_ccw * (1.0 / (1 + abs(d)))
    t = sum(score) or 1.0
    return [x/t for x in score]

def _backtest_accuracy(history, top_n=20, test_len=30):
    if len(history) < test_len + 60:
        return None
    hits = 0
    for t in range(len(history) - test_len, len(history)):
        sub = history[:t]
        scores = _combine_scores(sub)
        top = set(sorted(range(37), key=lambda x: scores[x], reverse=True)[:top_n])
        if history[t] in top:
            hits += 1
    return hits / test_len

def _select_top20(history, scores):
    ranked = sorted(range(37), key=lambda x: scores[x], reverse=True)
    chosen = []
    used = set()
    for cand in ranked:
        if len(chosen) >= 20: break
        if cand in used: continue
        too_close = sum(1 for c in chosen if wheel_dist(c, cand) <= 1)
        if too_close >= 3: continue
        chosen.append(cand); used.add(cand)
    if len(chosen) < 20:
        for cand in ranked:
            if cand not in used:
                chosen.append(cand); used.add(cand)
                if len(chosen) >= 20: break
    return chosen

def calculate_v23(history):
    if not history:
        return WHEEL[:5], WHEEL[5:10], WHEEL[10:15], WHEEL[15:20], WHEEL[:20]
    scores = _combine_scores(history)
    top20 = _select_top20(history, scores)
    sectors = []
    used = set()
    for center in top20:
        if len(sectors) >= 4: break
        if center in used: continue
        cluster = [x for x in neighbors(center, 2) if x in top20 and x not in used]
        if len(cluster) < 5:
            for x in top20:
                if x not in used and x not in cluster:
                    cluster.append(x)
                    if len(cluster) >= 5: break
        cluster = cluster[:5]
        if len(cluster) == 5:
            sectors.append(cluster)
            used.update(cluster)
    while len(sectors) < 4:
        rem = [x for x in top20 if x not in used]
        if not rem: break
        c = rem[0]
        cluster = [c]
        used.add(c)
        for x in top20:
            if x not in used and len(cluster) < 5:
                cluster.append(x); used.add(x)
        sectors.append(cluster)
    s1, s2, s3, s4 = sectors[0], sectors[1], sectors[2], sectors[3]
    final = s1 + s2 + s3 + s4
    seen = set(); final_unique = []
    for x in final:
        if x not in seen:
            final_unique.append(x); seen.add(x)
    for x in top20:
        if len(final_unique) >= 20: break
        if x not in seen:
            final_unique.append(x); seen.add(x)
    return s1, s2, s3, s4, final_unique[:20]

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
            misses INTEGER NOT NULL DEFAULT 0,
            total_bet INTEGER NOT NULL DEFAULT 0
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
    allowed = {"history", "sec1", "sec2", "sec3", "sec4", "prediction", "hits", "misses", "total_bet"}
    fields = []; params = []
    for k, v in vals.items():
        if k not in allowed: continue
        if k in ("history", "sec1", "sec2", "sec3", "sec4", "prediction"): v = json.dumps(v)
        fields.append(f"{k}=?")
        params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as con:
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)
        con.commit()

def reset_user(chat_id):
    with connect_db() as con:
        con.execute("INSERT INTO users(chat_id,history,sec1,sec2,sec3,sec4,prediction,hits,misses,total_bet) VALUES(?, '[]','[]','[]','[]','[]','[]',0,0,0) ON CONFLICT(chat_id) DO UPDATE SET history='[]',sec1='[]',sec2='[]',sec3='[]',sec4='[]',prediction='[]',hits=0,misses=0,total_bet=0", (str(chat_id),))
        con.commit()

def send_message(chat_id, text):
    if not TOKEN: return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = HTTP.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "parse_mode": "HTML"}, timeout=15)
        if not r.ok:
            HTTP.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
            return False
        return True
    except:
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
        ns1, ns2, ns3, ns4, npred = calculate_v23(history)
        con.execute("UPDATE users SET history=?,sec1=?,sec2=?,sec3=?,sec4=?,prediction=?,hits=?,misses=? WHERE chat_id=?",
                    (json.dumps(history), json.dumps(ns1), json.dumps(ns2), json.dumps(ns3), json.dumps(ns4), json.dumps(npred), hits, misses, str(chat_id)))
        con.commit()
        return {"hit": hit, "number": number, "new_s1": ns1, "new_s2": ns2, "new_s3": ns3, "new_s4": ns4, "new_pred": npred, "hits": hits, "misses": misses}

def help_message():
    return ("🎯 <b>بوت القناص V23 Quantum Advanced</b>\n\n"
            "🧠 محرك تنبؤ متطور بالذكاء الاحتمالي:\n"
            "• Time-decay frequency (تحليل التردد الزمني)\n"
            "• Adaptive neighbor affinity (تقارب الجوار الديناميكي)\n"
            "• High-order Markov chains (سلاسل ماركوف المتقدمة للأزواج)\n"
            "• Direction momentum & Hot sectors\n\n"
            "1. أرسل 100 رقم على الأقل لتفعيل النظام.\n"
            "2. كل رقم جديد ترسله سيقوم بتحديث التوقعات وتقييم الإصابة فوراً.\n\n"
            "/start - إعادة تعيين وبداية جديدة\n"
            "/status - عرض القطاعات الأربعة الحالية\n"
            "/stats - إحصائيات الدقة والإصابات\n"
            "/backtest - اختبار خلفي للذكاء الاصطناعي\n"
            "/help - مساعدة")

def process_message(message, update_id):
    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    if not text: return
    if text in ("/start", "/help"):
        if text == "/start": reset_user(chat_id)
        send_message(chat_id, help_message())
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if text == "/status":
        s1 = json.loads(user["sec1"])
        s2 = json.loads(user["sec2"])
        s3 = json.loads(user["sec3"])
        s4 = json.loads(user.get("sec4", "[]"))
        send_message(chat_id, f"📊 <b>الأهداف الـ 20 الحالية (V23):</b>\nآخر رقم: <b>{history[-1] if history else 'لا يوجد'}</b>\n\n🔵 القطاع 1: <code>{s1}</code>\n🟢 القطاع 2: <code>{s2}</code>\n🟡 القطاع 3: <code>{s3}</code>\n🟣 القطاع 4: <code>{s4}</code>")
        return
    if text == "/stats":
        h = user["hits"]; m = user["misses"]; tot = h + m
        rate = (h / tot * 100) if tot else 0
        exp = 20 / 37 * 100
        send_message(chat_id, f"📈 <b>إحصائيات V23:</b>\nإجمالي اللفات المسجلة: <b>{tot}</b> | إصابات: <b>{h}</b>\nالدقة الحقيقية: <b>{rate:.1f}%</b>\nالمتوقعة عشوائياً: <b>{exp:.1f}%</b>\nالفرق: <b>{rate-exp:+.1f}%</b>")
        return
    if text == "/backtest":
        if len(history) < 90:
            send_message(chat_id, "تحتاج إلى 90 رقم على الأقل لإجراء الاختبار الخلفي.")
            return
        acc = _backtest_accuracy(history, top_n=20, test_len=30)
        if acc is None:
            send_message(chat_id, "السجل غير كافٍ.")
            return
        exp = 20 / 37
        send_message(chat_id, f"🧪 <b>الاختبار الخلفي (آخر 30 لفة):</b>\nدقة النموذج: <b>{acc*100:.1f}%</b>\nالعشوائي المتوقع: <b>{exp*100:.1f}%</b>\nالفرق: <b>{(acc-exp)*100:+.1f}%</b>")
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as e:
        send_message(chat_id, f"⚠️ {e}")
        return
    if not numbers: return
    if len(numbers) >= MIN_HISTORY:
        s1, s2, s3, s4, pred = calculate_v23(numbers)
        save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3, sec4=s4, prediction=pred, hits=0, misses=0)
        send_message(chat_id, f"✅ <b>تم تفعيل V23 Quantum بنجاح</b>\nحجم السجل: <b>{len(numbers)} رقم</b>\nآخر رقم: <b>{numbers[-1]}</b>\n\n🔵 <b>القطاع 1:</b> <code>{s1}</code>\n🟢 <b>القطاع 2:</b> <code>{s2}</code>\n🟡 <b>القطاع 3:</b> <code>{s3}</code>\n🟣 <b>القطاع 4:</b> <code>{s4}</code>")
        return
    if len(numbers)!= 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} رقم.\nأرسل سجل تاريخي يحتوي على 100 رقم على الأقل للبدء أولاً.")
        return
    number = numbers[0]
    res = record_spin(chat_id, update_id, number)
    if res is None:
        send_message(chat_id, "⚠️ سجل غير مكتمل أو تم معالجة الرقم مسبقاً.")
        return
    icon = "🟢 <b>إصابة صحيحة 🎯</b>" if res["hit"] else "🔴 <b>تسجيل رقم:</b>"
    send_message(chat_id, f"{icon} <b>{number}</b>\n\n🎯 <b>الأهداف الجديدة الـ 20:</b>\n🔵 <code>{res['new_s1']}</code>\n🟢 <code>{res['new_s2']}</code>\n🟡 <code>{res['new_s3']}</code>\n🟣 <code>{res['new_s4']}</code>")

@app.get("/")
def home():
    return "Roulette V23 Quantum is running successfully.", 200

@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        if not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), WEBHOOK_SECRET): abort(403)
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
