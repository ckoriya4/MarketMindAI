// Crossovers of confirmed, displayed minute observations only; never interpolate a tick.
export function findCrossovers(points, nowSeconds) {
 const result=[];let previous=null,lastSign=0;
 for(const p of [...points].sort((a,b)=>a.time-b.time)) {
  if(p.time+60>nowSeconds)continue;
  if(!Number.isFinite(p.a)||!Number.isFinite(p.b)){previous=null;lastSign=0;continue;}
  if(!previous || p.segment!==previous.segment || p.time-previous.time>60 || p.time<=previous.time)lastSign=0;
  const sign=Math.sign(p.a-p.b);
  if(sign && lastSign && sign!==lastSign)result.push({time:p.time,direction:sign>0?'CALL':'PUT',a:p.a,b:p.b,segment:p.segment,fromTime:previous.time,fromA:previous.a,fromB:previous.b,fraction:Math.abs(previous.a-previous.b)/(Math.abs(previous.a-previous.b)+Math.abs(p.a-p.b))});
  if(sign)lastSign=sign;
  previous=p;
 }
 return result;
}
