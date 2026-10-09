import test from 'node:test';
import assert from 'node:assert/strict';
import { createReaderContent } from './reader_content.mjs';

const target = (collection,id) => ({collection,id});
const pin = (collection,id,version=1) => ({collection,id,version});
const statement = text => ({form:'verbatim',text});
const literal = 'For every x in D, require k = 0xabcdef0123456789abcdef0123456789 and itm_symbol > 0; the negative case is unproved.';

// Bodies use the current contract's actual structured fields, including record
// types and nonempty values absent from the KEDRL experiment inputs.
function fixture() {
  const records=[], put=(collection,id,body,version=1) => {
    const row={ref:pin(collection,id,version),body}; records.push(row); return row;
  };
  put('papers','paper',{title:'Constrained estimates',source_root:'.',main_items:['claim'],report_paths:[],scope:'Positive-domain claims only.',exclusions:['Boundary equality is outside the paper scope.']});
  put('sources','source',{paper_id:'paper',path:'original.tex',media_type:'tex',blob_sha256:'a'.repeat(64),capture_method:'source',limitation:'The supplemental derivation is unavailable.'});
  put('sources','source',{paper_id:'paper',path:'revised.tex',media_type:'tex',blob_sha256:'b'.repeat(64),capture_method:'source',limitation:null},2);
  const excerpt='😀ABC mathematical proof span ends here.';
  put('anchors','anchor',{source_id:'source',source_version:1,locator:{start_line:10,end_line:12,page:null,label:'proof'},excerpt,excerpt_sha256:'c'.repeat(64),method:'exact_lines',limitation:'The last line is truncated in the supplied source.'});
  put('items','assumption',{kind:'assumption',label:'Assumption A',caption:'Integrability',statement:statement('For all x > 0, E|X| < infinity.'),passages:[{role:'statement',anchor_id:'anchor'}],aliases:[],uncertainty:null,origin:'source',owner_id:null,scope_id:null});
  put('items','claim',{kind:'theorem',label:'Theorem 2',caption:'Conditional bound',statement:statement('For every x > 0, P(X > x) <= 1/x under Assumption A.'),passages:[{role:'proof',anchor_id:'anchor'}],aliases:[],uncertainty:'The x = 0 case is excluded.',origin:'source',owner_id:null,scope_id:'scope',proof_idea:'Apply the integrable majorant from Assumption A.'});
  put('items','claim',{kind:'theorem',label:'Theorem 2',caption:'Conditional bound',statement:{form:'synopsis',text:'A later synopsis omits the positive-domain restriction.'},passages:[],aliases:[],uncertainty:null,origin:'source',owner_id:null,scope_id:'scope'},2);
  put('parts','part',{item_id:'claim',label:'Part (ii)',statement:statement('If x > 0 and y >= 1, then xy > 0.'),passages:[{role:'proof',anchor_id:'anchor'}],scope_id:'scope',origin:'source'});
  put('scopes','scope',{argument_id:'argument',parent_id:null,assumptions:[target('items','assumption')],binders:[{symbol:'x',domain:'positive reals',quantifier:'forall'},{symbol:'y',domain:'[1, infinity)',quantifier:'exists'}],conditions:['x > 0','y >= 1'],evidence_refs:['anchor']});
  put('arguments','argument',{target:target('parts','part'),label:'Proof of Part (ii)',origin:'source',scope_id:'scope',final_group_id:'group',evidence_refs:['anchor'],lifecycle:'registered'});
  put('groups','group',{argument_id:'argument',conclusion:target('parts','part'),kind:'cases',scope_id:'scope',case_scope_ids:['scope'],discharges:['scope'],rationale:'Use the positive case, then discharge its local assumption.',evidence_refs:['anchor']});
  put('uses','use',{from:target('items','assumption'),to:target('parts','part'),type:'dependency',reason:'Supplies integrability for the positive-domain argument.',evidence_refs:['anchor'],regime:'Only x > 0.',uncertainty:'The boundary case is not supplied.'});
  put('uses','summary',{from:target('items','assumption'),to:target('items','claim'),type:'dependency',reason:'Summary of the detailed positive-domain applications.',evidence_refs:[],regime:null,uncertainty:null});
  put('application_details','application',{use_id:'use',group_id:'group',needed_form:statement('E|X| < infinity at x > 0.'),substitutions:[{symbol:'t',value:'x / y'},{symbol:'q',value:'0xabcdef0123456789'}],scope_id:'scope',state:'registered'});
  put('target_specs','exact',{target:target('items','claim'),statement_ref:pin('items','claim'),statement:null,scope_id:'scope',evidence_refs:['anchor'],state:'registered',fidelity_ref:pin('observations','comparison')});
  put('connection_refinements','refinement',{summary_use_id:'summary',argument_id:'argument',use_ids:['use'],state:'registered',note:'The summary uses the conjunction of the two local conditions.'});
  put('proof_boundaries','boundary',{target:target('parts','part'),argument_ids:['argument'],anchor_refs:[pin('anchors','anchor')],source_review_ref:pin('source_reviews','source_review'),state:'complete'});
  put('coverage','structural',{argument_id:'argument',anchor_id:'anchor',start_offset:0,end_offset:4,classification:'structural',claim_refs:[],check_ids:[],note:''});
  put('coverage','substantive',{argument_id:'argument',anchor_id:'anchor',start_offset:5,end_offset:28,classification:'substantive',claim_refs:[target('parts','part')],check_ids:['check'],note:'The positive case was examined; the equality case was excluded.'});
  put('observations','comparison',{target:target('items','claim'),result:'needs_attention',reviewer:'reviewer',note:'The saved synopsis drops x > 0 and must not replace the exact statement.',evidence_refs:['anchor']});
  put('source_issues','source_issue',{source_id:'source',anchor_id:'anchor',category:'locator_limit',description:'The supplied proof passage cuts off before the boundary argument.',lifecycle:'open',resolution:null,reviewer:'reviewer'});
  put('source_reviews','source_review',{source_refs:[pin('sources','source')],anchor_refs:[pin('anchors','anchor')],purpose:'proof_boundary',decision:'accepted',rationale:'Only the positive case occurs in the supplied proof boundary.',reviewer:'reviewer',proof_spans:[{argument_ref:pin('arguments','argument'),anchor_ref:pin('anchors','anchor'),start_offset:5,end_offset:28}]});
  put('audits','audit',{paper_id:'paper',mode:'focused',targets:[target('parts','part')],exclusions:[{target:target('items','claim'),source_anchor_ids:['anchor'],reason:'The source does not contain the boundary proof.',consequence:'No conclusion about x = 0 is established.'}],protocol_version:'coherent-proof-audit/1',independent_required:true,qualification_id:'qualification',global_tasks:[{kind:'global_consistency',applicability:'required',reason:''},{kind:'adversarial',applicability:'required',reason:''},{kind:'method_interface',applicability:'required',reason:''}],report_path:'report.html'});
  const check={audit_id:'audit',target:target('arguments','argument'),kind:'composition',role:'primary',reviewer:'reviewer',protocol_version:'coherent-proof-audit/1',state:'complete',outcome:'gap',reasoning:literal,evidence_refs:['anchor'],conditions:['Assume x > 0; the estimate fails at x = 0.'],next_action:'A repair would require a boundary argument.',response_id:null,supersedes:null,extent:'partial',omissions:'No argument for x = 0 is supplied.'};
  put('checks','check',check);
  put('checks','successor',{...check,reasoning:'Successor assessment still needs a boundary argument.',supersedes:pin('checks','check')});
  put('checks','independent',{...check,role:'independent',response_id:'response',reasoning:'The apparent proof still lacks the excluded equality case.'});
  put('findings','finding',{audit_id:'audit',target:target('parts','part'),category:'proof_gap',lifecycle:'resolved',description:'The equality case does not follow from the positive-case estimate.',evidence_refs:['anchor'],check_refs:[pin('checks','check')],affected_uses:['use'],impact_reason:'Only the restricted positive-domain form has support.',resolution:'Duplicate records were consolidated, but the itm_symbol > 0 condition and boundary gap remain.'});
  put('repairs','repair',{finding_id:'finding',kind:'restricted_statement',description:'Restrict the claim to the positive domain.',supported_form:target('parts','part'),argument_id:null,added_conditions:['x > 0','The limit x = 0 is excluded.'],evidence_refs:['anchor']});
  put('qualifications','qualification',{reviewer:'reviewer',profile:{provider:'provider',model:'model',effort:null,tools:[],context_isolation:'separate'},protocol_version:'coherent-proof-audit/1',valid_case_results:[],invalid_case_results:[],evidence_blob:'d'.repeat(64),qualified:false,limitations:['No calibration result supports independent qualification.']});
  put('responses','response',{audit_id:'audit',packet_id:'packet',reviewer:'reviewer',qualification_id:'qualification',original_blob:'e'.repeat(64),covered_targets:[target('parts','part')],coverage_note:'Only the positive-domain part was examined.',exposure:'route_provided',exposure_note:'A proposed solution was supplied; alternative routes may not have been challenged.',state:'needs_revision',intake_diagnostics:[],pending_judgments:[0,2]});
  put('reconciliations','combined',{audit_id:'audit',target:target('parts','part'),primary_checks:[pin('checks','check')],independent_checks:[pin('checks','independent')],decision:'unresolved',rationale:'Both views leave the boundary case unresolved.',evidence_refs:['anchor'],successor_checks:[pin('checks','successor')],supersedes:null,adjudicator:'coordinator',response_dispositions:[{response_ref:pin('responses','response'),judgment_indexes:[0,2],rationale:'The returned judgments apply only to x > 0; their boundary criticism remains unresolved.'}]});
  put('reuse_decisions','reuse',{check_ref:pin('checks','check'),source_review_id:'source_review',decision:'recheck',rationale:'The revised source removes the integrability premise, so the older assessment cannot be reused.',evidence_refs:['anchor']});
  put('identity_maps','mapping',{reason:'response_mapping',source_blob:null,response_id:'response',entries:[{old:'old-target',new_refs:[target('parts','part')],rationale:'The returned statement refers to the positive-domain part.'}],reviewer:'coordinator',note:'The mathematical target was interpreted as the restricted part.'});
  put('overview_selections','overview',{paper_id:'paper',title:'Positive-domain overview',scope:'Only supplied positive-domain claims.',item_ids:['claim'],use_ids:['summary'],main_item_ids:['claim'],source_ids:['source'],authoring_profile:null,roots:[],unresolved:['The boundary source is missing.']});
  return {records,worklist:{tasks:[{judgment_refs:[pin('checks','successor')],draft_refs:[],freshness:'needs_review'}]}};
}

