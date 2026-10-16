# -*- coding: utf-8 -*-
"""Telegram webhook bot - Roulette V23 Single File"""
from __future__ import annotations
import hmac, html, json, logging, os, re, sqlite3, time, math
from collections import Counter, defaultdict
from typing import Any
import requests
from flask import Flask, abort, request

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100
MIN_BACKTEST_SPINS = 30
RANDOM_TOP20_RATE = 20 / 37

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("roulette_bot")
HTTP = requests.Session()

if not WEBHOOK_SECRET:
    log.warning("WEBHOOK_SECRET is unset")

# ================= ROULETTE MODEL =================
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL)}
WHEEL_SIZE = 37

def wheel_dist(a,b):
    d = abs(WHEEL_INDEX[a]-WHEEL_INDEX[b]) % WHEEL_SIZE
    return min(d, WHEEL_SIZE-d)

def wheel_step(a,b):
    d = (WHEEL_INDEX[b]-WHEEL_INDEX[a]) % WHEEL_SIZE
    if d > WHEEL_SIZE//2: d -= WHEEL_SIZE
    return int(d)

def neighbors(c,r=2):
    idx = WHEEL_INDEX[c]
    return [WHEEL[(idx+o)%WHEEL_SIZE] for o in range(-r,r+1)]

def _decay_weights(n, halflife=40.0):
    return [0.5**((n-1-i)/halflife) for i in range(n)]

def _score_frequency(history, lookback=150, halflife=30.0):
    recent = history[-lookback:]
    w = _decay_weights(len(recent), halflife)
    s = [0.0]*37
    for n,wt in zip(recent,w): s[n]+=wt
    t=sum(s) or 1.0
    return [x/t for x in s]

def _score_neighbor_affinity(history, lookback=120):
    recent = history[-lookback:]
    if len(recent)<10: return [1/37]*37,[1/37]*37
    n1=[0.0]*37; n2=[0.0]*37
    w=_decay_weights(len(recent),25.0)
    for i,num in enumerate(recent):
        for cand in range(37):
            d=wheel_dist(cand,num)
            if d==0: continue
            if d<=1: n1[cand]+=w[i]
            if d<=2: n2[cand]+=w[i]
    return [x/(sum(n1) or 1) for x in n1],[x/(sum(n2) or 1) for x in n2]

def _score_step_distribution(history, lookback=120):
    if len(history)<20: return [1/37]*37
    seg=history[-lookback:]
    steps=[wheel_step(seg[i-1],seg[i]) for i in range(1,len(seg))]
    cnt=Counter(steps); tot=sum(cnt.values()) or 1
    last=history[-1]
    s=[0.0]*37
    for cand in range(37):
        st=wheel_step(last,cand)
        s[cand]=(cnt.get(st,0)+0.5)/(tot+0.5*37)
    t=sum(s) or 1.0
    return [x/t for x in s]

def _score_markov(history, lookback=250):
    if len(history)<40: return [1/37]*37
    seg=history[-lookback:]
    trans=defaultdict(Counter); trans2=defaultdict(Counter)
    for i in range(1,len(seg)):
        trans[seg[i-1]][seg[i]]+=1
        if i>=2: trans2[(seg[i-2],seg[i-1])][seg[i]]+=1
    row=trans2.get((seg[-2],seg[-1]))
    if not row or sum(row.values())<3:
        row=trans.get(seg[-1],Counter())
    tot=sum(row.values())
    return [(row.get(n,0)+1.0)/(tot+1.0*37) for n in range(37)]

def _score_hot_sectors(history, lookback=60):
    recent=history[-lookback:]
    if not recent: return [1/37]*37
    w=_decay_weights(len(recent),20.0)
    act=[0.0]*37
    for n,wt in zip(recent,w):
        for cand in neighbors(n,2): act[cand]+=wt
    t=sum(act) or 1.0
    return [v/t for v in act]

