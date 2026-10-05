#!/usr/bin/env python3
"""Walk-forward method scorecard (simplified). Equal-weight picks, 80% invested, same-close fills, no tech cap,
no costs in total_ret (cost_drag_10bps shows 10 bps per side). Evidence for Monday scorecards only; never trades."""
import json, warnings, sys
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from pathlib import Path
ROOT=str(Path(__file__).resolve().parents[1])
uni=json.load(open(f"{ROOT}/config/universe.json"))
eq=list(dict.fromkeys(uni["etfs"]+uni["mega_caps"]))
cr=["BTC-USD","ETH-USD","SOL-USD","AVAX-USD","LINK-USD"]
def px(t):
    d=yf.download(t,period="2y",auto_adjust=True,progress=False,threads=True)["Close"]
    return d.dropna(how="all").ffill()
def run(P, step, sel, n, invest, start_idx, buffer=None, hold_bench=None):
    rets=P.pct_change().fillna(0)
    dates=P.index[start_idx:]
    w=pd.Series(0.0,index=P.columns); nav=1.0; navs=[]; turn=0.0; held=[]
    for k,i in enumerate(range(start_idx,len(P))):
        if k>0:
            r=(w*rets.iloc[i]).sum(); nav*=1+r
            # drift weights
            w=w*(1+rets.iloc[i])/(1+r) if (1+r)!=0 else w
        if k%step==0:
            picks=sel(P,i,n,held,buffer)
            nw=pd.Series(0.0,index=P.columns)
            if picks: nw[picks]=invest/len(picks)
            turn+=(nw-w).abs().sum()/2; w=nw; held=picks
        navs.append(nav)
    s=pd.Series(navs,index=dates)
    dd=(s/s.cummax()-1).min()
    return s, turn
def r63(P,i,d=63):
    return P.iloc[i]/P.iloc[i-d]-1
def mom(P,i,n,held,buffer):
    r=r63(P,i); r12=P.iloc[i]/P.iloc[i-252]-1 if i>=252 else r*0
    r=r[(r12>-0.2)].dropna().sort_values(ascending=False)
    top=list(r.index[:n])
    if buffer:
        keep=[h for h in held if h in list(r.index[:buffer])]
        rest=[t for t in r.index if t not in keep]
        top=keep+rest[:n-len(keep)]
    return top
def mr(P,i,n,held,buffer):
    r=r63(P,i).dropna().sort_values(); return list(r.index[:n])
def ew(P,i,n,held,buffer): return list(P.columns)
def stats(name,s,turn,years):
    tot=s.iloc[-1]/s.iloc[0]-1; dd=(s/s.cummax()-1).min()
    return dict(method=name,total_ret=round(tot*100,2),max_dd=round(dd*100,2),turnover_x=round(turn,2),cost_drag_10bps=round(turn*2*0.001*100,2))
out={}
# equity: last ~252 trading days
P=px(eq); P=P.dropna(axis=1,thresh=int(len(P)*0.9))
si=len(P)-253
res=[]
for name,step,sel,buf in [("weekly_mom_top8",5,mom,None),("weekly_mom_top8_buffer10",5,mom,10),("monthly_mom_top8",21,mom,None),("weekly_meanrev_bottom8",5,mr,None)]:
    s,t=run(P,step,sel,8,0.8,si,buf); res.append(stats(name,s,t,1))
s,t=run(P,21,ew,0,0.8,si); res.append(stats("equal_weight_universe_80pct_monthly",s,t,1))
spy=P["SPY"].iloc[si:]; s=spy/spy.iloc[0]; res.append(stats("SPY_buy_hold_100pct",s,0,1))
s80=1+0.8*(s-1); res.append(dict(method="SPY_buy_hold_80pct_approx",total_ret=round((s.iloc[-1]-1)*80,2)))
out["equity_1y"]={"start":str(P.index[si].date()),"end":str(P.index[-1].date()),"results":res}
# equity last 13 weeks too
si2=len(P)-64; res2=[]
for name,step,sel,buf in [("weekly_mom_top8",5,mom,None),("weekly_mom_top8_buffer10",5,mom,10),("monthly_mom_top8",21,mom,None),("weekly_meanrev_bottom8",5,mr,None)]:
    s,t=run(P,step,sel,8,0.8,si2,buf); res2.append(stats(name,s,t,0.25))
spy=P["SPY"].iloc[si2:]; res2.append(stats("SPY_buy_hold_100pct",spy/spy.iloc[0],0,.25))
out["equity_3m"]={"start":str(P.index[si2].date()),"results":res2}
# crypto
C=px(cr); C=C.dropna()
ci=len(C)-366; resc=[]
for name,step,sel,n,buf in [("weekly_mom_top4",7,mom,4,None),("weekly_mom_top4_buffer",7,mom,4,5),("monthly_mom_top4",30,mom,4,None),("weekly_mom_top2",7,mom,2,None)]:
    s,t=run(C,step,sel,n,0.8,ci,buf); resc.append(stats(name,s,t,1))
s,t=run(C,30,ew,0,0.8,ci); resc.append(stats("equal_weight_5_80pct_monthly",s,t,1))
b=C["BTC-USD"].iloc[ci:]; resc.append(stats("BTC_buy_hold_100pct",b/b.iloc[0],0,1))
out["crypto_1y"]={"start":str(C.index[ci].date()),"end":str(C.index[-1].date()),"results":resc}
ci2=len(C)-92; resc2=[]
for name,step,sel,n,buf in [("weekly_mom_top4",7,mom,4,None),("monthly_mom_top4",30,mom,4,None)]:
    s,t=run(C,step,sel,n,0.8,ci2,buf); resc2.append(stats(name,s,t,.25))
b=C["BTC-USD"].iloc[ci2:]; resc2.append(stats("BTC_buy_hold_100pct",b/b.iloc[0],0,.25))
out["crypto_3m"]={"start":str(C.index[ci2].date()),"results":resc2}
# JPM / XLV / QQQ spot checks
out["spot"]={t:float(P[t].iloc[-1]) for t in ["JPM","XLV","QQQ","XLK","SPY"]}
import datetime as _dt
p=Path(ROOT)/"reports"/f"method_backtest_{_dt.date.today().isoformat()}.json"
p.write_text(json.dumps(out,indent=1))
print(json.dumps(out,indent=1))
print("wrote",p)