const get = (projection,collection,id,version=1) => projection.records.find(row => row.ref.collection===collection && row.ref.id===id && row.ref.version===version);
const field = (content,collection,id,path) => content.record(pin(collection,id)).fields.find(row=>JSON.stringify(row.path)===JSON.stringify(path));

test('exact pinned statements, proof parts, origin and source versions retain their meaning',()=>{
  const p=fixture(), content=createReaderContent(p), exact=content.record(pin('target_specs','exact'));
  const saved=exact.fields.find(row=>row.label==='Pinned statement examined');
  assert.equal(saved.value.text,'For every x > 0, P(X > x) <= 1/x under Assumption A.');
  assert.deepEqual(saved.sourceRef,pin('items','claim'));
  assert.equal(content.resolve(pin('items','claim',3)),null);
  assert.equal(content.title(pin('anchors','anchor')),'original.tex, proof, lines 10 to 12');
  assert.equal(field(content,'parts','part',['statement']).value.text,'If x > 0 and y >= 1, then xy > 0.');
  get(p,'items','claim').body.origin='proposed_repair';
  assert.equal(createReaderContent(p).record(pin('items','claim')).fields.find(row=>row.path[0]==='statement').label,'Proposed repaired statement');
  get(p,'target_specs','exact').body.statement_ref=pin('items','claim',9);
  const unavailable=createReaderContent(p).record(pin('target_specs','exact'));
  assert.ok(unavailable.notices.some(note=>note.includes('pinned statement')));
  assert.ok(!JSON.stringify(unavailable).includes('later synopsis'));
});