def _combine_scores(history):
    if not history: return [1/37]*37
    f=_score_frequency(history); n1,n2=_score_neighbor_affinity(history)
    st=_score_step_distribution(history); mk=_score_markov(history); hot=_score_hot_sectors(history)
    seg=history[-50:]
    steps=[wheel_step(seg[i-1],seg[i]) for i in range(1,len(seg)) if wheel_step(seg[i-1],seg[i])!=0]
    cw=sum(1 for s in steps if s>0)/len(steps) if steps else 0.5
    ccw=1-cw
    W={"freq":0.15,"near1":0.15,"near2":0.10,"step":0.20,"markov":0.25,"hot":0.10,"dir":0.05}
    scores=[0.0]*37; last=history[-1]
    for i in range(37):
        scores[i]=W["freq"]*f[i]+W["near1"]*n1[i]+W["near2"]*n2[i]+W["step"]*st[i]+W["markov"]*mk[i]+W["hot"]*hot[i]
        d=wheel_step(last,i)
        if d>0: scores[i]+=W["dir"]*cw/(1+abs(d))
        elif d<0: scores[i]+=W["dir"]*ccw/(1+abs(d))
    t=sum(scores) or 1.0
    return [x/t for x in scores]

def calculate_v23(history):
    if not history:
        return WHEEL[:5],WHEEL[5:10],WHEEL[10:15],WHEEL[15:20],WHEEL[:20]
    scores=_combine_scores(history)
    ranked=sorted(range(37),key=lambda x: scores[x],reverse=True)
    top20=[]
    for cand in ranked:
        if len(top20)>=20: break
        if sum(1 for c in top20 if wheel_dist(c,cand)<=1)>=3: continue
        top20.append(cand)
    for cand in ranked:
        if len(top20)>=20: break
        if cand not in top20: top20.append(cand)
    sectors=[]; used=set()
    for center in top20:
        if len(sectors)>=4: break
        if center in used: continue
        cluster=[x for x in neighbors(center,2) if x in top20 and x not in used]
        for x in top20:
            if len(cluster)>=5: break
            if x not in used and x not in cluster: cluster.append(x)
        cluster=cluster[:5]
        if len(cluster)==5: sectors.append(cluster); used.update(cluster)
    while len(sectors)<4:
        rem=[x for x in top20 if x not in used]
        if not rem: break
        sectors.append(rem[:5]); used.update(rem[:5])
    return sectors[0],sectors[1],sectors[2],sectors[3],top20

def parse_numbers(text):
    _ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    text=(text or "").translate(_ARABIC_DIGITS)
    tokens=[x for x in re.split(r"[\s,;،\n]+", text.strip()) if x]
    nums=[]
    for t in tokens:
        if not re.fullmatch(r"\d+", t): raise ValueError(f"رمز غير صالح: {t}")
        n=int(t)
        if not 0<=n<=36: raise ValueError(f"الرقم {n} خارج النطاق (0-36)")
        nums.append(n)
    return nums

def wilson_interval(hits, n, z=1.96):
    if n==0: return 0.0,0.0
    p=hits/n
    d=1+z*z/n
    c=p+z*z/(2*n)
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return max(0,(c-h)/d), min(1,(c+h)/d)

def _backtest_accuracy(history, top_n=20, test_len=200):
    if len(history) < MIN_HISTORY + MIN_BACKTEST_SPINS: return None
    hits=0; trials=0
    start=max(MIN_HISTORY, len(history)-test_len)
    for t in range(start, len(history)):
        sub=history[:t]
        scores=_combine_scores(sub)
        top=set(sorted(range(37),key=lambda x: scores[x],reverse=True)[:top_n])
        trials+=1
        if history[t] in top: hits+=1
    if trials==0: return None
    rate=hits/trials
    lo,hi=wilson_interval(hits,trials)
    return {"rate":rate,"baseline":RANDOM_TOP20_RATE,"hits":hits,"trials":trials,"ci_low":lo,"ci_high":hi,"above_baseline_significant":lo>RANDOM_TOP20_RATE}

