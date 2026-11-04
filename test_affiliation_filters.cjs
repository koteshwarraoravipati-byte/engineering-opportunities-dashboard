'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const affiliation=html.split('// BEGIN AFFILIATION HELPERS')[1].split('// END AFFILIATION HELPERS')[0];
const program=html.split('// BEGIN PROGRAM FILTER HELPERS')[1].split('\n').slice(1).join('\n').split('// END PROGRAM FILTER HELPERS')[0];
const ctx=vm.createContext({});vm.runInContext(affiliation,ctx);vm.runInContext(program,ctx);
const official={sourceStatus:'verified',sourceType:'official_college',affiliationStatus:'officially_confirmed',companyPartner:'Example Ltd',companyRole:'Delivery partner',affiliationEvidenceUrl:'https://example.ac.in/programme'};
assert.equal(ctx.classifyAffiliation(official),'officially_confirmed');
for(const changes of [{sourceStatus:'unverified'},{sourceType:'company_provider'},{companyPartner:''},{companyRole:''},{affiliationEvidenceUrl:''},{affiliationEvidenceUrl:'https://example.ac.in.evil.test/programme'},{affiliationEvidenceUrl:'https://example.ac.in@evil.test/'},{affiliationEvidenceUrl:'http://example.ac.in/programme'}])assert.equal(ctx.classifyAffiliation({...official,...changes}),'unknown');
assert.equal(ctx.classifyAffiliation({title:'Official IIT NIT collaboration with Company',sourceStatus:'verified',sourceUrl:'https://example.ac.in/'}),'unknown','branding and verified source alone do not prove a company tie');
assert.equal(ctx.classifyAffiliation({sourceType:'company_provider'}),'company_advertised');
assert.equal(ctx.classifyAffiliation({...official,affiliationStatus:'venue_only'}),'venue_only');
assert.equal(ctx.classifyAffiliation({...official,affiliationStatus:'company_advertised'}),'company_advertised');
assert.equal(ctx.classifyAffiliation({...official,affiliationStatus:'unknown'}),'unknown');
const published=JSON.parse(fs.readFileSync(path.join(__dirname,'data/institute_company_opportunities_2026-11-04.json'),'utf8')).records;
for(const e of published)assert.equal(ctx.classifyAffiliation(e),'officially_confirmed',e.id);
assert.equal(ctx.classifyAffiliation({...published[0],sourceUrl:'https://other.ac.in/'}),'unknown','legacy evidence pinned to exact record and source');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'catalog.json'),'utf8')).events;
const counts={};for(const e of [...catalog,...published]){const key=ctx.classifyAffiliation(e);counts[key]=(counts[key]||0)+1;}
assert.equal(counts.officially_confirmed,10);assert.equal(counts.venue_only,3);assert.equal(counts.company_advertised,3);
assert.equal(ctx.matchesProgramFilters(official,{affiliation:'officially_confirmed'}),true);
assert.equal(ctx.matchesProgramFilters(official,{affiliation:'venue_only'}),false);
assert.match(html,/affiliationFilter/);assert.match(html,/affiliationLabel\(e\)/);
console.log('PASS: affiliation metadata, legacy evidence, unknown-safe defaults, spoof-resistant URLs, filter composition and counts',counts);

const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,classList:{toggle(name,value){node(id).hidden=value}},closest(){return this}});return nodes.get(id)}
Object.assign(ctx,{$:node,events:[...catalog,...published],saved:new Set(['saved-independent']),normalizeDistrictLabel:v=>String(v||''),sortOpportunities:es=>es,opportunityStatus:e=>'Open',renderCards:es=>es.map(e=>e.id).join(','),renderSavedCart:()=>{},renderRecommendations:()=>{},openSharedOpportunity:()=>{}});
vm.runInContext(html.slice(html.indexOf('function currentProgramFilters()'),html.indexOf('function programBadges(e)'))+html.slice(html.indexOf('function isCompany(e)'),html.indexOf('function resetVisible()'))+html.slice(html.indexOf('function render(){'),html.indexOf('function deadlineLabel(e)')),ctx);
node('affiliationFilter').value='officially_confirmed';ctx.render();assert.equal(node('resultCount').textContent,10);assert.equal(node('providerDirectoryHeading').hidden,true);assert.equal(node('savedCount').textContent,1);
node('providerFilter').value='company';ctx.render();assert.equal(node('resultCount').textContent,0,'provider and affiliation filters compose rather than broadening');
node('affiliationFilter').value='venue_only';ctx.render();assert.equal(node('resultCount').textContent,3);
node('affiliationFilter').value='company_advertised';ctx.render();assert.equal(node('resultCount').textContent,3);
node('providerFilter').value='';node('affiliationFilter').value='';ctx.render();assert.equal(node('resultCount').textContent,87);assert.equal(node('providerDirectoryHeading').hidden,false);
console.log('PASS: real render() respects affiliation/provider combinations, directory visibility, reset and Saved independence');