test('actual nonempty application, refinement and repair structures survive with context',()=>{
  const p=fixture(), content=createReaderContent(p);
  assert.deepEqual(field(content,'scopes','scope',['binders']).value,[{symbol:'x',domain:'positive reals',quantifier:'forall'},{symbol:'y',domain:'[1, infinity)',quantifier:'exists'}]);
  assert.deepEqual(field(content,'application_details','application',['substitutions']).value,[{symbol:'t',value:'x / y'},{symbol:'q',value:'0xabcdef0123456789'}]);
  assert.equal(field(content,'application_details','application',['needed_form']).value.text,'E|X| < infinity at x > 0.');
  assert.equal(field(content,'connection_refinements','refinement',['note']).value,'The summary uses the conjunction of the two local conditions.');
  assert.deepEqual(field(content,'connection_refinements','refinement',['summary_use_id']).value,target('uses','summary'));
  assert.deepEqual(field(content,'groups','group',['discharges']).value,[target('scopes','scope')]);
  const repair=content.record(pin('repairs','repair'));
  assert.deepEqual(field(content,'repairs','repair',['added_conditions']).value,['x > 0','The limit x = 0 is excluded.']);
  assert.ok(repair.notices.some(note=>note.includes('does not establish')));
  assert.ok(content.text(pin('repairs','repair')).includes('If x > 0 and y >= 1, then xy > 0.'));
});

