"""OI PRO: symmetric five-strike OI, three routes, completed15m /5m, alerts only."""
import json,logging,math,os,sqlite3,threading,time
from contextlib import asynccontextmanager,contextmanager
from datetime import datetime,time as clock,timezone
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel
from . import oi_signal as shared
from .chart_service import get_chart_data
from .chart_indicators import enrich
from .market_session import session_bounds
from .oi_pro_rules import summarize_oi,evaluate

router=APIRouter();DB=Path(__file__).resolve().parents[1]/'data'/'oi-pro-alerts.sqlite3';logger=logging.getLogger('uvicorn.error')
class InputUnavailable(ValueError):pass
def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def flag(name,default=False):return os.getenv(name,'true' if default else 'false').lower() in ('true','yes','1')
def settings():
    cfg=dict(start=os.getenv('DIRECT_START_IST','09:30'),end=os.getenv('DIRECT_END_IST','14:45'),poll_seconds=max(5,float(os.getenv('DIRECT_POLL_SECONDS','15'))),
        cooldown_seconds=int(os.getenv('DIRECT_COOLDOWN_SECONDS','900')),min_momentum=float(os.getenv('OI_PRO_MIN_MOMENTUM','0')),
        max_candle_atr=float(os.getenv('OI_PRO_MAX_CANDLE_ATR','1.5')),rr=float(os.getenv('OI_PRO_RR','2')),
        sl_buffer=float(os.getenv('OI_PRO_SL_BUFFER','0')),premium_filter=flag('OI_PRO_PREMIUM_FILTER',True),keep_ema_rsi=flag('OI_PRO_KEEP_EMA_RSI',False),
        risk_pct=float(os.getenv('OI_PRO_RISK_PCT','0.5')),capital=float(os.getenv('OI_PRO_CAPITAL','0') or 0),max_losses=int(os.getenv('OI_PRO_MAX_LOSSES','2')))
    if any(not numeric(cfg[k]) for k in ('poll_seconds','min_momentum','max_candle_atr','rr','sl_buffer','risk_pct','capital')):raise InputUnavailable('Non-finite configuration')
    if cfg['min_momentum']<0 or cfg['max_candle_atr']<=0 or cfg['rr']<2 or cfg['sl_buffer']<0 or not 0<cfg['risk_pct']<=1 or cfg['capital']<0 or cfg['max_losses']<1 or cfg['cooldown_seconds']<0:raise InputUnavailable('Invalid OI PRO parameters')
    clock.fromisoformat(cfg['start']);clock.fromisoformat(cfg['end']);return cfg

def in_window(now,cfg):return now.weekday()<5 and clock.fromisoformat(cfg['start'])<=now.time().replace(tzinfo=None)<=clock.fromisoformat(cfg['end'])

