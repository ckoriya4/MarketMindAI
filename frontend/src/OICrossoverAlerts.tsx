import {publishOIAlert} from "./oiAlertStore";
import {useEffect,useRef,useState} from 'react';
import {evaluateTotalCross} from './sumOiAlert.mjs';
interface Point {time:number;segment:number;put_oi:number;call_oi:number;atm?:number;source?:string}
interface Snapshot {scope:string;source:string;status:string;quote_time:number;points:Point[];session:{open:number;close:number}}
interface Alert {scope:string;id:string;time:number;direction:string;put:number;call:number;atm?:number}
export default function OICrossoverAlerts({data,error=false}:{data:Snapshot|null;error?:boolean}) {
 const cursor=useRef<{scope:string;time:number}|null>(null);
 const [enabled,setEnabled]=useState(false),[permission,setPermission]=useState('Not enabled');
 const [alert,setAlert]=useState<Alert|null>(null);
 useEffect(()=>{
  if(!data)return;
  const result=evaluateTotalCross(data,Date.now()/1000,cursor.current,enabled,error);cursor.current=result.cursor;
  const event=result.event as Alert|null;if(!event)return;
  // Persist deduplication across remounts/tabs where storage is available.
  const key='nifty-total-oi-last-alert:'+data.scope;
  try{if(localStorage.getItem(key)===event.id)return;localStorage.setItem(key,event.id);}catch{/* in-memory cursor remains active */}
  setAlert({...event,scope:data.scope});
  const title=`NIFTY · BUY ${event.direction} · OI CROSSOVER`;
  const when=new Date((event.time+60)*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false});
  const body=`${when} IST · Put sum ${event.put.toLocaleString('en-IN')} · Call sum ${event.call.toLocaleString('en-IN')}. Crossover-only alert; price confirmation required.`;
  if(typeof Notification!=='undefined'&&Notification.permission==='granted'){
   try{new Notification(title,{body,tag:event.id});}catch{/* banner remains available */}
  }
 },[data,enabled,error]);
 useEffect(()=>{
  const tick=()=>publishOIAlert({enabled,fresh:!!data&&!error&&data.source==='kite'&&data.status==='fresh'&&Date.now()/1000-data.quote_time>=-5&&Date.now()/1000-data.quote_time<=30,alert:alert?.scope===data?.scope?alert:null});
  tick();const id=setInterval(tick,1000);return()=>clearInterval(id);
 },[data,error,enabled,alert]);
 useEffect(()=>()=>publishOIAlert({enabled:false,fresh:false,alert:null}),[]);
 async function enable(){
  setEnabled(true);
  if(typeof Notification==='undefined'){setPermission('In-page alerts only: desktop notifications unsupported');return;}
  try{const p=await Notification.requestPermission();setPermission(p==='granted'?'Desktop + in-page alerts enabled':'In-page alerts enabled; desktop permission not granted');}
  catch{setPermission('In-page alerts enabled; desktop notifications unavailable');}
 }
 return <div style={{border:'1px solid #25485c',borderRadius:5,padding:8,margin:'8px 0',fontSize:11}}>
  <button type="button" onClick={()=>enabled?setEnabled(false):void enable()}>{enabled?'Disable':'Enable'} OI crossover alerts</button>
  <span role="status"> {enabled?permission:'Alerts off'}</span>
  <div>Uses TOTAL Put/Call OI sums, regardless of chart mode or hidden lines. Confirmed 1-minute crosses only. Keep this page open.</div>
  {alert&&<div role="alert" style={{color:alert.direction==='CALL'?'#00d6a3':'#ff4566',paddingTop:8}}>
   <strong>BUY {alert.direction} · TOTAL OI CROSSOVER</strong><br/>
   {new Date((alert.time+60)*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST · Put {alert.put.toLocaleString('en-IN')} · Call {alert.call.toLocaleString('en-IN')}<br/>
   {alert.direction==='CALL'?'Put sum crossed above Call sum.':'Call sum crossed above Put sum.'} Historical alert once shown; not a persistent active entry. Confirm price and risk before acting.
   <button type="button" onClick={()=>setAlert(null)}>Dismiss</button>
  </div>}
 </div>;
}
