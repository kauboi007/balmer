*notes*

- traffic generators
  1. poisson - p(cold)=e^(l*t) set this to a number u belonging to [0,1) then solve for t
  2. bursty  - swtich between 2 states of ON and OFF where ON lasts for DON and has possion of lambda and quiet for DOFF period of time.. sweep across some values where DOFF near , above and below t
  3. peroidic with jitters - gap=period + noise => noise = gaussian with std=p+n(0,sigma^2)
