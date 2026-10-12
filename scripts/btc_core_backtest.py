import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf, json
cr=["BTC-USD","ETH-USD","SOL-USD","AVAX-USD","LINK-USD"]
C=yf.download(cr,period="2y",auto_adjust=True,progress=False)["Close"].dropna().ffill()
rets=C.pct_change().fillna(0)
def weights(i,core,n,held,buffer=None):
    w=pd.Series(0.0,index=C.columns)
    sat=0.8-core
    if core>0: w["BTC-USD"]=core
    r=C.iloc[i]/C.iloc[i-63]-1; r12=C.iloc[i]/C.iloc[i-252]-1 if i>=252 else r*0
    pool=[t for t in C.columns if not (core>0 and t=="BTC-USD")]
    r=r[pool]; r=r[r12[pool]>-0.2].sort_values(ascending=False)
    picks=list(r.index[:n])
    if picks and sat>0: w[picks]+=sat/len(picks)
    return w,picks
def run(start,core,n,step=7):
    w=pd.Series(0.0,index=C.columns); nav=1; navs=[]; turn=0; held=[]
    for k,i in enumerate(range(start,len(C))):
        if k>0:
            r=(w*rets.iloc[i]).sum(); nav*=1+r; w=w*(1+rets.iloc[i])/(1+r)
        if k%step==0:
            nw,held=weights(i,core,n,held); turn+=(nw-w).abs().sum()/2; w=nw
        navs.append(nav)
    s=pd.Series(navs,index=C.index[start:])
    return round((s.iloc[-1]-1)*100,2), round(((s/s.cummax())-1).min()*100,2), round(turn,2)
out={}
for lab,days in [("1y",366),("6m",183),("3m",92)]:
    st=len(C)-days; rows={}
    rows["mom_top4_80 (current)"]=run(st,0,4)
    for core in (0.4,0.5,0.6):
        rows[f"BTC core {int(core*100)}% + mom top2 rest"]=run(st,core,2)
        rows[f"BTC core {int(core*100)}% + mom top3 rest"]=run(st,core,3)
    rows["BTC 80% hold"]=run(st,0.8,0)
    b=C["BTC-USD"].iloc[st:]; rows["BTC 100% hold"]=(round((b.iloc[-1]/b.iloc[0]-1)*100,2),round(((b/b.cummax())-1).min()*100,2),0)
    out[lab]={"start":str(C.index[st].date()),"rows":rows}
    print(lab,C.index[st].date())
    for k,v in rows.items(): print(f"   {k:34s} ret {v[0]:7.2f}% mdd {v[1]:7.2f}% turn {v[2]}")
json.dump(out,open("results.json","w"),indent=1)
