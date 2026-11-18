export interface CrossPoint {time:number;segment:number;a:number;b:number}
export interface OICrossover extends CrossPoint {direction:'CALL'|'PUT';fromTime:number;fromA:number;fromB:number;fraction:number}
export function findCrossovers(points:CrossPoint[],nowSeconds:number):OICrossover[];
