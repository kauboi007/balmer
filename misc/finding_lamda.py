import math
#finding lamda
def find(idle_timeout):
    a=[]
    for p in [0.5,0.9]:
        templam=-math.log(p)/idle_timeout
        a.append(templam)
        return a

