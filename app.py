import collections

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
ORPHELINS = [1,20,14,31,9,17,34,6]

def analyze(history):
    if len(history) < 20:
        return "انتظر 20 لفة"
    last_15 = history[-15:]
    last_50 = history[-50:]
    f15 = collections.Counter(last_15)
    gap = {}
    for n in range(37):
        try:
            gap[n] = list(reversed(history)).index(n)
        except:
            gap[n] = 99

    score50 = {}
    for n in range(37):
        if gap[n] >= 10:
            continue
        last10 = history[-10:]
        last25 = history[-25:]
        c10 = last10.count(n)
        c25 = last25.count(n) - c10
        c50 = last_50.count(n) - (c10+c25)
        count = (c10 * 3) + (c25 * 1) + (c50 * 0.2)
        if f15[n] >= 2:
            count += 1.5
        if f15[n] >= 3:
            count += 1.0
        if count > 0:
            score50[n] = count

    hot5 = sorted(score50.items(), key=lambda x: x[1], reverse=True)[:5]
    basic = [n for n,_ in hot5]
    with_neighbors = []
    for num in basic[:3]:
        if gap[num] < 10:
            with_neighbors.append(num)
            for nb in NEIGHBORS.get(num, [])[:1]:
                if gap[nb] < 10:
                    with_neighbors.append(nb)
        if len(with_neighbors) >= 5:
            break
    with_neighbors = with_neighbors[:5]

    last20 = history[-20:]
    v = sum(1 for x in last20 if x in VOISINS)
    t = sum(1 for x in last20 if x in TIERS)
    sector = f"Voisins({v}/20)" if v>=t else f"Tiers({t}/20)"

    hot_str = ", ".join([f"{n}" for n,_ in hot5])
    return f"V22 Gap10 | اخر:{history[-1]} | قطاع:{sector} | اساسي:{basic} | جيران:{with_neighbors} | اخر10:{history[-10:]}"
