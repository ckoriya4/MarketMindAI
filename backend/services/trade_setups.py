"""Four descriptive option setup scores. Missing factors are never fabricated."""
import math,time
from datetime import datetime
from threading import Lock
from fastapi import APIRouter,Query,HTTPException
from . import oi_signal as shared
from .option_chain import get_dynamic_option_chain
from .chart_service import get_chart_data
from .chart_indicators import enrich
from .option_model import suitability
router=APIRouter();lock=Lock();cache={}
ACTIONS=('CALL BUY','PUT BUY','CALL SELL','PUT SELL')

def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def rule(name,weight,passed,detail):return dict(name=name,weight=weight,passed=passed,detail=detail)

def score_card(action,checks,market_ready,execution,budget=None):
    known=sum(c['weight'] for c in checks if c['passed'] is not None)
    earned=sum(c['weight'] for c in checks if c['passed'] is True)
    excluded=[c['name'] for c in checks if c['passed'] is None]
    base_raw=earned/known*100 if known>0 else None
    base=round(base_raw,2) if base_raw is not None else None
    loss=execution.get('max_loss')
    valid_loss=numeric(loss) and loss>=0
    has_budget=numeric(budget) and budget>0
    fit=min(1,budget/loss) if has_budget and valid_loss and loss>0 else 1 if has_budget and valid_loss and loss==0 else None
    adjusted=round(base_raw*fit,2) if base_raw is not None and fit is not None else base
    reasons=[]
    if not market_ready:reasons.append('Stale/incomplete essential market inputs')
    if not known:reasons.append('No available checks')
    if not execution.get('valid'):reasons.append('Executable quote / hedge unavailable')
    if not valid_loss:reasons.append('Estimated maximum loss unavailable')
    if not has_budget:reasons.append('Set your maximum loss budget')
    elif valid_loss and loss>budget:reasons.append('Estimated maximum loss exceeds your limit; minimum one-lot trade is blocked')
    score=adjusted if market_ready else None
    ready=not reasons and score is not None and score>=80
    hard_block=bool(reasons)
    status='AVAILABLE CHECKS MATCHED — REVIEW' if ready else 'NO TRADE — LOSS LIMIT' if has_budget and valid_loss and loss>budget else 'NO TRADE' if hard_block or score is None or score<60 else 'WATCH ONLY'
    return dict(action=action,score=score,base_score=base if market_ready else None,
                risk_fit_pct=round(fit*100,2) if fit is not None else None,
                matched_weight=earned,known_weight=known,missing_weight=100-known,
                excluded_checks=excluded,partial=bool(excluded),checks=checks,status=status,
                color='green' if ready else 'yellow' if not hard_block and score is not None and score>=60 else 'red',
                blockers=reasons,execution=execution,profit_probability=None)


