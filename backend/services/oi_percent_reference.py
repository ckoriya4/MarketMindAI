"""Reverse-percent OI change using verified previous-session reference totals."""
import json,math
from datetime import date
from fastapi import APIRouter,Query,HTTPException
from . import oi_signal as shared
from .session_recorder import recorder
from .dynamic_oi import prepare_db
from .previous_oi import previous_baselines
router=APIRouter()

def reverse_oi(current,percent):
    valid=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
    if not valid(current) or current<=0 or not valid(percent) or percent<=-100:return None
    reference=current/(1+percent/100)
    return dict(reference=reference,change=current-reference)

def reference_change(current,reference):
    valid=lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0
    if not valid(current) or not valid(reference):return None
    pct=(current-reference)/reference*100
    value=reverse_oi(current,pct)
    return dict(value,percent=pct) if value else None

def attach_references(data,selections,contracts,baselines):
    points=[];missing=0
    for point in data['points']:
        selection=selections.get(point['segment']);values={};dates=set();complete=selection is not None
        if complete:
            for typ,side in [('PE','put'),('CE','call')]:
                total=0
                for strike in selection[side+'_strikes']:
                    key=contracts.get((strike,typ));entry=baselines.get(key)
                    if not entry:complete=False;break
                    total+=entry[0];dates.add(entry[1])
                if not complete:break
                value=reference_change(point[side+'_oi'],total)
                if not value:complete=False;break
                values[side]=value
        valid=complete and len(dates)==1
        if not valid:missing+=1
        points.append(dict(point,absolute_put=values['put']['change'] if valid else None,
            absolute_call=values['call']['change'] if valid else None,
            absolute_put_pct=values['put']['percent'] if valid else None,
            absolute_call_pct=values['call']['percent'] if valid else None,
            absolute_reference_date=next(iter(dates)) if valid else None))
    return dict(data,points=points,latest=points[-1],absolute_method='reference-recovered-from-percentage',
        absolute_reference='Previous actual trading-session closing OI, not automatically morning/open OI',
        absolute_missing_points=missing,
        absolute_note='Current OI/(1+Change%/100) gives the percent-reference OI. Aggregate percentages use verified summed reference OI, not average strike percentages. Missing/zero reference stays unavailable.')

@router.get('/api/signals/oi-reference')
def oi_reference(symbol:str=Query('NIFTY'),expiry:str|None=Query(None),side_strikes:int=Query(3),itm_strikes:int=Query(0)):
    if symbol not in ('NIFTY','BANKNIFTY'):raise HTTPException(422,'Unsupported underlying')
    data=recorder.read(symbol,expiry,3,0)
    if data.get('selection_mode')!='dynamic-direct-sum':raise HTTPException(503,'Install the direct-sum graph backend first.')
    day=data['session']['date'];expiry_day=date.fromisoformat(data['expiry'])
    db=prepare_db()
    try:rows=db.execute('SELECT segment,selection FROM dynamic_oi_samples WHERE scope=? ORDER BY time',(data['scope'],)).fetchall()
    finally:db.close()
    selections={segment:json.loads(value) for segment,value in rows}
    wanted={(strike,typ) for selection in selections.values() for typ,side in [('PE','put'),('CE','call')] for strike in selection[side+'_strikes']}
    try:
        kite=shared.kite_client()
        with shared.lock:listed=shared.instruments(kite,date.fromisoformat(day))
        selected={(int(r['strike']),r['instrument_type']):r for r in listed if r.get('name')==symbol and r.get('instrument_type') in ('PE','CE') and shared.expiry_date(r['expiry'])==expiry_day and (int(r['strike']),r['instrument_type']) in wanted}
        contract_keys={pair:'NFO:'+r['tradingsymbol'] for pair,r in selected.items()}
        baseline=previous_baselines(day,[(contract_keys[pair],r['instrument_token']) for pair,r in selected.items()])
    except Exception:contract_keys={};baseline={}
    return attach_references(data,selections,contract_keys,baseline)
