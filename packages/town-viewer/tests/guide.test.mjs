import test from 'node:test';
import assert from 'node:assert/strict';
import {guideMarkup,installGuide} from '../dist/guide.js';

const sample={schemaVersion:'engine-guide/1.0',summary:'A seeded <engine>.',capabilities:[{id:'town',title:'Town generation',text:'Streets & parcels',where:['Configuration › Town & meters']}],impacts:[{title:'Backlog',text:'Open cases',where:'Year'}],
 scale:{measuredOn:'October 2026',measured:[{town:'Cobourg',homes:5500,accounts:6993,registers:18378,generateS:26,replayS:15,memoryMB:110}],limits:[{title:'Hosted',text:'60 seconds'}]},
 gaps:[{title:'Storm season',text:'Not yet',plan:'Operations year'}],status:{engine:'hosted',generatorVersion:'0.9.0',schemaVersion:'utility-town/2.0',towns:['ayr','elora'],capabilities:{generate:false},limits:{episodes:40,actions:2000,interruptions:500,pageRows:500,csvRows:5000,yearDays:365,scenarios:16,tables:26}}};

test('the guide renders its sections as sidebar groups with counts, escaped text and the live status',()=>{
 const html=guideMarkup(sample);
 for(const id of ['capabilities','impacts','scale','gaps','status'])assert.match(html,new RegExp(`<details class="schema-group guide-group" data-group="${id}" open>`));
 assert.match(html,/<h3>What it can do<\/h3><span class="schema-count">1<\/span>/);assert.match(html,/<h3>Gaps still remaining<\/h3><span class="schema-count">1<\/span>/);
 assert.match(html,/A seeded &lt;engine&gt;\./,'summary is escaped');assert.match(html,/Streets &amp; parcels/);
 assert.match(html,/<td>Cobourg<\/td><td>5,500<\/td><td>6,993<\/td><td>18,378<\/td><td>26 s<\/td><td>15 s<\/td><td>110 MB<\/td>/);
 assert.match(html,/Measured October 2026\./);assert.match(html,/<dt>Hosted<\/dt><dd>60 seconds<\/dd>/);
 assert.match(html,/16 scenarios/);assert.match(html,/5,000 rows a CSV page/);
 assert.match(html,/<strong>Storm season\.<\/strong> Not yet <span class="guide-plan">Next: Operations year<\/span>/);
 assert.match(html,/<dt>Engine<\/dt><dd>hosted<\/dd>/);assert.match(html,/No \(prebuilt towns only\)/);assert.match(html,/guide-chip">ayr</);
 assert.equal(guideMarkup(null),'');
});

test('the guide is fetched once per engine and the note stays when there is none',async()=>{
 const calls=[],root={innerHTML:''};
 const ok={ok:true,json:async()=>sample},fetchImpl=async url=>{calls.push(url);return url.startsWith('/api')?ok:{ok:false,status:404};};
 const g=installGuide({api:()=>'/api',root,fetchImpl});
 assert.equal((await g.render()).schemaVersion,'engine-guide/1.0');await g.render();assert.deepEqual(calls,['/api/m2c/guide']);assert.match(root.innerHTML,/What it can do/);
 const none=installGuide({api:'http://old/api',root:{innerHTML:''},fetchImpl});assert.equal(await none.render(),null);assert.equal(none.guide,null);
 const down=installGuide({api:'http://down/api',root:{innerHTML:''},fetchImpl:async()=>{throw Error('network');}});assert.equal(await down.render(),null);
});