test('structural and substantive coverage expose exact codepoint spans and claim context',()=>{
  const content=createReaderContent(fixture()), structural=content.record(pin('coverage','structural')), substantive=content.record(pin('coverage','substantive'));
  const span=structural.fields.find(row=>row.slice);
  assert.equal(span.value,'😀ABC');
  assert.deepEqual(span.slice,{start:0,end:4});
  assert.deepEqual(span.sourceRef,pin('anchors','anchor'));
  assert.ok(structural.notices.some(note=>note.includes('does not mean its mathematics was examined')));
  assert.equal(substantive.fields.find(row=>row.slice).value,'mathematical proof span');
  assert.deepEqual(field(content,'coverage','substantive',['claim_refs']).value,[target('parts','part')]);
  assert.deepEqual(field(content,'coverage','substantive',['check_ids']).value,[target('checks','check')]);
  assert.equal(content.record(pin('source_reviews','source_review')).fields.find(row=>row.slice).value,'mathematical proof span');
  assert.ok(content.record(pin('proof_boundaries','boundary')).notices.some(note=>note.includes('does not by itself establish mathematical support')));
});

test('adverse, partial, earlier and stale assessments keep exact reasoning and limitations',()=>{
  const content=createReaderContent(fixture()), old=content.record(pin('checks','check')), current=content.record(pin('checks','successor'));
  assert.equal(field(content,'checks','check',['reasoning']).value,literal);
  assert.equal(field(content,'checks','check',['outcome']).value,'gap');
  assert.equal(field(content,'checks','check',['omissions']).value,'No argument for x = 0 is supplied.');
  assert.equal(field(content,'checks','check',['next_action']).value,'A repair would require a boundary argument.');
  assert.ok(old.notices.some(note=>note.includes('Earlier assessment')));
  assert.ok(old.notices.some(note=>note.includes('partial')));
  assert.ok(current.notices.some(note=>note.includes('requires current review')));
  assert.equal(field(content,'findings','finding',['resolution']).value,'Duplicate records were consolidated, but the itm_symbol > 0 condition and boundary gap remain.');
  assert.ok(content.text(pin('checks','check')).includes(literal));
});

