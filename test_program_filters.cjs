'use strict';
// Run with: node test_program_filters.cjs (no packages, network or account needed).
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(Boolean);
scripts.forEach(script=>new vm.Script(script));
const helpers=html.match(/\/\/ BEGIN PROGRAM FILTER HELPERS[^\n]*\n([\s\S]*?)\/\/ END PROGRAM FILTER HELPERS/)[1];
const ctx=vm.createContext({});vm.runInContext(helpers,ctx);
let assertions=0;
function eq(actual,expected,label){assert.deepEqual(actual,expected,label);assertions++}
const {classifyCost:cost,classifyDelivery:delivery,classifyProgramType:type,matchesProgramFilters:matches}=ctx;
for(const [record,expected] of [
 [{},'unknown'],[{fee:null},'unknown'],[{fee:''},'unknown'],[{fee:0},'free'],[{fees:0},'free'],[{fee:'0'},'free'],[{fee:'Free'},'free'],[{fee:'Nil'},'free'],[{fee:'No registration fee'},'free'],[{fee:'₹0'},'free'],[{summary:'Registration is free.'},'free'],[{description:'No fee for participation.'},'free'],[{description:'Registration fee: 0'},'free'],
 [{fee:950},'paid'],[{fees:'INR 950'},'paid'],[{fee:'Rs. 1,500 token, remaining discounted fee payable'},'paid'],[{summary:'Registration fee ₹950; no stipend.'},'paid'],[{description:'Paid online workshop.'},'paid'],[{summary:'Course fee: 950'},'paid'],[{fee:'Displayed discounted price; total to be confirmed'},'paid'],
 [{summary:'No stipend.'},'unknown'],[{summary:'Free portal access.'},'unknown'],[{description:'Free certificate and materials.'},'unknown'],[{summary:'Stipend ₹12000 per month.'},'unknown'],[{description:'Prizes worth ₹50000.'},'unknown'],[{summary:'Free demo session; course fee not stated.'},'unknown'],[{fee:'Not disclosed',summary:'Free workshop'},'unknown'],[{fee:'Not free'},'unknown'],[{fee:'Not stated'},'unknown'],[{fee:'No fees disclosed'},'unknown'],[{summary:'No fee information provided'},'unknown'],[{fee:'No fee; stipend ₹5000'},'free'],[{fee:{amount:0}},'unknown']
])eq(cost(record),expected,'cost '+JSON.stringify(record));
for(const [mode,expected] of [['Online','online'],['offline','in-person'],['In-person','in-person'],['In person','in-person'],['hybrid','hybrid'],['Blended','hybrid'],['See organizer page','unknown'],['online/offline','unknown'],['online or in-person','unknown'],['','unknown']])eq(delivery({mode}),expected,'mode '+mode);
for(const [record,expected] of [
 [{type:'Workshop'},'workshop'],[{eventType:'workshop'},'workshop'],[{programType:'Paid hands-on workshop'},'workshop'],[{type:'Internship',programType:'Paid bootcamp with internship letter; not verified employment internship'},'training'],[{eventType:'Technical training'},'training'],[{programType:'Certificate course'},'training'],[{type:'Internship'},'unknown'],[{type:'Internship',summary:'No stipend established'},'unknown'],[{type:'Employment internship'},'employment'],[{eventType:'Internship (employment)'},'employment'],[{programType:'Internship role'},'employment'],[{type:'Employment internship',summary:'Not employment'},'unknown'],[{type:'Internship',description:'Not a verified employment internship'},'unknown'],[{type:'Employment internship',description:'Employment is not established.'},'unknown'],[{type:'Employment internship',summary:'No employment or stipend offer established.'},'unknown'],[{type:'Conference'},'other'],[{},'unknown'],[{type:'Opportunity',eventType:'Unknown'},'unknown']
])eq(type(record),expected,'type '+JSON.stringify(record));
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'catalog.json'),'utf8')).events;
const byId=id=>{const record=catalog.find(e=>e.id===id);assert.ok(record,'catalog fixture '+id);return record};
eq(cost(byId('nitw-ml-dl-2026')),'unknown','missing workshop fee is not free');
eq(type(byId('mea-internship-term2-2026')),'unknown','unqualified internship category is not employment');
eq(delivery(byId('iith-ai-agents-2026')),'hybrid','actual hybrid course');
const isl=byId('isl-winter-batch2-2027');eq(cost(isl),'paid','ISL fee');
const islTextOnly={...isl};delete islTextOnly.fee;delete islTextOnly.fees;eq(cost(islTextOnly),'paid','ISL ₹950 evidence in summary/description when fee fields absent');
const ids=filters=>catalog.filter(e=>matches(e,filters)).map(e=>e.id).sort();
eq(ids({cost:'paid',delivery:'online',programType:'training'}),['isl-winter-batch2-2027'],'three-way actual filter');
eq(ids({cost:'paid',delivery:'in-person',programType:'training'}),['techobytes-winter-bengaluru-2026','techobytes-winter-chennai-2026'],'paid training not employment');
eq(ids({cost:'unknown',delivery:'hybrid',programType:'training'}),['iith-ai-agents-2026'],'unknown fee and hybrid training');
eq(ids({cost:'paid',delivery:'online',programType:'workshop'}),['technocon-mnit-online-nov-2026'],'online paid workshop');
eq(ids({cost:'free'}),[],'no catalog record is inferred free');
eq(ids({programType:'employment'}),[],'no catalog record is inferred employment');
eq(ids({}),catalog.map(e=>e.id).sort(),'clearing filters restores full catalog');
// Execute the real render() against a bounded fake DOM: validates integration with existing filters and sections.
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,classList:{toggle(name,value){node(id).hidden=value}},closest(){return this}});return nodes.get(id)}
Object.assign(ctx,{$:node,events:catalog,saved:new Set(['nitw-ml-dl-2026']),normalizeDistrictLabel:v=>String(v||''),sortOpportunities:es=>es,opportunityStatus:e=>e.availabilityStatus||'Deadline unknown',renderCards:es=>es.map(e=>e.id).join(','),renderSavedCart:()=>{},renderRecommendations:()=>{},openSharedOpportunity:()=>{}});
vm.runInContext(html.slice(html.indexOf('function currentProgramFilters()'),html.indexOf('function programBadges(e)'))+html.slice(html.indexOf('function isCompany(e)'),html.indexOf('function resetVisible()'))+html.slice(html.indexOf('function render(){'),html.indexOf('function deadlineLabel(e)')),ctx);
node('providerFilter').value='company';node('costFilter').value='paid';node('deliveryFilter').value='in-person';node('programTypeFilter').value='training';ctx.render();
eq(node('resultCount').textContent,2,'render combines company plus all three new filters');
eq(node('companyCards').innerHTML,'techobytes-winter-chennai-2026,techobytes-winter-bengaluru-2026','render company matches');
eq(node('verifiedHeading').hidden,true,'company-only preserves institutional disclosure hiding');
eq(node('companyHeading').hidden,false,'company section remains visible');
eq(node('savedCount').textContent,1,'saved count stays independent');
node('providerFilter').value='institutional';ctx.render();eq(node('resultCount').textContent,0,'institutional filter excludes paid company training');eq(node('companyHeading').hidden,true,'institutional hides company section');
for(const id of ['providerFilter','costFilter','deliveryFilter','programTypeFilter'])node(id).value='';ctx.render();eq(node('resultCount').textContent,catalog.length,'cleared render restores catalog');
node('search').value='techobytes';node('state').value='Tamil Nadu';node('programTypeFilter').value='training';ctx.render();eq(node('resultCount').textContent,1,'new filters combine with existing search and state');
// Structural contracts guard event listeners, metadata, escaping, recommendations and provider disclosures.
for(const id of ['costFilter','deliveryFilter','programTypeFilter']){
 assert.match(html,new RegExp('<select id="'+id+'" aria-label="[^"]+" aria-describedby="programFilterHelp">'));assertions++;
 assert.match(html,new RegExp("'"+id+"'"));assertions++;
}
assert.match(html,/\['deadlineSort','availabilityFilter','providerFilter','costFilter','deliveryFilter','programTypeFilter','affiliationFilter'\]\.forEach\(id=>\$\(id\)\.addEventListener\('change',\(\)=>\{resetVisible\(\);render\(\)\}\)\)/);assertions++;
assert.match(html,/statusBadge\(e\)\+programBadges\(e\)/);assertions++;
assert.match(html,/modalMeta'\)\.innerHTML=programBadges\(e\)/);assertions++;
assert.match(html,/\[\.\.\.programLabels\(e\),affiliationLabel\(e\)\]\.map\(label=>'<span>'\+escapeHtml\(label\)/);assertions++;
assert.match(html,/opportunityStatus\(e\)!=='Closed'&&matchesProgramFilters\(e,currentProgramFilters\(\)\)/);assertions++;
assert.match(html,/independent of your dashboard filters/);assertions++;
assert.match(html,/Unknown is not assumed free or an employment internship/);assertions++;
assert.match(html,/not an employment offer/);assertions++;
console.log('PASS: '+assertions+' assertions; all inline scripts parse; '+catalog.length+' catalog records checked.');
