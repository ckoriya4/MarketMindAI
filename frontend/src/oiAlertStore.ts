export interface CrossAlert {id:string;time:number;direction:string;put:number;call:number;scope:string}
export interface AlertState {enabled:boolean;fresh:boolean;alert:CrossAlert|null}
let state:AlertState={enabled:false,fresh:false,alert:null};
const listeners=new Set<()=>void>();
export function publishOIAlert(next:AlertState){state=next;for(const listener of listeners)listener();}
export const readOIAlert=()=>state;
export function subscribeOIAlert(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener);};}
