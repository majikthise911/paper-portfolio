import warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf, json
cr=["BTC-USD","ETH-USD","SOL-USD","AVAX-USD","LINK-USD"]
C=yf.download(cr,period="2y",auto_adjust=True,progress=False)["Close"].dropna().ffill()
R=C.pct_change().fillna(0)
def wts(i,core,n,rs):
    w=pd.Series(0.0,index=C.columns); w["BTC-USD"]=core
    r=C.iloc[i]/C.iloc[i-63]-1; r12=C.iloc[i]/C.iloc[i-252]-1
    pool=[t for t in C.columns if t!="BTC-USD"]
    rr=r[pool][r12[pool]>-0.2].sort_values(ascending=False)
    picks=list(rr.index[:n])
    for t in picks:
        if rs and r[t]<=r["BTC-USD"]: w["BTC-USD"]+=0.15
        else: w[t]+=0.15
    for _ in range(n-len(picks)): w["BTC-USD"]+=0.15 if rs else 0
    return w
def run(st,core,n,rs):
    w=pd.Series(0.0,index=C.columns); nav=1; navs=[]; turn=0
    for k,i in enumerate(range(st,len(C))):
        if k>0:
            r=(w*R.iloc[i]).sum(); nav*=1+r; w=w*(1+R.iloc[i])/(1+r)
        if k%7==0:
            nw=wts(i,core,n,rs); turn+=(nw-w).abs().sum()/2; w=nw
        navs.append(nav)
    s=pd.Series(navs,index=C.index[st:])
    return round((s.iloc[-1]-1)*100,2), round((s/s.cummax()-1).min()*100,2), round(turn,2)
out={}
for lab,d in [("1y",366),("6m",183),("3m",92)]:
    st=len(C)-d; rows={}
    rows["v2 BTC50 + top2 (live)"]=run(st,0.5,2,False)
    rows["v2 + RS-vs-BTC filter"]=run(st,0.5,2,True)
    rows["BTC65 + top1"]=run(st,0.65,1,False)
    rows["BTC65 + top1 RS"]=run(st,0.65,1,True)
    rows["BTC80 hold"]=run(st,0.8,0,False)
    b=C["BTC-USD"].iloc[st:]; rows["BTC100"]=(round((b.iloc[-1]/b.iloc[0]-1)*100,2),round((b/b.cummax()-1).min()*100,2),0)
    out[lab]={"start":str(C.index[st].date()),"rows":rows}
    print(lab,C.index[st].date())
    for k,v in rows.items(): print(f"  {k:26s} ret {v[0]:7.2f} mdd {v[1]:7.2f} turn {v[2]}")
i=len(C)-1; r=C.iloc[i]/C.iloc[i-63]-1; print("63d now",r.round(4).to_dict())
json.dump(out,open("reports/crypto_rs_filter_backtest_2026-10-26.json","w"),indent=1)
