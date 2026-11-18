import {useEffect,useState,useSyncExternalStore} from 'react';
import {readOIAlert,subscribeOIAlert} from './oiAlertStore';
export default function OIStatusNotification(){
 const state=useSyncExternalStore(subscribeOIAlert,readOIAlert,readOIAlert);
 const [now,setNow]=useState(Date.now());const [dismissed,setDismissed]=useState('');
 useEffect(()=>{const id=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(id);},[]);
 const alert=state.alert;const recent=!!alert&&now/1000-(alert.time+60)<=90;
 const live=state.enabled&&state.fresh&&recent;
 const shown=alert&&alert.id!==dismissed;
 const text=!state.enabled?'OI alerts OFF':!state.fresh?'OI alerts · WAIT — fresh data required':shown?`BUY ${alert.direction} · ${live?'NEW CROSSOVER':'LAST CROSSOVER'}`:'OI alerts ON · waiting for next crossover';
 return <span role="status" aria-live="polite" style={{display:'inline-flex',alignItems:'center',gap:8,flexWrap:'wrap',marginLeft:12,padding:'5px 9px',border:'1px solid currentColor',borderRadius:5,color:shown&&state.enabled?(alert.direction==='CALL'?'#00d6a3':'#ff4566'):'#ffc94a',fontSize:11,maxWidth:'100%',whiteSpace:'normal'}}>
  <strong>{text}</strong>
  {shown&&state.enabled&&<><span>{new Date((alert.time+60)*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false})} IST · Put {alert.put.toLocaleString('en-IN')} / Call {alert.call.toLocaleString('en-IN')}{!live?' · historical alert':''}</span><button type="button" aria-label="Dismiss status bar crossover" onClick={()=>setDismissed(alert.id)} style={{cursor:'pointer'}}>×</button></>}
 </span>;
}
