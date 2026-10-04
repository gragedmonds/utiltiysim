export type Utility = 'electric'|'water'|'gas';
export type NullableNumber = number|null;
export interface Point { x:number; z:number; elevationM?:number }
export interface Heightmap { cols:number;rows:number;cellSizeM:number;originX:number;originZ:number;order?:'row-major-z-positive';values:number[] }
export interface NetworkFrame { unit:'kW'|'m3/h';edgeIds:string[];flows:NullableNumber[];sourceFlow:NullableNumber;enabled?:boolean[] }
export interface Clock { simTime:string;timezone:string;sunElevationDeg?:number;sunAzimuthDeg?:number;moonPhase?:number }
export interface StateFrame { schemaVersion:'utility-state/1.0';townId:string;simulationId:string;topologyRevision:string;indexRevision:string;sequence:number;simTime:string;complete:true;networks:Record<Utility,NetworkFrame>;premises?:{ids:string[];electric:NullableNumber[];water:NullableNumber[];gas:NullableNumber[]};clock?:Clock }
export interface Edge {id:string;from:string;to:string;kind:string;points:Point[];lengthM:number;placement:string;enabled?:boolean;normallyOpen?:boolean;[key:string]:unknown}
export interface Node extends Point {id:string;kind:string;premiseId?:string;servicePointId?:string;[key:string]:unknown}
export interface Network {sourceId:string;sourceIds?:string[];stationId?:string;nodes:Node[];edges:Edge[];unit:'kW'|'m3/h';[key:string]:unknown}
export interface Premise extends Point {id:string;address:string;width:number;depth:number;height:number;angle:number;side:-1|1;roofTone:number;solarKW:number;services:Partial<Record<Utility,string>>;connections?:Utility[];accountId?:string|null;[key:string]:unknown}
export interface ViewerSnapshot {schemaVersion:'utility-town/1.0'|'utility-town/2.0';id:string;count:number;topologyRevision?:string;indexRevision?:string;source?:{utilityOffsets?:string;[key:string]:unknown};bounds:{minX:number;maxX:number;minZ:number;maxZ:number};terrain?:Heightmap|{heightmap:Heightmap};premises:Premise[];roads:{points:Point[];[key:string]:unknown}[];networks:Record<Utility,Network>;[key:string]:unknown}
export interface Inspection {snapshot:ViewerSnapshot;legacy:boolean;sampleHeight:(x:number,z:number)=>number;topologyRevision:string;indexRevision:string;networks:Record<Utility,{nodes:Map<string,Node>;edges:Map<string,Edge>;sources:Set<string>;edgeIds:string[]}>}
export interface FlowView {homes:Map<string,Record<Utility,NullableNumber>>;electric:CommodityFlow;water:CommodityFlow;gas:CommodityFlow}
export interface CommodityFlow {source:NullableNumber;unit:string;edgeFlows:Map<string,NullableNumber>;edgeEnabled:Map<string,boolean>}
export const UTILITIES:Utility[];export const PALETTE:Record<Utility,number>;
export function heightSampler(terrain?:Heightmap|{heightmap:Heightmap},legacyFallback?:(x:number,z:number)=>number):(x:number,z:number)=>number;
export function inspectSnapshot(snapshot:unknown,options?:{legacyTerrain?:(x:number,z:number)=>number}):Inspection;
export function premiseConnections(home:Premise|null|undefined):Utility[];
export const OTHER_UTILITY:'Served by another utility';
export function serviceOf(home:Premise|null|undefined,utility:Utility):'served'|'other'|null;
export function traceConnection(snapshot:ViewerSnapshot,premiseId:string,utility:Utility,enabledOverrides?:Map<string,boolean>|null):{connected:boolean;edges:Edge[];sourceId?:string;reason:string|null;mode?:'connectivity'};
export function geometryOffset(snapshot:ViewerSnapshot,utility:Utility):number;
export function displayQuantity(value:number|null|undefined,unit:string,commodity:Utility,profile?:string):{value:NullableNumber;unit:string};
export function validateClock(clock:Clock|null|undefined):Clock|null;
export class StateReceiver {constructor(inspection:Inspection);inspection:Inspection;frame:StateFrame|null;lastSequence:number;runId:string|null;flow:FlowView|null;validate(frame:unknown):{flow:FlowView;clock:Clock|null};accept(frame:unknown):{flow:FlowView;clock:Clock|null};reset():void}
export function interpolateTrajectory(trajectory:{points:(Point&{at:string})[]},simTime:string):({x:number;z:number;angle:number}|null);
