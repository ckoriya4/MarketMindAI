"""Completed-bar OI/price rules. They are hypotheses, not profit probabilities."""
import math

def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def premium_state(oi_change,price_change):
    if oi_change>0 and price_change>0:return 'long_buildup'
    if oi_change>0 and price_change<0:return 'possible_writing'
    if oi_change<0 and price_change>0:return 'short_covering'
    if oi_change<0 and price_change<0:return 'long_unwinding'
    return 'unchanged_or_mixed'

def summarize_oi(times,histories,put_keys,call_keys):
    """Only a contiguous current-ATM segment supplied by the runtime; no missing legs."""
    rows=[]
    for t in times:
        if rows and t-rows[-1]['time']!=900:rows=[]
        legs=[histories.get(k,{}).get(t) for k in put_keys+call_keys]
        if any(r is None or not number(r.get('oi')) or r['oi']<0 or not number(r.get('close')) or r['close']<=0 for r in legs):
            # Never bridge a missing contract-minute: restart the valid calculation run.
            rows=[];continue
        rows.append(dict(time=t,put=sum(histories[k][t]['oi'] for k in put_keys),call=sum(histories[k][t]['oi'] for k in call_keys)))
    if not rows:raise ValueError('No complete same-basket 15m OI records')
    base=rows[0]
    for i,row in enumerate(rows):
        row['pe_change']=row['put']-base['put'];row['ce_change']=row['call']-base['call'];row['d']=row['pe_change']-row['ce_change']
        row['m']=row['d']-rows[i-1]['d'] if i else None
    latest=rows[-1];previous=rows[-2] if len(rows)>1 else None
    last_nonzero=next((r['d'] for r in reversed(rows[:-1]) if r['d']!=0),None)
    cross=1 if last_nonzero is not None and last_nonzero<0<latest['d'] else -1 if last_nonzero is not None and last_nonzero>0>latest['d'] else 0
    counts={side:{state:0 for state in ('possible_writing','long_buildup','short_covering','long_unwinding','unchanged_or_mixed')} for side in ('PE','CE')}
    if previous:
        for side,keys in [('PE',put_keys),('CE',call_keys)]:
            for key in keys:
                a=histories[key][latest['time']];b=histories[key][previous['time']]
                counts[side][premium_state(a['oi']-b['oi'],a['close']-b['close'])]+=1
    pe,ce=counts['PE'],counts['CE']
    bullish=(pe['possible_writing']>pe['long_buildup'] and pe['possible_writing']>0) or (ce['short_covering']>ce['possible_writing'] and ce['short_covering']>0)
    bearish=(ce['possible_writing']>ce['long_buildup'] and ce['possible_writing']>0) or (pe['short_covering']>pe['possible_writing'] and pe['short_covering']>0)
    return dict(rows=rows,d=latest['d'],previous_d=previous['d'] if previous else None,m=latest['m'],previous_m=previous['m'] if previous else None,
        cross=cross,baseline_time=base['time'],snapshot_time=latest['time'],premium_counts=counts,premium_bullish=bullish,premium_bearish=bearish)

def breakout_confirmation(bars,level,direction):
    if len(bars)<2:return False,'need two completed 5m bars'
    previous,current=bars[-2:]
    if current['time']-previous['time']!=300:return False,'5m gap'
    if direction>0:
        retest=previous['close']>level and current['low']<=level and current['close']>level
        held=previous['close']>level and current['close']>level
    else:
        retest=previous['close']<level and current['high']>=level and current['close']<level
        held=previous['close']<level and current['close']<level
    return bool(retest or held),'retest held' if retest else 'two closes held' if held else 'breakout not held'

def evaluate(oi,trend,entry,cfg):
    """Early is PREPARE only. Trade routes require live data gates in runtime too."""
    if oi['m'] is None or oi['previous_d'] is None:return dict(candidate=None,checks={},reason='Waiting for two complete same-basket 15m OI records')
    p,prev=trend['last'],trend['previous'];price=p['close'];vwap=trend['vwap'];m=oi['m'];d=oi['d'];threshold=cfg['min_momentum']
    flat=abs(vwap-trend['previous_vwap'])<=price*0.0002 and prev['low']<=price<=prev['high']
    large_bar=(p['high']-p['low'])>cfg['max_candle_atr']*trend['atr14']
    rows={};candidates=[]
    for direction,side in [(1,'CALL'),(-1,'PUT')]:
        above=price>vwap if direction>0 else price<vwap
        entry_vwap=entry['last']['close']>entry['vwap'] if direction>0 else entry['last']['close']<entry['vwap']
        momentum=m>threshold if direction>0 else m<-threshold
        structure=p['high']>prev['high'] and p['low']>prev['low'] if direction>0 else p['high']<prev['high'] and p['low']<prev['low']
        level=prev['high'] if direction>0 else prev['low']
        held,entry_type=breakout_confirmation(entry['bars'],level,direction)
        premium=oi['premium_bullish'] if direction>0 else oi['premium_bearish']
        if not cfg['premium_filter']:premium=True
        ema_rsi=True
        if cfg['keep_ema_rsi']:
            e=entry['ema50'];r=entry['rsi14'];ep=entry['last']['close']
            ema_rsi=ep>e and r>55 if direction>0 else ep<e and r<45
        cross=oi['cross']==direction
        checks={'15m price vs VWAP':above,'15m OI momentum':momentum,('Premium/OI support' if cfg['premium_filter'] else 'Premium/OI filter disabled'):premium,
            '5m price vs VWAP':entry_vwap,'Not sideways/oversized':not flat and not large_bar,('EMA50/RSI enabled' if cfg['keep_ema_rsi'] else 'EMA50/RSI disabled'):ema_rsi,
            'Cumulative crossover':cross,'HH/HL or LH/LL':structure,'Breakout/retest held':held}
        rows[side]=checks
        common=above and entry_vwap and momentum and premium and not flat and not large_bar and ema_rsi
        if cross and common:candidates.append(dict(kind='CROSSOVER',direction=side,action='BUY',entry_type='15m crossover + completed5m price confirmation'))
        elif not cross and common and structure and held:candidates.append(dict(kind='TREND',direction=side,action='BUY',entry_type=entry_type))
        turn=oi['previous_m'] is not None and (m>threshold and oi['previous_m']<=0 and d<0 and d>oi['previous_d'] if direction>0 else m<-threshold and oi['previous_m']>=0 and d>0 and d<oi['previous_d'])
        if turn and above:candidates.append(dict(kind='EARLY',direction=side,action='PREPARE',entry_type='OI momentum turned before cumulative zero cross'))
    chosen=next((c for c in candidates if c['kind']=='CROSSOVER'),None) or next((c for c in candidates if c['kind']=='TREND'),None) or next((c for c in candidates if c['kind']=='EARLY'),None)
    return dict(candidate=chosen,checks=rows,reason='All selected route rules match' if chosen else 'No qualified route; wait for completed price/OI confirmation',neutral=flat,large_candle=large_bar)