@contextmanager
def connection():
    DB.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(DB,timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE,time INTEGER,kind TEXT,action TEXT,direction TEXT,payload TEXT,telegram_status TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS outcomes (alert_id INTEGER PRIMARY KEY,result TEXT,closed_at INTEGER)')
    try:yield db;db.commit()
    finally:db.close()

def loss_streak(db,now):
    start=int(datetime.combine(now.date(),clock(0),tzinfo=shared.IST).timestamp())
    rows=db.execute("SELECT result FROM outcomes WHERE closed_at>=? AND closed_at<? AND result IN ('WIN','LOSS') ORDER BY closed_at DESC,alert_id DESC",(start,start+86400)).fetchall()
    count=0
    for (result,) in rows:
        if result!='LOSS':break
        count+=1
    return count

def save_event(db,key,event,now,cooldown):
    db.execute('BEGIN IMMEDIATE')
    if db.execute('SELECT 1 FROM alerts WHERE event_key=?',(key,)).fetchone():db.rollback();return None,'already_alerted'
    query="SELECT time FROM alerts WHERE action='BUY' ORDER BY id DESC LIMIT 1" if event['action']=='BUY' else "SELECT time FROM alerts WHERE action='PREPARE' AND direction=? ORDER BY id DESC LIMIT 1"
    last=db.execute(query,() if event['action']=='BUY' else (event['direction'],)).fetchone()
    if last and now-last[0]<cooldown:db.rollback();return None,'cooldown'
    cur=db.execute('INSERT INTO alerts(event_key,time,kind,action,direction,payload,telegram_status) VALUES (?,?,?,?,?,?,?)',(key,now,event['kind'],event['action'],event['direction'],json.dumps(event),'disabled'));db.commit()
    return cur.lastrowid,'alert'

def frame(chart,now,seconds):
    if chart.get('source')!='kite':raise InputUnavailable('Actual Kite candles required')
    bars=sorted([b for b in chart.get('candles',[]) if b['time']+seconds<=now.timestamp()],key=lambda b:b['time'])
    if len(bars)<55:raise InputUnavailable('Insufficient real indicator warm-up candles')
    opened=session_bounds(now.date())['open'];expected=opened+int((now.timestamp()-opened)//seconds)*seconds
    if bars[-1]['time']+seconds!=expected or datetime.fromtimestamp(bars[-1]['time'],shared.IST).date()!=now.date():raise InputUnavailable('Latest completed timeframe candle not yet available')
    return bars

def indicator_frame(chart,bars):
    value=enrich(dict(candles=bars,timeframe=chart['timeframe'],indicators={}),volume_supported=True)
    ind=value['indicators'];lookup={p['time']:p['value'] for p in value['vwap']}
    if len(bars)<2 or bars[-1]['time']-bars[-2]['time']!={'15m':900,'5m':300}[chart['timeframe']]:raise InputUnavailable('Gap in price confirmation bars')
    if any(not numeric(ind.get(k)) for k in ('vwap','ema50','rsi14','atr14')) or bars[-2]['time'] not in lookup:raise InputUnavailable('Actual volume/indicator values missing')
    return dict(bars=bars,last=bars[-1],previous=bars[-2],vwap=ind['vwap'],previous_vwap=lookup[bars[-2]['time']],ema50=ind['ema50'],rsi14=ind['rsi14'],atr14=ind['atr14'],instrument=chart.get('instrument','NIFTY futures'))

def message(event):
    title=f"EARLY {event['direction']} — PREPARE ONLY" if event['action']=='PREPARE' else f"{event['direction']} BUY — {event['kind']} RULE ALERT"
    text=f"{title}\nNIFTY · {event['strike']} {event['option_type']} · {event['expiry']}\nD {event['d']:+,.0f} · M {event['m']:+,.0f}\nSpot reference {event['spot_entry']:.2f}"
    if event.get('spot_sl') is not None:text+=f" · spot SL {event['spot_sl']:.2f} · target {event['spot_target']:.2f}"
    return text+f"\n{event['entry_type']}\n{event['risk_note']}\nRule alert only; no order placed; not profit probability."

def telegram_send(text):
    if not flag('DIRECT_TELEGRAM_ENABLED'):return 'disabled'
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip();chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
    if not token or not chat:return 'not_configured'
    try:
        import requests
        r=requests.post('https://api.telegram.org/bot'+token+'/sendMessage',json=dict(chat_id=chat,text=text),timeout=5);r.raise_for_status()
        return 'sent' if r.json().get('ok') else 'failed'
    except Exception:return 'failed'

class DirectEngine:
    def __init__(self):
        self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None;self.expiry=None;self.revision=0
        self.enabled=flag('DIRECT_ALERTS_ENABLED',True);self.state=dict(status='starting',reason='Waiting for OI PRO worker',candidate=None,checks={})
        self.analysis_key=None;self.analysis=None;self.option_cache={}
    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            self.stop_event.clear();self.thread=threading.Thread(target=self.run,daemon=True,name='oi-pro-worker');self.thread.start()
    def stop(self):self.stop_event.set()
    def configure(self,expiry,enabled=None):
        if expiry:
            parsed=None
            for fmt in ('%Y-%m-%d','%d-%b-%Y'):
                try:parsed=datetime.strptime(expiry,fmt).date().isoformat();break
                except ValueError:pass
            if parsed is None:raise HTTPException(422,'Invalid expiry')
            expiry=parsed
        with self.lock:
            changed=expiry!=self.expiry or enabled is not None and enabled!=self.enabled;self.expiry=expiry
            if enabled is not None:self.enabled=enabled
            if changed:self.revision+=1;self.state=dict(status='starting',reason='Expiry/settings changed; waiting for fresh analysis',candidate=None,checks={})
    def status(self):
        with self.lock:result=dict(self.state,enabled=self.enabled,expiry_setting=self.expiry,worker_running=bool(self.thread and self.thread.is_alive()))
        with connection() as db:
            rows=db.execute('SELECT id,time,payload,telegram_status FROM alerts ORDER BY id DESC LIMIT 5').fetchall()
            entries=db.execute("SELECT id,time,payload,telegram_status FROM alerts WHERE action='BUY' ORDER BY id DESC LIMIT 1").fetchone()
            result['loss_streak']=loss_streak(db,datetime.now(shared.IST))
        decode=lambda row:dict(json.loads(row[2]),id=row[0],created_at=row[1],telegram_status=row[3])
        result.update(events=[decode(row) for row in rows],latest_alert=decode(rows[0]) if rows else None,latest_entry=decode(entries) if entries else None,server_time=int(time.time()));return result
    def option_history(self,kite,contract,day,end):
        key=(day.isoformat(),contract['instrument_token']);old=self.option_cache.get(key,{})
        start=session_bounds(day)['open'] if not old else max(session_bounds(day)['open'],max(old)-1800)
        if self.stop_event.wait(1.05):raise InputUnavailable('Worker stopped')
        records=kite.historical_data(contract['instrument_token'],datetime.fromtimestamp(start,shared.IST),datetime.fromtimestamp(end,shared.IST),'15minute',oi=True)
        points=dict(old)
        for r in records:
            dt=r.get('date')
            if not isinstance(dt,datetime):continue
            if dt.tzinfo is None:dt=dt.replace(tzinfo=shared.IST)
            ts=int(dt.timestamp())
            if ts+900>end or datetime.fromtimestamp(ts,shared.IST).date()!=day:continue
            if numeric(r.get('oi')) and r['oi']>=0 and numeric(r.get('close')) and r['close']>0:points[ts]=dict(oi=r['oi'],close=r['close'])
        self.option_cache[key]=points;return points
    def analyze(self,kite,listed,expiry,index_bars,futures,now):
        options=[r for r in listed if r.get('name')=='NIFTY' and r.get('instrument_type') in ('CE','PE') and shared.expiry_date(r['expiry'])==expiry]
        paired={}
        for r in options:paired.setdefault(float(r['strike']),{})[r['instrument_type']]=r
        strikes=sorted(k for k,v in paired.items() if len(v)==2)
        if len(strikes)<5:raise InputUnavailable('Five paired listed strikes unavailable')
        nearest=lambda spot:min(strikes,key=lambda s:(abs(s-spot),-s))
        today=[b for b in index_bars if datetime.fromtimestamp(b['time'],shared.IST).date()==now.date()]
        atm=nearest(today[-1]['close']);i=strikes.index(atm)
        if i<2 or i+2>=len(strikes):raise InputUnavailable('ATM ±2 paired strike window unavailable')
        basket=strikes[i-2:i+3];run=[]
        for bar in reversed(today):
            if nearest(bar['close'])!=atm:break
            run.append(bar['time'])
        times=sorted(run);key=(now.date().isoformat(),expiry.isoformat(),tuple(basket),times[-1],times[0])
        if self.analysis_key==key:return self.analysis
        histories={};put=[];call=[]
        for strike in basket:
            for typ,keys in [('PE',put),('CE',call)]:
                contract=paired[strike][typ];name='NFO:'+contract['tradingsymbol'];keys.append(name)
                histories[name]=self.option_history(kite,contract,now.date(),today[-1]['time']+900)
        oi=summarize_oi(times,histories,put,call)
        if oi['snapshot_time']!=today[-1]['time']:raise InputUnavailable('Incomplete latest ten-contract OI snapshot')
        result=dict(oi=oi,atm=atm,strikes=basket,contracts=paired,expiry=expiry.isoformat())
        self.analysis_key=key;self.analysis=result;return result
    def tick(self,expiry_text,now,cfg):
        kite=shared.kite_client()
        with shared.lock:listed=shared.instruments(kite,now.date())
        expiries=sorted({shared.expiry_date(r['expiry']) for r in listed if r.get('name')=='NIFTY' and r.get('instrument_type') in ('CE','PE') and shared.expiry_date(r['expiry'])>=now.date()})
        expiry=datetime.strptime(expiry_text,'%Y-%m-%d').date() if expiry_text else expiries[0]
        if expiry not in expiries:raise InputUnavailable('Selected expiry is no longer listed')
        index=get_chart_data(symbol='NIFTY',timeframe='15m',count=1000,session=False)
        fut15=get_chart_data(symbol='NIFTY_FUT',timeframe='15m',count=1000,session=False)
        if index.get('symbol')!='NIFTY' or fut15.get('symbol')!='NIFTY_FUT' or index.get('timeframe')!='15m' or fut15.get('timeframe')!='15m':raise InputUnavailable('Instrument/timeframe mismatch')
        tnow=datetime.now(shared.IST);index_bars=frame(index,tnow,900);fut_bars=frame(fut15,tnow,900)
        if index_bars[-1]['time']!=fut_bars[-1]['time']:raise InputUnavailable('Index/futures15m candles not synchronized')
        analysis=self.analyze(kite,listed,expiry,index_bars,fut15,tnow)
        # Fetch again after historical basket download; never alert on a now-obsolete 15m bar.
        tnow=datetime.now(shared.IST);expected=session_bounds(tnow.date())['open']+int((tnow.timestamp()-session_bounds(tnow.date())['open'])//900)*900
        if analysis['oi']['snapshot_time']+900!=expected:raise InputUnavailable('A new15m candle completed during analysis; waiting for refresh')
        trend=indicator_frame(fut15,fut_bars)
        fut5=get_chart_data(symbol='NIFTY_FUT',timeframe='5m',count=1000,session=False)
        if fut5.get('symbol')!='NIFTY_FUT' or fut5.get('timeframe')!='5m':raise InputUnavailable('5m futures source mismatch')
        entry_bars=frame(fut5,datetime.now(shared.IST),300);entry=indicator_frame(fut5,entry_bars)
        if entry_bars[-1]['time']+300<analysis['oi']['snapshot_time']+900:raise InputUnavailable('5m entry confirmation precedes15m setup')
        result=evaluate(analysis['oi'],trend,entry,cfg)
        q=kite.quote(['NSE:NIFTY 50']).get('NSE:NIFTY 50',{});spot=q.get('last_price');qt=shared.provider_time(q.get('timestamp'))
        if not numeric(spot) or spot<=0 or not -5<=time.time()-qt<=30:raise InputUnavailable('Index quote stale')
        candidate=result['candidate']
        with connection() as db:streak=loss_streak(db,datetime.now(shared.IST))
        state=dict(result,status='waiting',parameters=cfg,oi={k:v for k,v in analysis['oi'].items() if k!='rows'},spot=spot,atm=analysis['atm'],strikes=analysis['strikes'],expiry=analysis['expiry'],quote_time=qt,
            indicators=dict(instrument=entry['instrument'],price=entry['last']['close'],vwap=entry['vwap'],ema50=entry['ema50'],rsi14=entry['rsi14']),loss_streak=streak,oi_bar_close=analysis['oi']['snapshot_time']+900,entry_bar_close=entry['last']['time']+300)
        if not candidate:return state,None
        if candidate['action']=='BUY' and streak>=cfg['max_losses']:state.update(status='blocked',candidate=None,reason='Paper-log consecutive-loss limit reached for today');return state,None
        all_strikes=sorted(analysis['contracts']);trade_atm=min(all_strikes,key=lambda s:(abs(s-spot),-s))
        if trade_atm not in analysis['strikes']:state.update(candidate=None,reason='Spot moved outside frozen analysis basket; waiting for new15m ATM window');return state,None
        typ='CE' if candidate['direction']=='CALL' else 'PE';contract=analysis['contracts'][trade_atm][typ]
        option=kite.quote(['NFO:'+contract['tradingsymbol']]).get('NFO:'+contract['tradingsymbol'],{});ot=shared.provider_time(option.get('timestamp'));ltp=option.get('last_price')
        if not numeric(ltp) or ltp<=0 or not -5<=time.time()-min(qt,ot)<=30:raise InputUnavailable('Selected option quote stale/unavailable')
        sl=target=None;risk_note='PREPARE warning only; no entry/position size.';risk={}
        if candidate['action']=='BUY':
            sign=1 if candidate['direction']=='CALL' else -1
            sl=index_bars[-1]['low']-cfg['sl_buffer'] if sign>0 else index_bars[-1]['high']+cfg['sl_buffer']
            distance=(spot-sl)*sign
            if distance<=0:state.update(candidate=None,reason='Current index spot already beyond structural invalidation');return state,None
            target=spot+sign*cfg['rr']*distance
            if min(sl,target)<=0:raise InputUnavailable('Invalid structural spot levels')
            ask=(option.get('depth',{}).get('sell') or [{}])[0].get('price');lot=contract.get('lot_size')
            if not numeric(ask) or ask<=0 or not numeric(lot) or lot<=0:state.update(candidate=None,reason='Executable ask/lot size unavailable');return state,None
            full_premium=ask*lot;budget=cfg['capital']*cfg['risk_pct']/100 if cfg['capital']>0 else None
            risk=dict(one_lot_full_premium=round(full_premium,2),budget=round(budget,2) if budget is not None else None)
            if budget is not None and full_premium>budget:state.update(status='blocked',candidate=None,reason='One-lot full-premium exposure exceeds configured capital risk budget',risk=risk);return state,None
            risk_note='One-lot full-premium risk estimate fits configured budget; excludes fees/slippage.' if budget is not None else 'Capital risk budget NOT configured; position risk not approved.'
        final_now=datetime.now(shared.IST)
        opened=session_bounds(final_now.date())['open']
        if state['oi_bar_close']!=opened+int((final_now.timestamp()-opened)//900)*900 or state['entry_bar_close']!=opened+int((final_now.timestamp()-opened)//300)*300:raise InputUnavailable('A new confirmation candle completed before alert; waiting for refresh')
        if not in_window(final_now,cfg) or time.time()-min(qt,ot)>30:raise InputUnavailable('Window ended or input aged before alert')
        event=dict(candidate,strike=trade_atm,option_type=typ,option_symbol=contract['tradingsymbol'],expiry=analysis['expiry'],spot_entry=spot,spot_sl=round(sl,2) if sl is not None else None,spot_target=round(target,2) if target is not None else None,
            option_ltp=ltp,d=analysis['oi']['d'],m=analysis['oi']['m'],baseline_time=analysis['oi']['baseline_time'],strikes=analysis['strikes'],oi_bar_close=state['oi_bar_close'],entry_bar_close=state['entry_bar_close'],risk_note=risk_note,risk=risk,quote_time=min(qt,ot))
        return state,event
    def run(self):
        while not self.stop_event.is_set():
            try:
                cfg=settings();now=datetime.now(shared.IST)
                with self.lock:expiry=self.expiry;revision=self.revision;enabled=self.enabled
                state=dict(status='disabled' if not enabled else 'outside_window',candidate=None,checks={},reason='Engine disabled' if not enabled else 'Outside configured IST alert window',parameters=cfg);event=None
                if enabled and in_window(now,cfg):state,event=self.tick(expiry,now,cfg)
                with self.lock:
                    if revision!=self.revision or self.stop_event.is_set():continue
                    if event:
                        key=f"{now.date()}:{event['expiry']}:{event['strikes']}:{event['kind']}:{event['direction']}:{event['oi_bar_close']}"+(f":{event['entry_bar_close']}" if event['action']=='BUY' else '')
                        with connection() as db:identifier,status=save_event(db,key,event,int(time.time()),cfg['cooldown_seconds'])
                        state['status']=status
                        if identifier:event['id']=identifier
                        else:event=None
                    self.state=dict(state,evaluated_at=int(time.time()))
                if event:
                    logger.info(message(event));delivery=telegram_send(message(event))
                    with connection() as db:db.execute('UPDATE alerts SET telegram_status=? WHERE id=?',(delivery,event['id']))
            except Exception as error:
                reason=str(error) if isinstance(error,(InputUnavailable,ValueError)) else 'OI PRO data unavailable; check Kite token/history/OI access and current expiry'
                # Do not expose raw provider errors/URLs/secrets.
                if not isinstance(error,InputUnavailable) and not (isinstance(error,ValueError) and reason in ('No complete same-basket 15m OI records',)):reason='OI PRO data unavailable; waiting for complete real data'
                with self.lock:self.state=dict(status='unavailable',candidate=None,checks={},reason=reason,evaluated_at=int(time.time()))
            try:wait=max(5,float(os.getenv('DIRECT_POLL_SECONDS','15')))
            except ValueError:wait=15
            self.stop_event.wait(wait)

engine=DirectEngine()
class Config(BaseModel):
    expiry:str|None=None
    enabled:bool|None=None
class Outcome(BaseModel):
    alert_id:int
    result:str
@router.get('/api/signals/direct')
def status():return engine.status()
@router.post('/api/signals/direct/config')
def configure(payload:Config):engine.configure(payload.expiry,payload.enabled);return dict(status='updated')
@router.post('/api/signals/direct/outcome')
def record_outcome(payload:Outcome):
    result=payload.result.upper()
    if result not in ('WIN','LOSS','FLAT'):raise HTTPException(422,'Result must be WIN, LOSS or FLAT')
    with connection() as db:
        row=db.execute('SELECT action FROM alerts WHERE id=?',(payload.alert_id,)).fetchone()
        if not row or row[0]!='BUY':raise HTTPException(422,'Only an existing BUY alert can have a paper outcome')
        db.execute('INSERT INTO outcomes VALUES (?,?,?) ON CONFLICT(alert_id) DO UPDATE SET result=excluded.result',(payload.alert_id,result,int(time.time())))
    return dict(status='paper outcome recorded; no broker order modified')

def install_direct_alerts(app):
    if getattr(app.state,'direct_alerts_installed',False):return
    previous=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with previous(application):
            engine.start()
            try:yield
            finally:engine.stop()
    app.router.lifespan_context=lifespan;app.include_router(router);app.state.direct_alerts_installed=True
