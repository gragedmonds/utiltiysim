import {SimulationLibrary} from './simulation-library.js';
import {lockPatch} from './simulation-lock.js';
const id=typeof location==='undefined'?null:new URLSearchParams(location.search).get('simulation');
let library=null;
export let activeSimulation=null;
if(id){library=new SimulationLibrary();activeSimulation=library.get(id);}
// The record keeps the view date of the year in view (the simulation card's) and 2026's episodes (the ones setup chose);
// the years themselves live in the meter-to-cash state (simulation-library.js simulationYears).
export function simulationSaved(m){if(activeSimulation)activeSimulation=library.update(activeSimulation.id,{asOf:m.asOf,seed:m.seed,episodes:(m.yearState?.(2026)||m).episodes,settings:m.settings});}
// Locks the simulation's settings (simulation-lock.js) with the run settings it starts on.
export function lockSimulation(run){if(activeSimulation)activeSimulation=library.update(activeSimulation.id,lockPatch(run));return activeSimulation;}
export function simulationTown(ref,town){if(!activeSimulation)return;activeSimulation=library.update(activeSimulation.id,{townRef:ref,townId:town.id,townName:town.name||activeSimulation.townName,homes:town.homes||activeSimulation.homes});}
