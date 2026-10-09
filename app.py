from flask import Flask, request, jsonify
import collections
app = Flask(__name__)

NEIGHBORS = {0:[32,26],32:[0,15],15:[32,19],19:[15,4],4:[19,21],21:[4,2],2:[21,25],25:[2,17],17:[25,34],34:[17,6],6:[34,27],27:[6,13],13:[27,36],36:[13,11],11:[36,30],30:[11,8],8:[30,23],23:[8,10],10:[23,5],5:[10,24],24:[5,16],16:[24,33],33:[16,1],1:[33,20],20:[1,14],14:[20,31],31:[14,9],9:[31,22],22:[9,18],18:[22,29],29:[18,7],7:[29,28],28:[7,12],12:[28,35],35:[12,3],3:[35,26],26:[3,0]}

history=[]

def get_pred():
    if len(history)<20: return {"basic":[],"with_nb":[],"msg":f"دخل {len(history)}/20"}
    f15=collections.Counter(history[-15:]); gap={}
    for n in range(37):
        try: gap[n]=list(reversed(history)).index(n)
        except: gap[n]=99
    score={}
    for n in range(37):
        if gap[n]>=10: continue
        c10=history[-10:].count(n); c25=history[-25:].count(n)-c10; c50=history[-50:].count(n)-(c10+c25)
        s=(c10*3)+(c25*1)+(c50*0.2)
        if f15[n]>=2: s+=1.5
        if f15[n]>=3: s+=1.0
        if s>0: score[n]=s
    hot=sorted(score.items(),key=lambda x:x[1],reverse=True)[:5]
    basic=[n for n,_ in hot]
    with_nb=[]
    for num in basic[:3]:
        if gap[num]<10:
            with_nb.append(num)
            for nb in NEIGHBORS.get(num,[])[:1]:
                if gap[nb]<10: with_nb.append(nb)
        if len(with_nb)>=5: break
    return {"basic":basic[:5],"with_nb":with_nb[:5],"msg":"V22 Gap10 Live"}

@app.route('/')
def index():
    return "<h1>V22 Gap10 Live ✅</h1><p>go to /add</p>"

@app.route('/add', methods=['POST'])
def add():
    num=int(request.get_json().get('number')); history.append(num); return jsonify(get_pred())

@app.route('/reset', methods=['POST'])
def reset():
    history.clear(); return jsonify({"ok":True})

# هذا السطر هو الي ناقص عندك ويسبب Exited with status 1
# لازم يبقى
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
