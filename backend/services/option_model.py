"""Declared BSM estimates from actual option mids, never exchange-supplied Greeks."""
import math

def price(s,k,t,v,call):
    d1=(math.log(s/k)+v*v*t/2)/(v*math.sqrt(t));d2=d1-v*math.sqrt(t)
    n=lambda x:(1+math.erf(x/math.sqrt(2)))/2
    return s*n(d1)-k*n(d2) if call else k*n(-d2)-s*n(-d1)

def estimate(s,k,t,mid,call):
    if not all(math.isfinite(x) and x>0 for x in (s,k,t,mid)):raise ValueError('Invalid model input')
    intrinsic=max(0,s-k if call else k-s)
    if not intrinsic<mid<(s if call else k):raise ValueError('Mid outside model bounds')
    lo,hi=.00001,5.
    if price(s,k,t,hi,call)<mid:raise ValueError('IV outside solver range')
    for _ in range(90):
        v=(lo+hi)/2
        if price(s,k,t,v,call)<mid:lo=v
        else:hi=v
    v=(lo+hi)/2;d1=(math.log(s/k)+v*v*t/2)/(v*math.sqrt(t))
    pdf=math.exp(-d1*d1/2)/math.sqrt(2*math.pi);delta=(1+math.erf(d1/math.sqrt(2)))/2-(0 if call else 1)
    return dict(iv=v,delta=delta,gamma=pdf/(s*v*math.sqrt(t)),vega=s*pdf*math.sqrt(t)/100,theta=-s*pdf*v/(2*math.sqrt(t)*365))

def suitability(action,execution,contracts,quotes,spot,selected,now,hv):
    from datetime import datetime,time
    end=datetime.combine(selected,time(15,30),tzinfo=now.tzinfo)
    t=(end-now).total_seconds()/(365*86400)
    label='BSM estimates; r=0%, dividend yield=0%; mid quotes; expiry 15:30 IST. Not Kite/NSE Greeks.'
    if not hv or not math.isfinite(hv) or hv<=0:return None,label+' Daily realized volatility unavailable.'
    values=[]
    try:
        for leg in execution['legs']:
            c=contracts[(leg['strike'],leg['type'])];q=quotes['NFO:'+c['tradingsymbol']]
            bid=q['depth']['buy'][0]['price'];ask=q['depth']['sell'][0]['price']
            if not 0<bid<=ask:raise ValueError('Invalid book')
            values.append(estimate(spot,leg['strike'],t,(bid+ask)/2,leg['type']=='CE'))
        if not values:raise ValueError('No contracts')
    except (KeyError,IndexError,ValueError,TypeError,ZeroDivisionError):return None,label+' Valid live quote/model inputs unavailable.'
    # Transparent testing thresholds; not calibrated trade success probabilities.
    buy=action.endswith('BUY')
    ok=1<=t*365<=45 and all(.15<=abs(v['delta'])<=.85 and v['gamma']>0 and v['vega']>0 and (v['iv']<=1.5*hv if buy else v['iv']>=hv) for v in values)
    detail=label+f' HV20={hv:.2%}; testing gates: DTE 1–45, |delta| .15–.85, positive gamma/vega; '+('IV ≤ 1.5×HV.' if buy else 'IV ≥ HV.')
    detail+=' '+ '; '.join(f"{l['strike']}{l['type']}: IV {v['iv']:.2%}, delta {v['delta']:.3f}, gamma {v['gamma']:.6f}, vega/1% {v['vega']:.2f}, theta/day {v['theta']:.2f}" for l,v in zip(execution['legs'],values))
    return ok,detail
