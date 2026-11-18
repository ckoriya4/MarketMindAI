// Only newly observed, completed one-minute TOTAL OI crossovers qualify.
export function evaluateTotalCross(data, now, cursor, enabled=true, error=false) {
 const minutes=new Map();
 for(const p of [...(data?.points||[])].sort((a,b)=>a.time-b.time)) {
  const t=Math.floor(p.time/60)*60;
  if(t+60<=now && Number.isFinite(p.put_oi)&&Number.isFinite(p.call_oi))minutes.set(t,{...p,time:t});
 }
 const points=[...minutes.values()].sort((a,b)=>a.time-b.time);
 const latest=points.at(-1);const scope=data?.scope||'';
 if(!latest)return {cursor:cursor?.scope===scope?cursor:{scope,time:0},event:null};
 const next={scope,time:Math.max(cursor?.scope===scope?cursor.time:0,latest.time)};
 // First load/reload/scope change establishes a baseline, never replays history.
 if(!cursor||cursor.scope!==scope||!cursor.time||latest.time<=cursor.time)return {cursor:next,event:null};
 let previous=null,sign=0,event=null;
 for(const p of points) {
  if(!previous||p.segment!==previous.segment||p.time-previous.time!==60)sign=0;
  const current=Math.sign(p.put_oi-p.call_oi);
  if(current&&sign&&current!==sign)event={time:p.time,direction:current>0?'CALL':'PUT',put:p.put_oi,call:p.call_oi,atm:p.atm,segment:p.segment};
  if(current)sign=current;
  previous=p;
 }
 const fresh=!error&&data.source==='kite'&&data.status==='fresh'&&now-data.quote_time>=-5&&now-data.quote_time<=30;
 const eligible=enabled&&fresh&&event&&event.time===latest.time&&event.time>cursor.time&&now-(event.time+60)<=90&&latest.source==='live'&&now>=data.session?.open&&now<=data.session?.close;
 return {cursor:next,event:eligible?{...event,id:`${scope}:${event.segment}:${event.time}:${event.direction}`} : null};
}
