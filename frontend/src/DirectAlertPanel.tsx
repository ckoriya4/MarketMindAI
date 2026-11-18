import {useEffect,useRef,useState} from "react";
import "./DirectAlertPanel.css";
interface Alert {id:number;created_at:number;direction:string;strike:number;option_type:string;expiry:string;spot_entry:number;spot_sl:number;spot_target:number;option_ltp:number;telegram_status:string}
interface State {status:string;reason?:string;candidate?:string;worker_running:boolean;enabled:boolean;evaluated_at?:number;quote_time?:number;expiry?:string;spot?:number;atm?:number;checks:Record<string,Record<string,boolean>>;cooldown_remaining?:number;
 indicators?:{instrument:string;price:number;ema50:number;vwap:number;rsi14:number};oi?:{net:number;put_delta:number;call_delta:number};latest_alert?:Alert|null;
 parameters?:{start:string;end:string;oi_threshold:number;lookback_minutes:number;sl_points:number;target_points:number;cooldown_seconds:number}}
const ist=(t:number)=>new Date(t*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:false});
const num=(n:number|undefined)=>n==null?'—':n.toLocaleString('en-IN',{maximumFractionDigits:2});
export default function DirectAlertPanel({expiry=""}:{expiry?:string}){
 const [data,setData]=useState<State|null>(null),[error,setError]=useState(''),[now,setNow]=useState(Date.now()),[desktop,setDesktop]=useState(false);
 const seen=useRef<number|null>(null),mounted=useRef(Date.now()/1000);
 useEffect(()=>{const id=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(id);},[]);
 useEffect(()=>{
  let active=true;let timer:ReturnType<typeof setTimeout>|undefined;let controller:AbortController|undefined;
  const load=async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000);
   try{const response=await fetch('http://127.0.0.1:8000/api/signals/direct',{signal:controller.signal});const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Alert status unavailable');if(active){setData(value);setError('');}}
   catch(e){if(active)setError(e instanceof Error?e.message:'Connection failed');}
   finally{clearTimeout(timeout);if(active)timer=setTimeout(load,5000);}
  };
  const start=async():Promise<void>=>{
   controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),15000);
   try{const r=await fetch('http://127.0.0.1:8000/api/signals/direct/config',{signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expiry:expiry||null})});if(!r.ok)throw new Error('Expiry selection rejected');}
   catch(e){if(active){setError(e instanceof Error?e.message:'Configuration failed');timer=setTimeout(()=>void start(),5000);}return;}
   finally{clearTimeout(timeout);}
   if(active)void load();
  };setData(null);void start();return()=>{active=false;clearTimeout(timer);controller?.abort();};
 },[expiry]);
 useEffect(()=>{
  const alert=data?.latest_alert;if(!alert)return;
  const isNew=seen.current==null?alert.created_at>=mounted.current:alert.id>seen.current;
  seen.current=Math.max(seen.current||0,alert.id);
  if(isNew&&desktop&&'Notification' in window&&Notification.permission==='granted'&&Date.now()/1000-alert.created_at<60)new Notification(`${alert.direction} BUY · Rule alert`,{body:`NIFTY ${alert.strike} ${alert.option_type} · Spot ${alert.spot_entry} · SL ${alert.spot_sl} · Target ${alert.spot_target}. No order placed.`});
 },[data,desktop]);
 const fresh=!error&&data?.quote_time!=null&&now/1000-data.quote_time<=30&&data.evaluated_at!=null&&now/1000-data.evaluated_at<=45;
 const candidate=fresh?data?.candidate:null;
 const alert=data?.latest_alert;
 return <section className="panel direct-alert-panel">
  <div className="panel-title">DIRECT CALL / PUT · FOUR-RULE ALERT</div>
  <div className={`direct-alert-banner ${candidate==='CALL'?'call':candidate==='PUT'?'put':'wait'}`}>
   <b>{candidate?`${candidate} BUY · ALL RULES MATCHED`:'NO TRADE · WAITING'}</b>
   <span>{error||(!data?'Connecting to backend engine…':data.status==='cooldown'?`Cooldown: ${data.cooldown_remaining||0}s at last evaluation`:data.reason||data.status)}</span>
  </div>
  <div className="direct-alert-rules">{['CALL','PUT'].map(side=><div key={side}><strong>{side} checks</strong>{Object.entries(data?.checks?.[side]||{}).map(([name,passed])=><span key={name} className={fresh&&passed?'positive':'muted'}>{fresh&&passed?'✓':'○'} {name}</span>)}{!Object.keys(data?.checks?.[side]||{}).length&&<span>Waiting for complete inputs.</span>}</div>)}</div>
  <div className="direct-alert-note">Net ΔOI: {num(data?.oi?.net)} · RSI14: {num(data?.indicators?.rsi14)} · EMA50: {num(data?.indicators?.ema50)} · VWAP: {num(data?.indicators?.vwap)}<br/>
   {data?.indicators?`${data.indicators.instrument} · completed5m close ${num(data.indicators.price)}`:'Actual futures candles required; no substitute VWAP.'}
  </div>
  {alert&&<div className="direct-alert-last"><strong>LAST RECORDED ALERT · {ist(alert.created_at)} IST</strong><b>{alert.direction} BUY · {alert.strike} {alert.option_type} · {alert.expiry}</b><span>Spot reference {num(alert.spot_entry)} · Spot SL {num(alert.spot_sl)} · Spot target {num(alert.spot_target)}</span><span>Option snapshot LTP ₹{num(alert.option_ltp)} · Telegram: {alert.telegram_status}</span><small>Historical alert record; not a fresh entry instruction. Spot levels are not option premium stops and are not monitored/executed.</small></div>}
  <button type="button" onClick={async()=>{if('Notification' in window){const permission=await Notification.requestPermission();setDesktop(permission==='granted');}}}>{desktop?'Browser alerts enabled':'Enable browser notifications'}</button>
  <div className="direct-alert-note">Worker: {data?.worker_running?'running independently of dashboard':'not running'} · Window {data?.parameters?.start||'09:30'}–{data?.parameters?.end||'14:45'} IST · cooldown {data?.parameters?.cooldown_seconds??900}s.<br/>
   OI input = current − {data?.parameters?.lookback_minutes??15}m, not the graph’s previous−current sign. Threshold ±{num(data?.parameters?.oi_threshold)}. A threshold match alone is not a detected crossover.<br/>
   Four rule conditions, not profit certainty. Console alerts only on new matching events; no automatic orders.</div>
 </section>;
}
