// Only actual observations carry values; session whitespace is placed at boundaries only.
export function sectorLineData(points,name,metric,session) {
 const map=new Map();
 for(const p of points) {
  if(!Number.isFinite(p.time) || (session && (p.time<session.open||p.time>session.close)))continue;
  const sectors=['Financial Services','Information Technology','Oil, Gas & Consumable Fuels','FMCG'];
  const vals=sectors.map(s=>p.values[s]?.[metric]);
  const value=name==='Combined'?(vals.every(v=>typeof v==='number'&&Number.isFinite(v))?vals.reduce((s,v)=>s+v,0):null):p.values[name]?.[metric];
  map.set(p.time,typeof value==='number'&&Number.isFinite(value)?{time:p.time,value}:{time:p.time});
 }
 if(session){if(!map.has(session.open))map.set(session.open,{time:session.open});if(!map.has(session.close))map.set(session.close,{time:session.close});}
 return [...map.values()].sort((a,b)=>a.time-b.time);
}
export function valueCount(series) {return series.filter(p=>Number.isFinite(p.value)).length;}
