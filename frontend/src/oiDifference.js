// Independent signed changes: PREVIOUS (fifteen minute buckets ago) minus CURRENT.
export function oiDifferences(points) {
 const minutes=new Map();
 for(const p of [...points].sort((a,b)=>a.time-b.time)) {
  if(Number.isFinite(p.time))minutes.set(Math.floor(p.time/60)*60,p);
 }
 return [...minutes].sort((a,b)=>a[0]-b[0]).map(([time,current])=>{
  const previous=minutes.get(time-900);
  const sameBasket=previous&&previous.segment===current.segment;
  const valid=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
  return {time,
   put:sameBasket&&valid(previous.put_oi)&&valid(current.put_oi)?previous.put_oi-current.put_oi:null,
   call:sameBasket&&valid(previous.call_oi)&&valid(current.call_oi)?previous.call_oi-current.call_oi:null
  };
 });
}
