import {useEffect,useRef,useState} from "react";
import "./OIProSignalPanel.css";
interface Candidate {kind:string;direction:string;action:string;entry_type:string}
interface Event extends Candidate {id:number;created_at:number;strike:number;option_type:string;expiry:string;spot_entry:number;spot_sl:number|null;spot_target:number|null;option_ltp:number;telegram_status:string;risk_note:string;d:number;m:number}
interface State {status:string;reason?:string;candidate?:Candidate|null;worker_running:boolean;enabled:boolean;evaluated_at?:number;quote_time?:number;expiry?:string;spot?:number;atm?:number;strikes?:number[];checks:Record<string,Record<string,boolean>>;
 oi?:{d:number;m:number|null;previous_d:number|null;previous_m:number|null;baseline_time:number;premium_counts:Record<string,Record<string,number>>};
 latest_alert?:Event|null;latest_entry?:Event|null;events?:Event[];loss_streak?:number;oi_bar_close?:number;entry_bar_close?:number;
 parameters?:{start:string;end:string;cooldown_seconds:number;premium_filter:boolean;keep_ema_rsi:boolean;capital:number;risk_pct:number;max_losses:number}}
const num=(n:number|null|undefined)=>n==null?'—':n.toLocaleString('en-IN',{maximumFractionDigits:2});
const ist=(n:number)=>new Date(n*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false});
export default function OIProSignalPanel({expiry=""}:{expiry?:string}){
 const [data,setData]=useState<State|null>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[desktop,setDesktop]=useState(false),[now,setNow]=useState(Date.now());
 const seen=useRef<number|null>(null),mounted=useRef(Date.now()/1000);
 useEffect(()=>{const id=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(id);},[]);
 useEffect(()=>{
  let active=true;let timer:ReturnType<typeof setTimeout>|undefined;let controller:AbortController|undefined;
  const load=async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000);
   try{const r=await fetch('http://127.0.0.1:8000/api/signals/direct',{signal:controller.signal});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'OI PRO unavailable');if(active){setData(d);setError('');}}
   catch(e){if(active)setError(e instanceof Error?e.message:'Connection failed');}finally{clearTimeout(timeout);if(active)timer=setTimeout(load,5000);}
  };
  const start=async():Promise<void>=>{controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000);
   try{const r=await fetch('http://127.0.0.1:8000/api/signals/direct/config',{signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expiry:expiry||null})});if(!r.ok)throw new Error('Expiry configuration rejected');}
   catch(e){if(active){setError(e instanceof Error?e.message:'Configuration failed');timer=setTimeout(()=>void start(),5000);}return;}
   finally{clearTimeout(timeout);}if(active)void load();
  };setData(null);void start();return()=>{active=false;clearTimeout(timer);controller?.abort();};
 },[expiry]);
 useEffect(()=>{
  const event=data?.latest_alert;if(!event)return;
  const isNew=seen.current==null?event.created_at>=mounted.current:event.id>seen.current;seen.current=Math.max(seen.current||0,event.id);
  if(isNew&&desktop&&'Notification' in window&&Notification.permission==='granted'&&Date.now()/1000-event.created_at<60)new Notification(event.action==='PREPARE'?`EARLY ${event.direction} · PREPARE ONLY`:`${event.direction} BUY · ${event.kind}`,{body:`${event.strike} ${event.option_type}. ${event.entry_type}. No order placed.`});
 },[data,desktop]);
 const fresh=!error&&data?.quote_time!=null&&now/1000-data.quote_time<=30&&data.evaluated_at!=null&&now/1000-data.evaluated_at<=45;
 const signal=fresh?data?.candidate:null;
 const logOutcome=async(id:number,result:string)=>{try{const r=await fetch('http://127.0.0.1:8000/api/signals/direct/outcome',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alert_id:id,result})});if(!r.ok)throw new Error('Paper result rejected');setNotice(`Paper ${result} recorded for alert #${id}; no broker trade changed.`);}catch(e){setNotice(e instanceof Error?e.message:'Paper log failed');}};
 return <section className="panel oi-pro-panel">
  <div className="panel-title">NIFTY OI PRO · 15m SETUP / 5m ENTRY</div>
  <div className={`oi-pro-banner ${signal?.action==='BUY'?signal.direction==='CALL'?'call':'put':signal?'prepare':'wait'}`}>
   <strong>{signal?signal.action==='PREPARE'?`EARLY ${signal.direction} · PREPARE ONLY`:`${signal.direction} BUY · ${signal.kind}`:'NO ENTRY · WAITING'}</strong>
   <span>{error||data?.reason||'Connecting to OI PRO backend…'}</span><small>{data?.status}</small>
  </div>
  <div className="oi-pro-types">{['EARLY','CROSSOVER','TREND'].map(kind=><span key={kind} className={signal?.kind===kind?'active':''}>{kind==='EARLY'?'Early momentum · prepare':kind==='CROSSOVER'?'Confirmed crossover':'No-crossover trend'}</span>)}</div>
  <div className="oi-pro-metrics"><span>Cumulative D <b>{num(data?.oi?.d)}</b></span><span>15m momentum M <b>{num(data?.oi?.m)}</b></span></div>
  <div className="oi-pro-note">Symmetric CE and PE basket: {data?.strikes?.map(num).join(' / ')||'Waiting for listed ATM ±2 strikes'}. Same five strikes both sides; no3/2/1 weighting.</div>
  <details><summary>Route checks / premium evidence</summary><div className="oi-pro-checks">{['CALL','PUT'].map(side=><div key={side}><b>{side}</b>{Object.entries(data?.checks?.[side]||{}).map(([name,passed])=><span key={name} className={fresh&&passed?'positive':'muted'}>{fresh&&passed?'✓':'○'} {name}</span>)}</div>)}</div>
   {data?.oi?.premium_counts&&<div className="oi-pro-note">{Object.entries(data.oi.premium_counts).map(([side,counts])=><div key={side}>{side}: {Object.entries(counts).map(([name,n])=>`${name.replaceAll('_',' ')} ${n}`).join(' · ')}</div>)}Premium/OI labels are conventional hints, not proof of trade initiation.</div>}
  </details>
  <div className="oi-pro-note">OI close {data?.oi_bar_close?ist(data.oi_bar_close):'—'} · Entry5m close {data?.entry_bar_close?ist(data.entry_bar_close):'—'} IST.<br/>Basket baseline {data?.oi?.baseline_time?ist(data.oi.baseline_time+900):'—'} IST. D resets at a new basket or missing-data run. Index spot {num(data?.spot)}.</div>
  {(data?.events||[]).map(event=><article className="oi-pro-event" key={event.id}>
   <b>{event.action==='PREPARE'?`EARLY ${event.direction} · PREPARE ONLY`:`${event.direction} BUY · ${event.kind}`} · #{event.id}</b>
   <span>{ist(event.created_at)} IST · {event.strike} {event.option_type} · {event.expiry}</span>
   <span>Spot reference {num(event.spot_entry)} · SL {num(event.spot_sl)} · Target {num(event.spot_target)}</span>
   <small>{event.risk_note} · Telegram {event.telegram_status}. Recorded history, not a current entry instruction.</small>
  </article>)}
  <div className="oi-pro-note">Paper-log loss streak: {data?.loss_streak??0}/{data?.parameters?.max_losses??2}. Results are manual, not fetched from your trading account.</div>
  {data?.latest_entry&&<div className="oi-pro-log"><span>Latest BUY alert #{data.latest_entry.id} · record PAPER outcome:</span>{['WIN','LOSS','FLAT'].map(result=><button type="button" key={result} onClick={()=>void logOutcome(data.latest_entry!.id,result)}>{result}</button>)}</div>}
  {notice&&<div className="oi-pro-note" role="status">{notice}</div>}
  <button type="button" onClick={async()=>{if('Notification' in window)setDesktop(await Notification.requestPermission()==='granted');}}>{desktop?'Browser alerts enabled':'Enable browser notifications'}</button>
  <div className="oi-pro-note">Worker {data?.worker_running?'running independently of page':'not started'} · {data?.parameters?.start||'09:30'}–{data?.parameters?.end||'14:45'} IST. Actual futures VWAP/price confirmation; actual index ATM/spot levels. No orders, automatic exits or profit guarantees.</div>
 </section>;
}
