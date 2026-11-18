export interface DynamicOIPoint {
  time: number; segment: number; atm: number; step: number;
  put_oi: number; call_oi: number; put_change: number; call_change: number;
}
export function makeSegments(points: DynamicOIPoint[], mode: 'total'|'change') {
  const groups=new Map<number,{segment:number;atm:number;points:Map<number,{time:number;put:number;call:number}>}>();
  for(const p of [...points].sort((a,b)=>a.time-b.time)) {
    const group=groups.get(p.segment) || {segment:p.segment,atm:p.atm,points:new Map()};
    const minute=Math.floor(p.time/60)*60;
    group.points.set(minute,{time:minute,put:mode==='total' ? p.put_oi : p.put_change,call:mode==='total' ? p.call_oi : p.call_change});
    groups.set(p.segment,group);
  }
  return Array.from(groups.values()).sort((a,b)=>a.segment-b.segment).map(g=>({segment:g.segment,atm:g.atm,points:Array.from(g.points.values())}));
}