test('review integration preserves returned rationale, consequential exposure and reuse',()=>{
  const content=createReaderContent(fixture());
  assert.equal(field(content,'reconciliations','combined',['response_dispositions',0,'rationale']).value,'The returned judgments apply only to x > 0; their boundary criticism remains unresolved.');
  assert.equal(field(content,'reuse_decisions','reuse',['rationale']).value,'The revised source removes the integrability premise, so the older assessment cannot be reused.');
  assert.equal(field(content,'responses','response',['exposure_note']).value,'A proposed solution was supplied; alternative routes may not have been challenged.');
  assert.ok(content.title(pin('checks','independent')).startsWith('Additional assessment:'));
  const response=content.record(pin('responses','response'));
  assert.ok(response.notices.some(note=>note.includes('substantive contents are not present')));
  assert.ok(!response.fields.some(row=>row.path[0]==='pending_judgments'));
  assert.equal(field(content,'audits','audit',['exclusions',0,'consequence']).value,'No conclusion about x = 0 is established.');
  assert.equal(field(content,'identity_maps','mapping',['entries',0,'rationale']).value,'The returned statement refers to the positive-domain part.');
});

test('older compatible applications and unknown shapes retain useful science with an honest limitation',()=>{
  const p=fixture();
  Object.assign(get(p,'uses','use').body,{group_id:'group',needed_form:statement('The historical required form retains x > 0.'),substitutions:[{symbol:'z',value:'x^2'}]});
  get(p,'items','claim').body.passages=['anchor'];
  p.records.push({ref:pin('older_review','older'),body:{reasoning:literal,conditions:['x > 0'],job_id:'administrative-secret',unmapped_payload:{job:'ignore'}}});
  const content=createReaderContent(p), older=content.record(pin('older_review','older'));
  assert.equal(field(content,'uses','use',['needed_form']).value.text,'The historical required form retains x > 0.');
  assert.deepEqual(field(content,'items','claim',['passages',0]).value,target('anchors','anchor'));
  assert.ok(older.notices.some(note=>note.includes('limited scientific display')));
  assert.ok(content.text(pin('older_review','older')).includes(literal));
  assert.ok(!JSON.stringify(older).includes('administrative-secret'));
});

test('coherent review without optional calibration and accepted supplied-route review remain independent',()=>{
  const p=fixture(), response=get(p,'responses','response');
  Object.assign(response.body,{qualification_id:null,exposure:'source_only',state:'accepted',pending_judgments:[]});
  const blind=createReaderContent(p);
  assert.equal(blind.title(pin('responses','response')),'Independent review response');
  assert.ok(blind.title(pin('checks','independent')).startsWith('Independent assessment:'));
  assert.ok(!blind.record(pin('responses','response')).notices.some(note=>note.includes('qualification')));
  response.body.exposure='route_provided';
  p.obligations=[{assessment:{independent_review:'complete',check_refs:[pin('checks','independent')]}}];
  const supplied=createReaderContent(p);
  assert.ok(supplied.title(pin('checks','independent')).startsWith('Independent assessment with supplied argument context:'));
  assert.ok(supplied.record(pin('checks','independent')).notices.some(note=>note.includes('supplied argument context')));
  assert.ok(!supplied.record(pin('checks','independent')).notices.some(note=>note.includes('must not') || note.includes('does not establish a qualified')));
});

test('shared cyclic references do not expand search text into unrelated report reasoning',()=>{
  const p=fixture();
  for(let i=0;i<400;i++) p.records.push({ref:pin('groups',`dense${i}`),body:{argument_id:'argument',conclusion:target('parts','part'),kind:'joint',scope_id:'scope',case_scope_ids:[],discharges:[],rationale:`Local dense inference ${i}.`,evidence_refs:['anchor']}});
  const content=createReaderContent(p), texts=p.records.map(row=>content.text(row));
  assert.ok(texts.reduce((sum,text)=>sum+text.length,0)<350000);
  const own=content.text(pin('groups','dense399'));
  assert.ok(own.includes('Local dense inference 399.'));
  assert.ok(!own.includes('Local dense inference 398.'));
  assert.ok(!own.includes(literal));
  assert.ok(content.text(pin('scopes','scope')).includes('For all x > 0, E|X| < infinity.'));
  assert.ok(!own.includes('packet'));
});

export { fixture as readerContentFixture };
