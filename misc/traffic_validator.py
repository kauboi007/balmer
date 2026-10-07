import numpy as np
import json
from scipy import stats
import math
import random

def extr(path):
    metadata=None
    trace=None
    with open (path,'r',encoding='utf-8') as f:
            data=json.load(f)
            metadata=data['metadata']
            trace=data['trace']
    return metadata,trace

def validate(metadata,trace):
    gaps=np.diff(trace,prepend=0)
    n=len(gaps)
    mean_se=(1/metadata['lamda'])/np.sqrt(n)
    z_mean=abs(gaps.mean()-1/metadata['lamda'])/mean_se
    print("mean  n=",n,"observed=",gaps.mean(),"expected=",1/metadata['lamda'],"z=",z_mean,"pass" if z_mean<3 else "FAIL")
    pvalue=stats.kstest(gaps,'expon',args=(0,1/metadata['lamda'])).pvalue
    print("ks    p=",pvalue,"pass" if pvalue>0.01 else "FAIL")
    frac=(gaps>metadata['t']).mean()
    frac_se=np.sqrt(metadata['pval']*(1-metadata['pval'])/n)
    z_frac=abs(frac-metadata['pval'])/frac_se
    print("frac  observed=",frac,"expected=",metadata['pval'],"z=",z_frac,"pass" if z_frac<3 else "FAIL")

def repro_check(gen,lamda,duration):
    a=gen(lamda,duration,7)
    b=gen(lamda,duration,7)
    c=gen(lamda,duration,8)
    print("same seed equal      ",a==b)
    print("different seed differ",a!=c)
    with open("tmp_roundtrip.json","w",encoding="utf-8") as f:
        json.dump(a,f)
    with open("tmp_roundtrip.json","r",encoding="utf-8") as f:
        d=json.load(f)
    print("save/reload equal    ",a==d)

def long_trace_validator():
    def find(idle_timeout):
        a=[]
        for p in [0.5,0.9]:
            templam=-math.log(p)/idle_timeout
            a.append(templam)
        return a
    lam=find(5)
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
    p=[0.5,0.9]
    seed=7
    for l,pval in zip(lam,p):
        arr=possion_trace(l,100000/l,seed)
        metadata={"lamda":l,"pval":pval,"t":5}
        validate(metadata,arr)
        repro_check(possion_trace,l,1000/l)
        seed+=1
    
    


if(__name__=="__main__"):
    validate(*extr(r'traffic_generators/p05.json'))
    validate(*extr(r'traffic_generators/p09.json'))
    long_trace_validator()