import math
idle_timeout=10

#finding lamda
for p in [0.1,0.5,0.9]:
    templam=-math.log(p)/idle_timeout
    print("lamda for p={} is {}".format(p,templam))