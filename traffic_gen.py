import random
import math
import json

seed=7 #random seed
idle_timeout=30 #the server goes cold after 30 seconds of no requests
trace_duration_exp=10000 #how long the traffic shld keep generating

def possion_trace(lamda,trace_duration,seed):
    reqs=[]
    rng=random.Random(seed)
    s=0
    while(s<trace_duration):
        u=rng.uniform(0,1)
        if(u==0):
            continue
        t=-math.log(u)/lamda
        reqs.append(t+s)
        s+=t
    return reqs[:len(reqs)-1]

lamda=[0.07675283643313485,0.023104906018664842,0.0035120171885942093]
json_file_names=["low_res.json","medi_res.json","high_res.json"]

for i,j in zip(lamda,json_file_names):
    file=open(j,"w",encoding="utf-8")
    json.dump(possion_trace(i,trace_duration_exp,seed),file)
    file.close()
