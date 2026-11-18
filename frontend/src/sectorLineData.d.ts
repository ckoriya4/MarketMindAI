interface Row {time:number;values:Record<string,{call:number|null;put:number|null;total:number|null}>}
export function sectorLineData(points:Row[],name:string,metric:'call'|'put'|'total',session?:{open:number;close:number}):{time:number;value?:number}[];
export function valueCount(points:{value?:number}[]):number;
