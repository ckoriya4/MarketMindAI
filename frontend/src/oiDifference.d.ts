export interface DifferenceInput {time:number;segment:number;put_oi:number;call_oi:number}
export interface OIDifference {time:number;put:number|null;call:number|null}
export function oiDifferences(points:DifferenceInput[]):OIDifference[];