# ================= DATABASE =================
def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_FILE, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection

def init_db() -> None:
    with connect_db() as connection:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.executescript("""
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

def get_user(chat_id: str) -> dict[str, Any]:
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            connection.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            connection.commit()
            row = connection.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id: str, **values: Any) -> None:
    allowed = {"history", "sec1", "sec2", "sec3", "sec4", "prediction","hits", "misses", "total_bet"}
    json_fields = {"history", "sec1", "sec2", "sec3", "sec4", "prediction"}
    fields: list[str] = []
    parameters: list[Any] = []
    for key, value in values.items():
        if key not in allowed: continue
        if key in json_fields: value = json.dumps(value, ensure_ascii=False)
        fields.append(f"{key}=?")
        parameters.append(value)
    if not fields: return
    parameters.append(str(chat_id))
    with connect_db() as connection:
        connection.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", parameters)

def reset_user(chat_id: str) -> None:
    with connect_db() as connection:
        connection.execute("""
            INSERT INTO users(chat_id,history,sec1,sec2,sec3,sec4,prediction,hits,misses,total_bet)
            VALUES(?, '[]','[]','[]','[]','[]','[]',0,0,0)
            ON CONFLICT(chat_id) DO UPDATE SET
              history='[]',sec1='[]',sec2='[]',sec3='[]',sec4='[]',
              prediction='[]',hits=0,misses=0,total_bet=0
            """, (str(chat_id),))

def send_message(chat_id: str, text: str) -> bool:
    if not TOKEN:
        log.error("BOT_TOKEN is not configured")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id,"text": text,"disable_web_page_preview": True,"parse_mode": "HTML"}
    try:
        response = HTTP.post(url, json=payload, timeout=15)
        if response.ok: return True
        payload.pop("parse_mode")
        retry = HTTP.post(url, json=payload, timeout=15)
        return retry.ok
    except requests.RequestException:
        log.exception("Unable to send Telegram message.")
        return False

def record_spin(chat_id: str, update_id: str, number: int) -> dict[str, Any] | None:
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None: return None
        user = dict(row)
        history = json.loads(user["history"])
        if len(history) < MIN_HISTORY: return None
        try:
            connection.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
        except sqlite3.IntegrityError:
            return None
        prediction = calculate_v23(history)[4]
        hit = number in prediction
        hits = user["hits"] + int(hit)
        misses = user["misses"] + int(not hit)
        history.append(number)
        sec1, sec2, sec3, sec4, new_prediction = calculate_v23(history)
        connection.execute("""
            UPDATE users
            SET history=?,sec1=?,sec2=?,sec3=?,sec4=?,prediction=?,hits=?,misses=?
            WHERE chat_id=?
            """, (json.dumps(history), json.dumps(sec1),json.dumps(sec2), json.dumps(sec3), json.dumps(sec4),json.dumps(new_prediction), hits, misses, str(chat_id)))
        return {"hit": hit,"number": number,"new_s1": sec1,"new_s2": sec2,"new_s3": sec3,"new_s4": sec4,"new_pred": new_prediction,"hits": hits,"misses": misses}

def _format_list(values: list[int]) -> str:
    return html.escape("، ".join(str(value) for value in values))

def help_message() -> str:
    return (
        "<b>بوت تحليل الروليت</b>\n\n"
        "يرتّب 20 رقمًا باستخدام تكرارات مموّهة إحصائيًا، وأنماط الجوار والانتقال.\n"
        "الروليت العادل عشوائي؛ لا توجد طريقة تضمن معرفة الرقم القادم أو الربح.\n\n"
        "1. أرسل سجلًا تاريخيًا من 100 رقم على الأقل. يقبل الأرقام العربية والفارسية أيضًا.\n"
        "2. بعد التفعيل، أرسل رقمًا واحدًا بعد كل دورة لتحديث الاختيار والإحصاءات.\n\n"
        "/start - مسح السجل الحالي والبدء من جديد\n"
        "/status - عرض الأرقام العشرين الحالية\n"
        "/stats - عرض النتائج مقارنة بخط الأساس العشوائي\n"
        "/backtest - اختبار متدرّج على نتائج لم تُستخدم في كل توقع\n"
        "/help - المساعدة"
    )

def process_message(message: dict[str, Any], update_id: str) -> None:
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat: return
    chat_id = str(chat["id"])
    text = (message.get("text") or "").strip()
    if not text: return
    if text in ("/start", "/help"):
        if text == "/start": reset_user(chat_id)
        send_message(chat_id, help_message())
        return
    user = get_user(chat_id)
    history = json.loads(user["history"])
    if text == "/status":
        sec1, sec2, sec3, sec4, prediction = calculate_v23(history) if len(history) >= MIN_HISTORY else ([], [], [], [], [])
        if len(history) < MIN_HISTORY or len(prediction) != 20:
            send_message(chat_id, "أرسل سجلًا تاريخيًا من 100 رقم على الأقل لتفعيل التوقعات.")
            return
        scores = _combine_scores(history)
        estimated_coverage = sum(scores[number] for number in prediction)
        message_text = (
            "<b>الأرقام العشرون المختارة حاليًا</b>\n"
            f"آخر رقم مسجل: <b>{history[-1]}</b>\n"
            f"تقدير تغطية النموذج: <b>{estimated_coverage * 100:.1f}%</b>\n"
            f"خط الأساس العشوائي: <b>{RANDOM_TOP20_RATE * 100:.1f}%</b>\n"
            "<i>هذا تقدير من السجل وليس ضمانًا للنتيجة القادمة.</i>\n\n"
            f"المجموعة 1: <code>{_format_list(sec1)}</code>\n"
            f"المجموعة 2: <code>{_format_list(sec2)}</code>\n"
            f"المجموعة 3: <code>{_format_list(sec3)}</code>\n"
            f"المجموعة 4: <code>{_format_list(sec4)}</code>"
        )
        send_message(chat_id, message_text)
        return
    if text == "/stats":
        hits, misses = int(user["hits"]), int(user["misses"])
        total = hits + misses
        if total:
            rate = hits / total
            low, high = wilson_interval(hits, total)
            confidence = f"فاصل الثقة 95%: <b>{low * 100:.1f}%–{high * 100:.1f}%</b>\n"
        else:
            rate = 0.0
            confidence = ""
        send_message(chat_id,
            "<b>الإحصاءات الفعلية</b>\n"
            f"اللفات المقيمة: <b>{total}</b> | إصابات: <b>{hits}</b> | إخفاقات: <b>{misses}</b>\n"
            f"نسبة الإصابة: <b>{rate * 100:.1f}%</b>\n"
            f"{confidence}"
            f"خط الأساس لاختيار 20 من 37: <b>{RANDOM_TOP20_RATE * 100:.1f}%</b>\n"
            "<i>العينة القصيرة قد تبدو أعلى أو أقل من مستواها الحقيقي.</i>")
        return
    if text == "/backtest":
        result = _backtest_accuracy(history, top_n=20, test_len=200)
        if result is None:
            required = MIN_HISTORY + MIN_BACKTEST_SPINS
            send_message(chat_id, f"أحتاج إلى {required} رقمًا على الأقل: 100 رقم للتدريب و30 على الأقل للاختبار.")
            return
        difference = (float(result["rate"]) - float(result["baseline"])) * 100
        conclusion = (
            "الحد الأدنى لفاصل الثقة تجاوز خط الأساس في هذا الاختبار."
            if result["above_baseline_significant"]
            else "لا يثبت هذا الاختبار أن النموذج يتفوّق على العشوائي."
        )
        send_message(chat_id,
            "<b>اختبار تاريخي متدرّج</b>\n"
            f"اللفات المختبرة: <b>{result['trials']}</b> | الإصابات: <b>{result['hits']}</b>\n"
            f"الدقة: <b>{float(result['rate']) * 100:.1f}%</b>\n"
            f"خط الأساس العشوائي: <b>{float(result['baseline']) * 100:.1f}%</b>\n"
            f"الفرق: <b>{difference:+.1f} نقطة مئوية</b>\n"
            f"فاصل الثقة 95%: <b>{float(result['ci_low']) * 100:.1f}%–{float(result['ci_high']) * 100:.1f}%</b>\n"
            f"<i>{conclusion} النتائج الماضية لا تضمن المستقبل.</i>")
        return
    try:
        numbers = parse_numbers(text)
    except ValueError as error:
        send_message(chat_id, f"⚠️ {html.escape(str(error))}")
        return
    if not numbers: return
    if len(numbers) >= MIN_HISTORY:
        sec1, sec2, sec3, sec4, prediction = calculate_v23(numbers)
        save_user(chat_id,history=numbers,sec1=sec1,sec2=sec2,sec3=sec3,sec4=sec4,prediction=prediction,hits=0,misses=0)
        scores = _combine_scores(numbers)
        coverage = sum(scores[number] for number in prediction)
        send_message(chat_id,
            "<b>تم تسجيل السجل وتفعيل التحليل</b>\n"
            f"حجم السجل: <b>{len(numbers)}</b> | آخر رقم: <b>{numbers[-1]}</b>\n"
            f"تقدير تغطية النموذج: <b>{coverage * 100:.1f}%</b> | "
            f"خط الأساس العشوائي: <b>{RANDOM_TOP20_RATE * 100:.1f}%</b>\n"
            "<i>التوقع احتمالي ولا يضمن نتيجة أو ربحًا.</i>\n\n"
            f"المجموعة 1: <code>{_format_list(sec1)}</code>\n"
            f"المجموعة 2: <code>{_format_list(sec2)}</code>\n"
            f"المجموعة 3: <code>{_format_list(sec3)}</code>\n"
            f"المجموعة 4: <code>{_format_list(sec4)}</code>")
        return
    if len(numbers) != 1 or len(history) < MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} رقمًا. أرسل سجلًا تاريخيًا من {MIN_HISTORY} رقم على الأقل للبدء.")
        return
    result = record_spin(chat_id, update_id, numbers[0])
    if result is None:
        send_message(chat_id, "⚠️ السجل غير مكتمل أو سبق تسجيل هذه الدورة.")
        return
    label = "إصابة" if result["hit"] else "لم تصب هذه المرة"
    send_message(chat_id,
        f"<b>{label}: {result['number']}</b>\n\n"
        "<b>الأرقام العشرون للدورة التالية:</b>\n"
        f"1: <code>{_format_list(result['new_s1'])}</code>\n"
        f"2: <code>{_format_list(result['new_s2'])}</code>\n"
        f"3: <code>{_format_list(result['new_s3'])}</code>\n"
        f"4: <code>{_format_list(result['new_s4'])}</code>")

@app.get("/")
def home() -> tuple[str, int]:
    return "Roulette analysis bot is running.", 200

@app.post("/telegram-webhook")
def webhook() -> tuple[str, int]:
    if WEBHOOK_SECRET and not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), WEBHOOK_SECRET):
        abort(403)
    update = request.get_json(silent=True)
    if not isinstance(update, dict): return "ok", 200
    message = update.get("message")
    if not isinstance(message, dict): return "ok", 200
    try:
        process_message(message, str(update.get("update_id", time.time_ns())))
    except Exception:
        log.exception("Error processing Telegram webhook update.")
    return "ok", 200

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
