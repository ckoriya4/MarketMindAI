"""Shared background stock-option OI snapshots. Cash volume is never option OI."""
import csv,io,math,time,threading,hashlib
from datetime import datetime,timezone
from pathlib import Path
import requests
from kiteconnect.exceptions import TokenException
from . import oi_signal as shared

BASE=Path(__file__).resolve().parents[1]
_provider=None

def configure_constituents(provider):
    global _provider
    _provider=provider

def members():
    if _provider:return _provider()
    path=BASE/'nifty50.csv'
    if path.exists():text=path.read_text(encoding='utf-8-sig')
    else:
        r=requests.get('https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv',headers={'User-Agent':'Mozilla/5.0'},timeout=15);r.raise_for_status();text=r.content.decode('utf-8-sig')
    rows=[dict(symbol=r['Symbol'].strip(),sector=r.get('Industry','').strip()) for r in csv.DictReader(io.StringIO(text))]
    if len(rows)!=50 or len({r['symbol'] for r in rows})!=50:raise ValueError('Official CSV must contain 50 unique symbols')
    return rows

def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def fmt(v):return '—' if v is None else f'{v/1e7:.2f}Cr' if abs(v)>=1e7 else f'{v/1e5:.1f}L' if abs(v)>=1e5 else f'{v:,.0f}'
def stamp(q):
    try:return shared.provider_time(q.get('timestamp'))
    except Exception:return None

def universe(stocks,instruments,today):
    names={s['symbol'] for s in stocks};all_rows={s:[] for s in names}
    for r in instruments:
        if r.get('name') in names and r.get('instrument_type') in ('CE','PE') and shared.expiry_date(r['expiry'])>=today:
            all_rows[r['name']].append(r)
    expiries=[{shared.expiry_date(r['expiry']) for r in rows} for rows in all_rows.values() if rows]
    common=set.intersection(*expiries) if expiries else set()
    if not common:raise ValueError('No common listed expiry among supported stock options')
    expiry=min(common)
    return expiry,{s:[r for r in rows if shared.expiry_date(r['expiry'])==expiry] for s,rows in all_rows.items()}

def aggregate(stocks,contracts,quotes,now):
    result={}
    for stock in stocks:
        symbol=stock['symbol'];rows=contracts.get(symbol,[]);value=dict(sector=stock['sector'],contracts=len(rows))
        all_times=[]
        for typ,key in [('CE','call'),('PE','put')]:
            selected=[r for r in rows if r['instrument_type']==typ];total=0;times=[];missing=0;unknown_time=0;details=[]
            for r in selected:
                q=quotes.get('NFO:'+r['tradingsymbol'],{});oi=q.get('oi');ts=stamp(q)
                if not numeric(oi) or oi<0 or (ts is not None and ts>now+5):
                    missing+=1;details.append(dict(contract=r['tradingsymbol'],reason='missing/invalid OI' if not numeric(oi) or oi<0 else 'future timestamp'));continue
                total+=int(oi)
                if ts is None:unknown_time+=1;details.append(dict(contract=r['tradingsymbol'],reason='OI present; timestamp unavailable'))
                else:times.append(ts)
            value[key]=total if selected and not missing else None
            value[key+'_missing']=missing if selected else 1
            value[key+'_contracts']=len(selected)
            value[key+'_timestamp_missing']=unknown_time
            value[key+'_diagnostics']=details
            all_times+=times
        value['pcr']=round(value['put']/value['call'],3) if value['call'] is not None and value['call']>0 and value['put'] is not None else None
        value['oldest_quote']=min(all_times) if all_times else None
        value['status']='unavailable' if value['call'] is None or value['put'] is None else 'fresh' if all_times and not value['call_timestamp_missing'] and not value['put_timestamp_missing'] and now-min(all_times)<=180 else 'stale'
        value['error']='No listed options / symbol mapping unavailable' if not rows else 'Incomplete CE/PE quotes' if value['status']=='unavailable' else None
        result[symbol]=value
    return result

