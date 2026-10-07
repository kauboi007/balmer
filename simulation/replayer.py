import json
import time
import numpy as np

def load_trace(path,n):
    data=None
    with open(path,"r") as f:
        data=json.load(f)
        data=data['trace'][:n]
    return data

def run_schedule(arrivals,k):
    t0=time.monotonic()
    rows=[]
    for x in arrivals:
        sr=x/k
        wait=t0+sr-time.monotonic()
        if(wait>0):
            time.sleep(wait)
        now=time.monotonic()
        rows.append((sr,now-t0,now))
    return rows

def report(rows):
    lag=[]
    for i in rows:
        lag.append((rows[i][1]-rows[i][0])*1000)
    mean=np.mean(lag)
    p95=np.percentile(lag,95)
    maxlag=max(lag)
    print(mean)
    print(p95)
    print(maxlag)
