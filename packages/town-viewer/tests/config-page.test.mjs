import test from 'node:test';
import assert from 'node:assert/strict';
import {SECTIONS,sectionFor,hashFor,navModel,navMarkup} from '../dist/config-page.js';

test('the old tab routes still name a section, and a section has one address',()=>{
 assert.deepEqual(SECTIONS.map(s=>s.id),['town','m2c','scenarios','data']);
 assert.equal(sectionFor('#/config'),'town');assert.equal(sectionFor('#/config/m2c'),'m2c');assert.equal(sectionFor('#/settings/scenarios'),'scenarios');assert.equal(sectionFor('#/config/data'),'data');
 assert.equal(sectionFor('#/workspace'),'town','not a configuration route: the first section');
 assert.equal(hashFor('scenarios'),'#/config/scenarios');assert.equal(hashFor('nope'),'#/config/town');
});

// A page as the sidebar reads it: sections with their rendered schema cards (no browser needed).
function fakePage(){
 const row=hidden=>({hidden});
 const card=(group,title,rows,changed='')=>({dataset:{group},hidden:false,id:'',querySelector:sel=>sel==='h3'?{textContent:title+(changed?' '+changed:''),firstChild:{textContent:title}}:sel==='.schema-badge'?{textContent:changed}:null,querySelectorAll:sel=>sel==='.schema-field'?rows:[]});
 const panes={town:{id:'',cards:[card('seeds','Seeds',[row(false),row(false)]),card('town','Town',[row(false),row(true),row(false)],'2 changed')]},m2c:{id:'cfg-m2c',cards:[card('vee','VEE',[row(false)])]},scenarios:{id:'',cards:[]},data:{id:'',cards:[]}};
 for(const p of Object.values(panes))p.querySelectorAll=sel=>sel==='.schema-group'?p.cards:[];
 return {querySelector:sel=>{const m=sel.match(/data-settings-pane="(\w+)"/);return m?panes[m[1]]:null;},panes};
}

test('the sidebar model lists each section and its groups, with stable anchors and visible-field counts',()=>{
 const page=fakePage(),model=navModel(page);
 assert.deepEqual(model.map(s=>s.anchor),['cfg-town','cfg-m2c','cfg-scenarios','cfg-data']);
 assert.equal(page.panes.town.id,'cfg-town','a pane without an id gets one');
 assert.deepEqual(model[0].groups,[{id:'cfg-town-seeds',title:'Seeds',count:2,changed:0},{id:'cfg-town-town',title:'Town',count:2,changed:2}]);
 assert.deepEqual(model[1].groups.map(g=>g.id),['cfg-m2c-vee']);assert.deepEqual(model[2].groups,[]);
 assert.deepEqual(navModel(page).map(s=>s.groups.map(g=>g.id)),model.map(s=>s.groups.map(g=>g.id)),'reading the page again keeps the same ids');
});

test('the sidebar markup marks the active entry and shows how many settings in a group changed',()=>{
 const html=navMarkup(navModel(fakePage()),'cfg-town-town');
 assert.match(html,/class="cfg-nav-head" data-target="cfg-town" data-section="town">Town &amp; meters</);
 assert.match(html,/class="cfg-nav-item is-active" data-target="cfg-town-town">Town<span class="cfg-nav-changed" title="2 changed">2<\/span>/);
 assert.match(html,/data-target="cfg-m2c-vee">VEE<\/button>/);
 assert.doesNotMatch(html,/cfg-nav-groups"><\/div>/,'sections without groups have no empty list');
 assert.equal((html.match(/is-active/g)||[]).length,1);
});

test('generated Title Case labels read as sentences and keep the utility acronyms',async()=>{
 const {sentenceTitle}=await import('../dist/schema-form.js');
 assert.equal(sentenceTitle('Analyst Queue Days Max'),'Analyst queue days max');
 assert.equal(sentenceTitle('Rpa Coverage'),'RPA coverage');assert.equal(sentenceTitle('Ami Missed Read'),'AMI missed read');assert.equal(sentenceTitle('Vee'),'VEE');
 assert.equal(sentenceTitle('Cast iron before year'),'Cast iron before year','a written title is left alone');
 assert.equal(sentenceTitle('Outsort auto-release max'),'Outsort auto-release max');assert.equal(sentenceTitle(''),'');
});
