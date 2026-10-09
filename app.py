from flask import Flask, request, jsonify
import collections

app = Flask(__name__)

NEIGHBORS = {
    0:[32,26], 32:[0,15], 15:[32,19], 19:[15,4], 4:[19,21], 21:[4,2], 2:[21,25],
    25:[2,17], 17:[25,34], 34:[17,6], 6:[34,27], 27:[6,13], 13:[27,36], 36:[13,11],
    11:[36,30], 30:[11,8], 8:[30,23], 23:[8,10], 10:[23,5], 5:[10,24], 24:[5,16],
    16:[24,33], 33:[16,1], 1:[33,20], 20:[1,14], 14:[20,31], 31:[14,9], 9:[31,22],
    22:[9,18], 18:[22,29], 29:[18,7], 7:[29,28], 28:[7,12], 12:[28,35], 35:[12,3],
    3:[35,26], 26:[3,0]
}

VOISINS = [22,18,29,7,28,12,35,3,26,0,32,15,19,4,21,2,25]
TIERS = [27,13,36,11,30,8,23,10,5,24,16,33]

history = []

def get_pred():
    if len(history) < 20:
        return {"basic": [], "with_nb": [], "msg": f"دخل {len(history)}/20 - انتظر {20-len(history)}"}
    last_15 = history[-15:]
    last_50 = history[-50:]
    f15 = collections.Counter(last_15)
    gap = {}
    for n in range(37):
        try: gap[n] = list(reversed(history)).index(n)
        except: gap[n] = 99
    score = {}
    for n in range(37):
        if gap[n] >= 10: continue
        c10 = history[-10:].count(n)
        c25 = history[-25:].count(n) - c10
        c50 = last_50.count(n) - (c10+c25)
        s = (c10*3)+(c25*1)+(c50*0.2)
        if f15[n] >= 2: s+=1.5
        if f15[n] >= 3: s+=1.0
        if s>0: score[n]=s
    hot = sorted(score.items(), key=lambda x:x[1], reverse=True)[:5]
    basic = [n for n,_ in hot]
    with_nb=[]
    for num in basic[:3]:
        if gap[num]<10:
            with_nb.append(num)
            for nb in NEIGHBORS.get(num,[])[:1]:
                if gap[nb]<10: with_nb.append(nb)
        if len(with_nb)>=5: break
    msg = "✅ العب 4 لفات ثابت" if len([x for x in hot if x[1]>=2])>=2 else "⚠️ انتظار"
    return {"basic": basic[:5], "with_nb": with_nb[:5], "msg": msg, "last": history[-1], "gap10": True}

@app.route('/')
def index():
    return """
<!DOCTYPE html><html dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>V22 Gap10</title><style>
body{background:#111;color:#fff;font-family:Arial;text-align:center;padding:20px}
button{padding:12px 18px;margin:5px;font-size:16px;border-radius:8px;border:none}
.num{background:#222;color:#fff}.add{background:#0a0;color:#fff;width:90%}
.box{background:#222;padding:15px;margin:10px;border-radius:10px}
</style></head><body>
<h2>🧠 V22 - Gap10 + TimeWeight</h2>
<div class="box" id="pred">دخل ارقام...</div>
<div id="nums"></div>
<button class="add" onclick="addLast()">➕ اضافة اخر رقم</button>
<button onclick="reset()">🔄 تصفير</button>
<script>
let sel=null;
let hist = JSON.parse(localStorage.getItem('h')||'[]');
function renderNums(){
 let c=document.getElementById('nums'); c.innerHTML='';
 for(let i=0;i<37;i++){
  let b=document.createElement('button'); b.className='num'; b.textContent=i;
  b.onclick=()=>{sel=i; document.querySelectorAll('.num').forEach(x=>x.style.border=''); b.style.border='2px solid #0f0'};
  c.appendChild(b);
 }
}
async function addLast(){
 if(sel===null){alert('اختار رقم');return}
 let r=await fetch('/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({number:sel})});
 let j=await r.json();
 hist.push(sel); localStorage.setItem('h',JSON.stringify(hist));
 document.getElementById('pred').innerHTML=`اخر:${j.last||sel}<br>اساسي:${j.basic}<br>مع جيران:${j.with_nb}<br>${j.msg}`;
 sel=null; document.querySelectorAll('.num').forEach(x=>x.style.border='');
}
async function reset(){await fetch('/reset',{method:'POST'}); hist=[]; localStorage.setItem('h','[]'); document.getElementById('pred').innerHTML='تم التصفير - دخل 20 رقم';}
renderNums();
if(hist.length>0){fetch('/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({history:hist})})}
</script></body></html>
    """

@app.route('/add', methods=['POST'])
def add():
    num = int(request.get_json().get('number'))
    history.append(num)
    return jsonify(get_pred())

@app.route('/load', methods=['POST'])
def load():
    global history
    history = request.get_json().get('history', [])[-100:]
    return jsonify(get_pred())

@app.route('/reset', methods=['POST'])
def reset():
    history.clear()
    return jsonify({"ok": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
