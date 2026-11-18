import {useEffect,useMemo,useState} from "react";
import CrudePriceChart from "./CrudePriceChart";
import "./EnergyPanels.css";
interface DailySeries {price:number;change:number;change_pct:number|null;as_of:string;history:{date:string;value:number}[]}
interface Daily {status:string;series?:{WTI?:DailySeries;Brent?:DailySeries};error?:string}
interface Live {status:string;price?:number;symbol?:string;quote_time?:number;change?:number|null;change_pct?:number|null;history?:{time:number;value:number}[];history_date?:string;history_mode?:string;history_error?:string;error?:string;fetched_at?:number}
function useData<T>(path:string,interval:number) {
 const [data,setData]=useState<T|null>(null),[error,setError]=useState("");
 useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>|undefined;let controller:AbortController|undefined;
  const load=async()=>{controller=new AbortController();const timeout=setTimeout(()=>controller?.abort(),60000);
   try{const r=await fetch(`http://127.0.0.1:8000${path}`,{signal:controller.signal});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:"API unavailable");if(active){setData(d);setError("");}}
   catch(e){if(active)setError(e instanceof Error?e.message:"Refresh failed");}
   finally{clearTimeout(timeout);if(active)timer=setTimeout(load,interval);}
  };void load();return()=>{active=false;clearTimeout(timer);controller?.abort();};
 },[path,interval]);return {data,error};
}
const signed=(n:number)=>`${n>=0?"+":""}${n.toFixed(2)}`;
const ist=(n:number)=>new Date(n*1000).toLocaleString("en-IN",{timeZone:"Asia/Kolkata",hour12:false});
export default function LiveCrudeOilPanel(){
 const {data:live,error:liveError}=useData<Live>("/api/energy/crude/live",5000);
 const {data:daily,error:dailyError}=useData<Daily>("/api/energy/crude/daily",1800000);
 const [source,setSource]=useState("MCX"),[follow,setFollow]=useState(true),[now,setNow]=useState(Date.now());
 useEffect(()=>{const id=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(id);},[]);
 const age=live?.quote_time?Math.max(0,Math.floor(now/1000-live.quote_time)):null;
 const fresh=!liveError&&live?.status==="fresh"&&age!=null&&age<=90;
 const wti=daily?.series?.WTI,brent=daily?.series?.Brent;
 const points=useMemo(()=>source==="MCX"?live?.history||[]:(source==="WTI"?wti:brent)?.history.map(p=>({time:Date.parse(p.date+"T12:00:00Z")/1000,value:p.value}))||[],[source,live,wti,brent]);
 const note=source==="MCX"?liveError||live?.error||live?.history_error:dailyError||daily?.error;
 return <section className="panel crude">
  <div className="panel-title"><span>∿ CRUDE OIL ANALYSIS</span></div>
  <div className="crude-head"><div className="oil-icon">♜</div><div>
   <span className="muted tiny">WTI / Brent · EIA daily · USD/barrel</span>
   <b>{wti?`$${wti.price.toFixed(2)}`:"—"} / {brent?`$${brent.price.toFixed(2)}`:"—"}</b>
   <span className={wti&&wti.change<0?"negative":"positive"}>{wti?`${signed(wti.change)} (${wti.change_pct==null?"—":signed(wti.change_pct)+"%"}) · WTI daily`:dailyError||"Loading daily observations…"}</span>
  </div></div>
  <div className="energy-chart-toolbar"><strong className="tiny">{source==="MCX"?live?.symbol||"MCX crude":`${source} daily spot`} — PRICE CHART</strong>
   <select aria-label="Crude price source" value={source} onChange={e=>setSource(e.target.value)}><option value="MCX">MCX crude · INR</option><option value="WTI">WTI · EIA daily</option><option value="Brent">Brent · EIA daily</option></select>
  </div>
  {source==="MCX"&&<div className="energy-chart-toolbar"><b className={fresh?"positive":"negative"}>{live?.price!=null?`₹${live.price.toLocaleString("en-IN")}`:"—"} · {fresh?"LIVE SNAPSHOT":"STALE / UNAVAILABLE"}</b><label className="tiny"><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/> Follow latest</label></div>}
  <CrudePriceChart points={points} instrument={source==="MCX"?live?.symbol||"MCX":source} intraday={source==="MCX"} unavailable={note} followLatest={follow}/>
  <div className="muted tiny">{source==="MCX"?live?.history_mode||"Waiting for actual MCX history":"Official EIA daily spot observations — not a live tick feed"}</div>
  <ul className="check-list">
   <li>WTI as of {wti?.as_of||"—"} · Brent as of {brent?.as_of||"—"}</li>
   <li>MCX quote: {live?.quote_time?`${ist(live.quote_time)} IST · age ${age}s`:"—"}{live?.change_pct!=null?` · ${signed(live.change_pct)}%`:""}</li>
   <li>{source==="MCX"?"MCX polls every 5s after each request · historical closes refresh every 5m":"EIA daily data refreshes every 30m; publication dates may lag"}</li>
   {note&&<li role="status">{note}</li>}
  </ul>
 </section>;
}