class StockOptionCollector:
    def __init__(self):
        self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None
        self.state=dict(status='starting',companies={},error=None,contracts_done=0,contracts_total=0)
    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            self.stop_event.clear();self.thread=threading.Thread(target=self.run,daemon=True,name='stock-option-oi');self.thread.start()
    def stop(self):self.stop_event.set()
    def read(self):
        self.start()
        with self.lock:return dict(self.state)
    def update(self,**fields):
        with self.lock:self.state.update(fields)
    def run(self):
        while not self.stop_event.is_set():
            phase='constituents'
            try:
                self.update(status='collecting',error=None,stage=phase)
                stocks=members();phase='Kite instrument master';self.update(stage=phase)
                kite=shared.kite_client();today=datetime.now(shared.IST).date()
                with shared.lock:instruments=shared.instruments(kite,today)
                expiry,contracts=universe(stocks,instruments,today)
                keys=sorted({'NFO:'+r['tradingsymbol'] for rows in contracts.values() for r in rows});raw={}
                phase='NFO CE/PE quotes';self.update(stage=phase,contracts_total=len(keys),contracts_done=0,failed_batches=0)
                started=time.time();failures=0
                for offset in range(0,len(keys),400):
                    if self.stop_event.is_set():return
                    if offset and self.stop_event.wait(1.3):return
                    batch=keys[offset:offset+400]
                    try:raw.update(kite.quote(batch))
                    except TokenException:raise
                    except Exception:
                        if self.stop_event.wait(2):return
                        try:raw.update(kite.quote(batch))
                        except TokenException:raise
                        except Exception as error:
                            failures+=1;self.update(last_batch_error=type(error).__name__)
                    self.update(contracts_done=min(offset+400,len(keys)),failed_batches=failures)
                # Retry only incomplete payloads rather than refetching all thousands of contracts.
                for attempt in range(2):
                    needed=[key for key in keys if not numeric(raw.get(key,{}).get('oi')) or raw.get(key,{}).get('oi',-1)<0 or stamp(raw.get(key,{})) is None]
                    if not needed:break
                    self.update(stage='retry incomplete quotes',retry_contracts=len(needed))
                    for offset in range(0,len(needed),400):
                        if self.stop_event.wait(1.3):return
                        try:
                            response=kite.quote(needed[offset:offset+400])
                            for key,q in response.items():
                                if numeric(q.get('oi')) and q['oi']>=0:raw[key]=q
                        except TokenException:raise
                        except Exception:pass
                now=time.time();companies=aggregate(stocks,contracts,raw,now)
                complete=sum(r['call'] is not None and r['put'] is not None for r in companies.values())
                stale=sum(r['status']=='stale' for r in companies.values())
                self.update(status='stale' if complete==len(stocks) and stale else 'ok' if complete==len(stocks) else 'partial',stale_companies=stale,stage='complete',companies=companies,stocks=stocks,
                    expiry=expiry.isoformat(),universe_id=hashlib.sha256('|'.join(keys).encode()).hexdigest(),company_count=len(stocks),quoted_companies=complete,
                    fetched_at=now,collection_span_seconds=round(now-started,1),
                    error=None if complete==len(stocks) else f'{complete}/{len(stocks)} companies have complete CE/PE totals; {failures} quote batches failed. See /api/market/option-oi-status.')
            except Exception as e:
                detail=getattr(e,'detail',None)
                code=getattr(getattr(e,'response',None),'status_code',None)
                message=detail if isinstance(detail,str) else f'{type(e).__name__}'+(f' HTTP {code}' if code else '')+'; check broker access/connection or the constituent CSV'
                self.update(status='unavailable',stage=phase,error=f'{phase}: {message}')
            self.stop_event.wait(60)

collector=StockOptionCollector()
_price_lock=threading.Lock();_price_cache=None;_price_at=0

def scanner_quotes():
    global _price_cache,_price_at
    stocks=members();oi=collector.read()
    with _price_lock:
        if _price_cache is None or time.monotonic()-_price_at>=5:
            kite=shared.kite_client();_price_cache=kite.quote(['NSE:'+s['symbol'] for s in stocks]);_price_at=time.monotonic()
        raw=_price_cache
    rows=[];metadata={};available=0
    for stock in stocks:
        sym=stock['symbol'];q=raw.get('NSE:'+sym,{});ltp=q.get('last_price');close=q.get('ohlc',{}).get('close')
        valid=numeric(ltp) and ltp>0;pct=(ltp-close)/close*100 if valid and numeric(close) and close>0 else None
        opt=oi.get('companies',{}).get(sym,{})
        current=oi.get('status') in ('ok','partial','collecting','stale') and opt.get('status')=='fresh' and opt.get('oldest_quote') is not None and time.time()-opt['oldest_quote']<=180
        # Show actual last-known OI values even when stale, with freshness exposed in metadata.
        oi_label=lambda value:fmt(value)+(' (stale)' if value is not None and not current else '')
        rows.append([sym,f'{ltp:,.2f}' if valid else '—',f'{pct:+.2f}%' if pct is not None else '—',oi_label(opt.get('call')),oi_label(opt.get('put')),str(opt['pcr'])+(' (stale)' if not current else '') if opt.get('pcr') is not None else '—','Bullish' if pct is not None and pct>0 else 'Bearish' if pct is not None and pct<0 else 'Mixed','WAIT'])
        available+=int(valid)
        metadata[sym]=dict(sector=stock['sector'],change_pct=pct,available=valid,oi_status='fresh' if current else 'stale' if opt.get('call') is not None or opt.get('put') is not None else 'unavailable',oi_expiry=oi.get('expiry'),oi_quote_time=opt.get('oldest_quote'),call_oi=opt.get('call'),put_oi=opt.get('put'),pcr=opt.get('pcr'),oi_error=opt.get('error'),quote_timestamp=str(q.get('timestamp') or ''))
    return dict(quotes=rows,metadata=metadata,source='kite',status='ok' if available==len(stocks) else 'partial',available=available,total=len(stocks),fetched_at=datetime.now(timezone.utc).isoformat(),option_oi={k:v for k,v in oi.items() if k not in ('companies','stocks')})