def oi_context(data,now):
    # Same chain-linking as the continuous OI graph, then final observation per minute.
    if data.get('weights')!=[1,1,1]:raise ValueError('Direct-sum OI data required; install direct-sum recorder update')
    if not data.get('points'):raise ValueError('OI history empty')
    minutes={};segment=None;offset_a=offset_b=last_a=last_b=base_a=base_b=0
    for p in sorted(data['points'],key=lambda p:p['time']):
        if p['segment']!=segment:
            offset_a,offset_b=last_a,last_b;base_a,base_b=p['put_change'],p['call_change'];segment=p['segment']
        last_a=offset_a+p['put_change']-base_a;last_b=offset_b+p['call_change']-base_b
        minute=int(p['time']//60*60);minutes[minute]=dict(time=minute,segment=segment,a=last_a,b=last_b)
    previous=None;sign=0;cross=0;cross_time=None
    for p in sorted(minutes.values(),key=lambda p:p['time']):
        if p['time']+60>now:continue
        if not previous or p['segment']!=previous['segment'] or p['time']-previous['time']>60:sign=0
        current=(p['a']>p['b'])-(p['a']<p['b'])
        if current and sign and current!=sign:cross=current;cross_time=p['time']
        if current:sign=current
        previous=p
    dominance=(last_a>last_b)-(last_a<last_b)
    if not previous or previous['segment']!=segment:cross=0;cross_time=None
    eligible=bool(cross_time is not None and 0<=now-(cross_time+60)<=300 and cross==dominance)
    return dict(direction=dominance,cross_direction=cross if eligible else 0,cross_time=cross_time,a=last_a,b=last_b)

def execution_plan(action,atm,step,contracts,quotes):
    typ='CE' if action.startswith('CALL') else 'PE';sell=action.endswith('SELL')
    sign=1 if typ=='CE' else -1
    strikes=[atm+sign*step,atm+sign*2*step] if sell else [atm]
    legs=[];spreads=[];net=0;lot=None;valid=True
    for index,strike in enumerate(strikes):
        contract=contracts.get((strike,typ))
        if not contract:return dict(valid=False,legs=[],max_loss=None,reason='Selected listed contract missing')
        side='SELL' if sell and index==0 else 'BUY';key='NFO:'+contract['tradingsymbol'];q=quotes.get(key,{})
        depth=q.get('depth',{});bid=(depth.get('buy') or [{}])[0].get('price');ask=(depth.get('sell') or [{}])[0].get('price')
        book_ok=numeric(bid) and numeric(ask) and 0<bid<=ask
        if not book_ok:valid=False;price=None;spreads.append(None)
        else:
            price=bid if side=='SELL' else ask;net+=price if side=='SELL' else -price
            spreads.append((ask-bid)/((ask+bid)/2)*100)
        size=contract.get('lot_size')
        if not numeric(size) or size<=0 or lot is not None and lot!=size:valid=False
        lot=size if lot is None else lot
        legs.append(dict(side=side,type=typ,strike=strike,symbol=contract['tradingsymbol'],price=price))
    if sell and not 0<net<step:valid=False
    max_loss=round((step-net)*lot if sell else -net*lot,2) if valid and lot else None
    return dict(valid=valid,legs=legs,lot_size=lot,max_loss=max_loss,max_loss_basis='One lot, full premium at risk for buys; defined-width hedge loss for sells. Excludes charges/slippage.',
                premium_credit=round(net,2) if sell and valid else None,spread_pct=max(spreads) if spreads and all(s is not None for s in spreads) else None)

@router.get('/api/signals/trade-setups')
def setups(expiry:str|None=Query(None),risk_budget:float|None=Query(None,gt=0)):
    with lock:
        key=(expiry,risk_budget);old=cache.get(key)
        if old and time.monotonic()-old[0]<10:return old[1]
        try:
            now=datetime.now(shared.IST);epoch=now.timestamp()
            chain=get_dynamic_option_chain('NIFTY',expiry,3)
            chart=get_chart_data(symbol='NIFTY_FUT',timeframe='5m',count=500,session=False)
            if chart.get('source')!='kite' or chart.get('symbol')!='NIFTY_FUT':raise HTTPException(503,'Actual futures candles required. Install the candle-indicator service update.')
            candles=[c for c in chart['candles'] if c['time']+300<=epoch]
            if len(candles)<35:raise HTTPException(503,'Insufficient completed candles for indicators')
            computed=enrich(dict(candles=candles,timeframe='5m',indicators={}),volume_supported=True)
            ind=computed['indicators'];last=candles[-1];prior=candles[-6:-1]
            market_ready=chain.get('status')=='fresh' and -5<=epoch-chain.get('spot_quote_at',0)<=90 and 0<=epoch-(last['time']+300)<=300 and datetime.fromtimestamp(last['time'],shared.IST).date()==now.date()
            oi=None;oi_error=None
            try:
                from .session_recorder import recorder
                oi_data=recorder.read('NIFTY',chain['selected_expiry'],3,0)
                if oi_data.get('status')!='fresh' or not -5<=epoch-oi_data.get('quote_time',0)<=30:raise ValueError('Direct-sum OI snapshots are stale')
                oi=oi_context(oi_data,epoch)
            except Exception:oi_error='Continuous direct-sum OI history unavailable/stale or incompatible'
            atm=chain['atm_strike'];rows=chain['strikes'];ladder=sorted(r['strike'] for r in rows);step=min(b-a for a,b in zip(ladder,ladder[1:]) if b>a)
            kite=shared.kite_client()
            selected=datetime.strptime(chain['selected_expiry'],'%d-%b-%Y').date()
            with shared.lock:listed=shared.instruments(kite,now.date())
            contracts={(float(r['strike']),r['instrument_type']):r for r in listed if r.get('name')=='NIFTY' and r.get('instrument_type') in ('CE','PE') and shared.expiry_date(r['expiry'])==selected}
            wanted={(atm,'CE'),(atm,'PE'),(atm+step,'CE'),(atm+2*step,'CE'),(atm-step,'PE'),(atm-2*step,'PE')}
            raw=kite.quote(['NFO:'+contracts[k]['tradingsymbol'] for k in wanted if k in contracts])
            if len(raw)!=len(wanted):market_ready=False
            for q in raw.values():
                try:
                    if not -5<=epoch-shared.provider_time(q.get('timestamp'))<=90:market_ready=False
                except Exception:market_ready=False
            hv=None
            try:
                daily=get_chart_data(symbol='NIFTY',timeframe='1D',count=60,session=False)
                closes=[c['close'] for c in daily['candles'] if datetime.fromtimestamp(c['time'],shared.IST).date()<now.date() and c['close']>0]
                if daily.get('source')=='kite' and len(closes)>=21:
                    returns=[math.log(b/a) for a,b in zip(closes[-21:-1],closes[-20:])]
                    mean=sum(returns)/20
                    hv=math.sqrt(sum((r-mean)**2 for r in returns)/19*252)
            except Exception:pass
            cards=[]
            for action in ACTIONS:
                bull=action in ('CALL BUY','PUT SELL');direction=1 if bull else -1
                price=last['close'];e9=ind['ema9'];e21=ind['ema21'];e50=ind['ema50'];vwap=ind['vwap'];rsi=ind['rsi14'];hist=ind['macd_histogram'];pcr=chain.get('pcr')
                execution=execution_plan(action,atm,step,contracts,raw)
                suitable,model_detail=suitability(action,execution,contracts,raw,chain.get('spot',chain.get('spot_price',0)),selected,now,hv)
                checks=[rule('Trend / EMA50',15,(price>e50 if bull else price<e50) if numeric(e50) else None,'Completed futures close vs EMA50'),
                    rule('Price structure breakout',10,price>max(c['high'] for c in prior) if bull else price<min(c['low'] for c in prior),'Close beyond prior five completed bars'),
                    rule('Session VWAP',10,(price>vwap if bull else price<vwap) if numeric(vwap) else None,'Same futures instrument and session volume'),
                    rule('EMA9/21 alignment',10,(price>e9>e21 if bull else price<e9<e21) if numeric(e9) and numeric(e21) else None,'Completed futures candle'),
                    rule('RSI14',5,(50<rsi<70 if bull else 30<rsi<50) if numeric(rsi) else None,'Illustrative momentum range'),
                    rule('MACD histogram',5,(hist>0 if bull else hist<0) if numeric(hist) else None,'Actual MACD12/26/9'),
                    rule('Direct-sum OI crossover',10,oi['cross_direction']==direction if oi else None,oi_error or 'Confirmed same-basket crossover within five minutes'),
                    rule('Direct-sum OI dominance',5,oi['direction']==direction if oi else None,oi_error or 'Same continuous A/B series as graph'),
                    rule('PCR',5,(pcr>1.1 if bull else pcr<.9) if numeric(pcr) else None,'Selected expiry and ±3 strike range; heuristic'),
                    rule('IV / Greeks / expiry suitability (model)',15,suitable,model_detail)]
                checks.extend([rule('Executable bid/ask',5,execution['valid'],'BUY at ask / SELL at bid; sell cards require protective hedge'),rule('Bid/ask spread ≤1%',5,execution.get('spread_pct')<=1 if numeric(execution.get('spread_pct')) else None,'Illustrative liquidity threshold; not execution guarantee')])
                cards.append(score_card(action,checks,market_ready,execution,risk_budget))
            result=dict(source='kite',status='fresh' if market_ready else 'stale',expiry=chain['selected_expiry'],quote_time=chain.get('spot_quote_at'),fetched_at=int(epoch),
                indicator_instrument=chart.get('instrument','NIFTY futures'),cards=cards,
                note='Base score = matched available points / available points ×100. Missing checks excluded, with coverage disclosed. Displayed score = base × min(1, loss budget / estimated one-lot max loss) when budget/loss available. Partial-check agreement, not profit probability; essential data and loss-limit gates still apply.')
            cache[key]=(time.monotonic(),result);return result
        except HTTPException:raise
        except Exception:raise HTTPException(503,'Trade setup inputs unavailable. Check actual Kite quotes/history and the candle-indicator update.') from None
