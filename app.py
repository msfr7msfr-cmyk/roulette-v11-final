# V22 - Gap10 + TimeWeight
def analyze(history):
    if len(history) < 20:
        return f"انتظر {20-len(history)} لفة"

    last_15 = history[-15:]
    last_50 = history[-50:]
    from collections import Counter
    f15 = Counter(last_15)

    gap = {}
    for n in range(37):
        try: gap[n] = list(reversed(history)).index(n)
        except: gap[n] = 99

    score = {}
    for n in range(37):
        if gap[n] >= 10: # <--- هذا الجديد Gap10
            continue
        c10 = history[-10:].count(n)
        c25 = history[-25:].count(n) - c10
        c50 = last_50.count(n) - (c10+c25)
        s = (c10*3)+(c25*1)+(c50*0.2) # <--- وزن زمني
        if f15[n] >= 2: s+=1.5
        if f15[n] >= 3: s+=1.0
        if s>0: score[n]=s

    hot5 = sorted(score.items(), key=lambda x:x[1], reverse=True)[:5]
    basic = [n for n,_ in hot5]

    # مع الجيران
    with_nb=[]
    for num in basic[:3]:
        if gap[num]<10:
            with_nb.append(num)
            nb = NEIGHBORS.get(num,[])[:1]
            for b in nb:
                if gap[b]<10: with_nb.append(b)
        if len(with_nb)>=5: break

    return basic, with_nb[:5]
