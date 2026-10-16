import os, re, json, time, hmac, sqlite3, logging, math
from collections import Counter
from flask import Flask, request, abort
import requests

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_FILE = os.getenv("DATABASE_PATH", "roulette.sqlite3")
MIN_HISTORY = 100

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roulette_21_precision")
HTTP = requests.Session()

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_INDEX = {n:i for i,n in enumerate(WHEEL)}
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
            sec4 TEXT NOT NULL DEFAULT '[]',
            prediction TEXT NOT NULL DEFAULT '[]',
            hits INTEGER NOT NULL DEFAULT 0,
            misses INTEGER NOT NULL DEFAULT 0,
            total_bet INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS updates_seen (update_id TEXT PRIMARY KEY);
        """)
        for col in ["sec4","total_bet"]:
            try: con.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT '[]'" if col=="sec4" else f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
            except: pass
init_db()

def get_user(chat_id):
    with connect_db() as con:
        row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            con.execute("INSERT INTO users(chat_id) VALUES(?)", (str(chat_id),))
            row = con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        return dict(row)

def save_user(chat_id, **vals):
    allowed={"history","sec1","sec2","sec3","sec4","prediction","hits","misses","total_bet"}
    fields=[]; params=[]
    for k,v in vals.items():
        if k not in allowed: continue
        if k in ("history","sec1","sec2","sec3","sec4","prediction"): v=json.dumps(v)
        fields.append(f"{k}=?"); params.append(v)
    if not fields: return
    params.append(str(chat_id))
    with connect_db() as con:
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE chat_id=?", params)

def reset_user(chat_id):
    with connect_db() as con:
        con.execute("INSERT INTO users(chat_id,history,sec1,sec2,sec3,sec4,prediction,hits,misses,total_bet) VALUES(?, '[]','[]','[]','[]','[]','[]',0,0,0) ON CONFLICT(chat_id) DO UPDATE SET history='[]',sec1='[]',sec2='[]',sec3='[]',sec4='[]',prediction='[]',hits=0,misses=0,total_bet=0", (str(chat_id),))

def send_message(chat_id, text):
    if not TOKEN: return False
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r=HTTP.post(url, json={"chat_id":chat_id,"text":text,"disable_web_page_preview":True,"parse_mode":"HTML"}, timeout=15)
        if not r.ok:
            HTTP.post(url, json={"chat_id":chat_id,"text":text}, timeout=15); return False
        return True
    except: return False

def parse_numbers(text):
    tokens=[x for x in re.split(r"[\s,;،\n]+", text.strip()) if x]
    nums=[]
    for t in tokens:
        if not re.fullmatch(r"\d+", t): raise ValueError(f"خطأ: {t}")
        n=int(t)
        if not 0<=n<=36: raise ValueError(f"الرقم {n} خارج النطاق")
        nums.append(n)
    return nums

def wheel_dist(a,b):
    d=abs(WHEEL_INDEX[a]-WHEEL_INDEX[b])%WHEEL_SIZE
    return min(d, WHEEL_SIZE-d)

def wheel_step(a,b):
    d=(WHEEL_INDEX[b]-WHEEL_INDEX[a])%WHEEL_SIZE
    if d>WHEEL_SIZE/2: d-=WHEEL_SIZE
    return int(d)

def get_neighbors(c, r=2):
    idx=WHEEL_INDEX[c]
    return [WHEEL[(idx+o)%WHEEL_SIZE] for o in range(-r, r+1)]

def calculate_precision_20(history):
    if not history: return WHEEL[:5],WHEEL[5:10],WHEEL[10:15],WHEEL[15:20],WHEEL[:20]
    last=history[-1]
    n=len(history)

    # 1. حساب القوة الحقيقية لكل مركز (بدون مطاردة الذيل)
    # نستخدم آخر 200 لفة بوزن متساوي نسبياً + Laplace
    recent = history[-200:]
    freq = Counter(recent)
    # Score لكل رقم = تردده + تأثير جيرانه الفيزيائيين
    scores={}
    for cand in range(37):
        base = (freq.get(cand,0) + 1.0) / (len(recent)+37) # Laplace smoothing
        neigh_score=0
        for nb in get_neighbors(cand,1):
            neigh_score += (freq.get(nb,0)+1.0)/(len(recent)+37)
        scores[cand]= base*0.6 + neigh_score*0.13 # وزن الجيران 40%

    # 2. توزيع القفزات - نأخذ التوزيع الكامل وليس قفزة واحدة
    if n>=20:
        steps=[wheel_step(history[i-1],history[i]) for i in range(max(1,n-100),n)]
        step_c=Counter(steps)
        for cand in range(37):
            d=wheel_step(last,cand)
            p=(step_c.get(d,0)+0.5)/(len(steps)+18.5)
            scores[cand] += p*0.8 # وزن القفزة أقل من التردد لتقليل الضجيج

    # 3. منع العقوبة السابقة - لا نعاقب الرقم الأخير، بل نتعامل معه بشكل طبيعي
    # ترتيب المراكز من الأقوى للأضعف
    ranked=sorted(range(37), key=lambda x: scores[x], reverse=True)

    # 4. بناء 4 قطاعات 5 أرقام غير متداخلة بأعلى قوة
    sectors=[]
    used=set()
    for center in ranked:
        if len(sectors)>=4: break
        cluster=get_neighbors(center,2)
        if set(cluster).intersection(used): continue
        # تأكد أن القطاع كامل ومتصل
        sectors.append(cluster)
        used.update(cluster)

    # إكمال إذا نقص قطاع
    while len(sectors)<4:
        rem=[x for x in ranked if x not in used]
        if not rem: break
        c=rem[0]
        cl=get_neighbors(c,2)
        # قص للـ 5 غير مستخدمة
        cl=[x for x in cl if x not in used][:5]
        while len(cl)<5:
            for x in ranked:
                if x not in used and x not in cl: cl.append(x); break
        sectors.append(cl); used.update(cl)

    # الترتيب: القطاع الأول هو الأقوى، الثاني هو المقابل، الثالث قفزة، الرابع ساخن
    # لإبقاء التوافق مع الواجهة
    s1,s2,s3,s4 = sectors[0],sectors[1],sectors[2],sectors[3]
    # إجبار القطاع الأول أن يحتوي جيران آخر رقم إذا كان قوياً (توازن)
    # لا نجبره إذا كان ضعيف جداً - هذا هو الإصلاح الأساسي
    final=s1+s2+s3+s4
    return s1,s2,s3,s4,final[:20]

def record_spin(chat_id, update_id, number):
    with connect_db() as con:
        try: con.execute("INSERT INTO updates_seen(update_id) VALUES(?)", (str(update_id),))
        except sqlite3.IntegrityError: return None
        row=con.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None: return None
        user=dict(row); history=json.loads(user["history"]); pred=json.loads(user["prediction"])
        if len(history)<MIN_HISTORY: return None
        hit=number in pred if pred else False
        hits=user["hits"]+(1 if hit else 0); misses=user["misses"]+(0 if hit else 1)
        history.append(number)
        ns1,ns2,ns3,ns4,npred=calculate_precision_20(history)
        con.execute("UPDATE users SET history=?,sec1=?,sec2=?,sec3=?,sec4=?,prediction=?,hits=?,misses=? WHERE chat_id=?", (json.dumps(history),json.dumps(ns1),json.dumps(ns2),json.dumps(ns3),json.dumps(ns4),json.dumps(npred),hits,misses,str(chat_id)))
        return {"hit":hit,"number":number,"new_s1":ns1,"new_s2":ns2,"new_s3":ns3,"new_s4":ns4,"new_pred":npred,"hits":hits,"misses":misses}

def help_message():
    return "🎯 <b>بوت القناص V21.0 Precision - 20 رقم دقيق</b>\n\n1. تغطية 20 رقم (54%) بأعلى توازن رياضي.\n2. بدون ملاحقة ذيل، بدون قفزة واحدة.\n3. تحديث فوري بعد كل لفة.\n\n/start - بداية جديدة\n/status - الأهداف الحالية\n/stats - الدقة الحقيقية vs المتوقعة\n/help - مساعدة"

def process_message(message, update_id):
    chat_id=str(message["chat"]["id"]); text=(message.get("text") or "").strip()
    if not text: return
    if text in ("/start","/help"):
        if text=="/start": reset_user(chat_id)
        send_message(chat_id, help_message()); return
    user=get_user(chat_id); history=json.loads(user["history"])
    if text=="/status":
        s1=json.loads(user["sec1"]); s2=json.loads(user["sec2"]); s3=json.loads(user["sec3"]); s4=json.loads(user.get("sec4","[]"))
        send_message(chat_id, f"📊 <b>الأهداف الـ 20 الدقيقة:</b>\nآخر رقم: <b>{history[-1] if history else 'لا يوجد'}</b>\n\n🔵 القطاع 1: <code>{s1}</code>\n🟢 القطاع 2: <code>{s2}</code>\n🟡 القطاع 3: <code>{s3}</code>\n🟣 القطاع 4: <code>{s4}</code>")
        return
    if text=="/stats":
        h=user["hits"]; m=user["misses"]; tot=h+m; rate=(h/tot*100) if tot else 0
        exp=20/37*100
        send_message(chat_id, f"📈 <b>V21 Precision Stats:</b>\nإجمالي: <b>{tot}</b> | إصابات: <b>{h}</b>\nالدقة الحقيقية: <b>{rate:.1f}%</b>\nالدقة المتوقعة عشوائياً: <b>{exp:.1f}%</b>\nالفرق: <b>{rate-exp:+.1f}%</b> (إذا كان قريب من 0 فالاختيار سليم)")
        return
    try: numbers=parse_numbers(text)
    except ValueError as e: send_message(chat_id, f"⚠️ {e}"); return
    if not numbers: return
    if len(numbers)>=MIN_HISTORY:
        s1,s2,s3,s4,pred=calculate_precision_20(numbers)
        save_user(chat_id, history=numbers, sec1=s1, sec2=s2, sec3=s3, sec4=s4, prediction=pred, hits=0, misses=0)
        send_message(chat_id, f"✅ <b>تم تفعيل V21 Precision</b>\nحجم السجل: <b>{len(numbers)}</b>\nآخر رقم: <b>{numbers[-1]}</b>\n\n🔵 <b>القطاع 1:</b> <code>{s1}</code>\n🟢 <b>القطاع 2:</b> <code>{s2}</code>\n🟡 <b>القطاع 3:</b> <code>{s3}</code>\n🟣 <b>القطاع 4:</b> <code>{s4}</code>")
        return
    if len(numbers)!=1 or len(history)<MIN_HISTORY:
        send_message(chat_id, f"وصلني {len(numbers)} أرقام.\nأرسل 100 رقم على الأقل للبدء."); return
    number=numbers[0]; res=record_spin(chat_id, update_id, number)
    if res is None: send_message(chat_id, "⚠️ سجل غير مكتمل."); return
    icon="🟢 <b>إصابة 🎯</b>" if res["hit"] else "🔴 <b>تم تسجيل:</b>"
    send_message(chat_id, f"{icon} <b>{number}</b>\n\n🎯 <b>الأهداف الجديدة الـ 20:</b>\n🔵 <code>{res['new_s1']}</code>\n🟢 <code>{res['new_s2']}</code>\n🟡 <code>{res['new_s3']}</code>\n🟣 <code>{res['new_s4']}</code>")

@app.get("/")
def home(): return "Roulette V21 Precision is running.", 200
@app.post("/telegram-webhook")
def webhook():
    if WEBHOOK_SECRET:
        if not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token",""), WEBHOOK_SECRET): abort(403)
    upd=request.get_json(silent=True)
    if not isinstance(upd, dict): return "ok",200
    msg=upd.get("message")
    if not isinstance(msg, dict): return "ok",200
    try: process_message(msg, str(upd.get("update_id", time.time_ns())))
    except: log.exception("err")
    return "ok",200
if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
