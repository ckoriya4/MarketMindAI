// Chain-link weighted OI changes across ATM basket segments. No prices/OI are invented.
export function continuousChanges(points) {
 let segment=null,offsetA=0,offsetB=0,baseA=0,baseB=0,lastA=0,lastB=0;
 return [...points].sort((a,b)=>a.time-b.time).map(p=>{
  if(p.segment!==segment){offsetA=lastA;offsetB=lastB;baseA=p.put_change;baseB=p.call_change;segment=p.segment;}
  lastA=offsetA+p.put_change-baseA;lastB=offsetB+p.call_change-baseB;
  return {...p,put_change:lastA,call_change:lastB};
 });
}
