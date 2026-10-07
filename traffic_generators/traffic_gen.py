import random
import math
import json
seed=7 #random seed
idle_timeout=5 

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

def find(idle_timeout):
    a=[]
    for p in [0.5,0.9]:
        templam=-math.log(p)/idle_timeout
        a.append(templam)
    return a

pval=[0.5,0.9]
lamda=find(idle_timeout)
json_file_names=["p05.json","p09.json"]
duration=1800

if(__name__=="__main__"):
    for i,j,z in zip(lamda,json_file_names,pval):
        file=open(j,"w",encoding="utf-8")
        json.dump({"metadata":{"lamda":i,"duration":duration,"pval":z,"t":idle_timeout,"seed":seed},
                "trace":possion_trace(i,duration,seed)},file)
        file.close()
        seed+=1
