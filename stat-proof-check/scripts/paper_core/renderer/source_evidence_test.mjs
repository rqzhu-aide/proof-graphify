// Focused saved-evidence presentation tests. This is a deterministic adapter
// simulation, not a browser or a fresh scientific examination.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { renderProjection, validateInput, representationReceipt } from './render_projection.mjs';
import { scanHtml, textOf, decodeEntities, descendants } from './html_scan.mjs';
import { readerFixture } from './selftest.mjs';

const pin = ref => `${ref.collection}:${ref.id}:${ref.version}`;
const fixture = () => readerFixture();
const render = input => renderProjection(JSON.stringify(input), {fontStyle:''});
const evidence = scan => scan.elements.filter(row => Object.hasOwn(row.attrs, 'data-source-evidence'));
const links = scan => evidence(scan).flatMap(row => [...descendants(row)].filter(child => child.tag === 'a'));
function addReview(input, version = 1, id = 'srv_saved') {
  const p = input.projection, owner = p.nodes.find(row => row.kind === 'theorem');
  const detail = p.details[owner.detail_key], section = detail.sections.find(row => row.kind === 'coverage');
  const ref = {collection:'source_reviews',id,version};
  p.records.push({ref,body:{purpose:'Saved comparison',decision:'accepted',rationale:`Saved source review version ${version}. <source & evidence>`}});
  detail.record_refs.push(ref); section.record_refs.push(ref);
  p.record_locations.push({ref,detail_key:owner.detail_key,section_key:section.key});
  return ref;
}
function capture(input, sourceVersion = 1) {
  const anchor = input.projection.records.find(row => row.ref.collection === 'anchors');
  const note = {source_ref:{collection:'sources',id:anchor.body.source_id,version:sourceVersion},source_path:null,
    locator:{page:2,label:'<PDF & "text">',extra:{range:'α < β'}},description:'Captured <script> & $x$ lost \\alpha.',anchor_refs:[anchor.ref]};
  input.display ||= {}; input.display.source_capture_notes = [note];
  return note;
}

// Use the existing navigation adapter harness instead of a second resolver.
const harnessSource = readFileSync(new URL('./interaction_test.mjs', import.meta.url), 'utf8');
const harnessStart = harnessSource.indexOf('  const callbacks = new Map()');
const harnessEndText = '  vm.runInContext(runtimeText, context); flush();';
const harnessEnd = harnessSource.indexOf(harnessEndText) + harnessEndText.length;
assert(harnessStart >= 0 && harnessEnd > harnessStart);
const activate = new Function('assert','scan','decodeEntities','scripts','input','vm','searchScenario','native','expected',
  harnessSource.slice(harnessStart,harnessEnd) + `
  const disclosure = document.querySelector('[data-source-evidence]');
  const sourceLinks = disclosure.querySelectorAll('a');
  assert.equal(sourceLinks.length,expected.length);
  const activated = [];
  for(let index=0;index<sourceLinks.length;index++) {
    const link=sourceLinks[index], expectedRow=expected[index]; link.click(); flush();
    const target=document.querySelector('.is-target');
    assert(target,'Must reveal the saved record rather than only a result heading.');
    assert.equal(target.getAttribute('data-record-ref'),expectedRow.key);
    assert(target.closest('[data-proof-detail="'+link.getAttribute('data-jump-detail')+'"]'));
    assert(target.closest('[data-proof-section="'+link.getAttribute('data-jump-section')+'"]'));
    const shownRationale=target.querySelectorAll('[data-scientific-path]').find(field => field.getAttribute('data-scientific-path') === '["rationale"]');
    assert(shownRationale,'Navigation must reveal the rationale field.');
    assert.equal(shownRationale.textContent,new Element(row(expectedRow.rationaleElement)).textContent);
    for(let parent=target;parent;parent=parent.parentElement)
      if(parent.tagName==='details') assert(parent.hasAttribute('open'));
    activated.push(expectedRow.key);
  }
  return activated;`);
function activateLinks(input, scan) {
  const scripts = scan.elements.filter(row => row.tag === 'script' && row.attrs.type !== 'application/json');
  const native = scripts.find(row => row.text.includes('var Archify = {}'))?.text || '';
  const expected = links(scan).map(row => {
    const key = row.attrs['data-jump-record'];
    const template = scan.elements.find(element => element.attrs['data-record-template'] === key);
    const rationale = [...descendants(template)].find(element => element.attrs['data-scientific-path'] === '["rationale"]');
    assert(rationale,'The selected source review must retain its saved rationale field.');
    // Rendered mathematics replaces dollar delimiters. Compare the complete
    // accepted rationale surface using the same deterministic DOM adapter.
    return {key,rationaleElement:rationale};
  });
  return activate(assert,scan,decodeEntities,scripts,input,vm,null,native,expected);
}

const empty = fixture();
assert.deepEqual(validateInput(empty).sourceCaptureNotes, []);
assert.equal(evidence(scanHtml(render(empty).html)).length,0);
const onlyCapture = fixture(), note = capture(onlyCapture, 999), original = JSON.stringify(onlyCapture.projection);
const renderedCapture = render(onlyCapture), captureScan = scanHtml(renderedCapture.html);
assert.deepEqual(renderedCapture.model.sourceCaptureNotes, [note]);
assert.equal(JSON.stringify(onlyCapture.projection), original);
assert.equal(evidence(captureScan).length,1);
assert(!Object.hasOwn(evidence(captureScan)[0].attrs,'open'));
assert.equal(links(captureScan).length,0);
const noteElement = captureScan.elements.find(row => Object.hasOwn(row.attrs,'data-source-capture-note'));
for(const [attribute,field] of [['data-source-ref','source_ref'],['data-source-path','source_path'],['data-source-locator','locator'],['data-source-anchor-refs','anchor_refs']])
  assert.deepEqual(JSON.parse(noteElement.attrs[attribute]),note[field]);
const descriptionElement = [...descendants(noteElement)].find(row => Object.hasOwn(row.attrs,'data-source-capture-description'));
assert.equal(textOf(captureScan,descriptionElement),note.description);
const tamperedCapture = renderedCapture.html.slice(0,descriptionElement.openEnd) + 'Rewritten capture note.' + renderedCapture.html.slice(descriptionElement.closeStart);
assert.equal(representationReceipt(renderedCapture.model,scanHtml(tamperedCapture)).status,'fail');
assert(textOf(captureScan,[...descendants(noteElement)].find(row => Object.hasOwn(row.attrs,'data-source-capture-locator'))).includes('<PDF & "text">'));
assert(![...descendants(noteElement)].some(row => row.tag === 'script'));
const invalid = structuredClone(onlyCapture); invalid.display.source_capture_notes[0].description = ' ';
assert.throws(() => validateInput(invalid), /Input rejected/);

const explanatory = fixture(), explanationOwner = explanatory.projection.nodes.find(row => row.kind === 'theorem');
const explanationDetail = explanatory.projection.details[explanationOwner.detail_key];
const explanationRef = {collection:'saved_explanations',id:'saved_math',version:1};
const explanatoryFields = ['note','coverage_note','next_action','caption'];
const explanationBody = Object.fromEntries(explanatoryFields.map(field => [field,'Saved $x$ <tag> & prose.']));
const explanationFragment = 'Saved <math display="inline"><semantics><mi>x</mi><annotation encoding="application/x-tex">x</annotation></semantics></math> &lt;tag&gt; &amp; prose.';
explanatory.projection.records.push({ref:explanationRef,body:explanationBody});
explanationDetail.record_refs.push(explanationRef); explanationDetail.sections[0].record_refs.push(explanationRef);
explanatory.projection.record_locations.push({ref:explanationRef,detail_key:explanationOwner.detail_key,section_key:explanationDetail.sections[0].key});
explanatory.display.refs[pin(explanationRef)] = Object.fromEntries(explanatoryFields.map(field => [field+'_html',explanationFragment]));
const mathBefore = JSON.stringify(explanatory.projection), mathScan = scanHtml(render(explanatory).html);
for(const field of explanatoryFields) {
  const slot = mathScan.elements.find(row => row.attrs['data-scientific-ref'] === pin(explanationRef) && row.attrs['data-scientific-path'] === JSON.stringify([field]));
  assert(slot,field+' must be shown in the selected record');
  assert([...descendants(slot)].some(row => row.tag === 'math'));
  assert(textOf(mathScan,slot).includes('<tag> & prose.'));
}
assert.equal(JSON.stringify(explanatory.projection),mathBefore);

const reviews = fixture(), first = addReview(reviews), second = addReview(reviews,2);
// A later registry-only version cannot replace either selected pin.
reviews.projection.records.push({ref:{...first,version:9},body:{rationale:'Unlocated newer review'}});
reviews.projection.record_locations.push(structuredClone(reviews.projection.record_locations.find(row => pin(row.ref) === pin(first))));
let scan = scanHtml(render(reviews).html);
assert.deepEqual(links(scan).map(row => row.attrs['data-jump-record']),[pin(first),pin(second)]);
assert.equal(evidence(scan).length,1);
assert(!textOf(scan,evidence(scan)[0]).includes('Captured source text'));
assert.deepEqual(activateLinks(reviews,scan),[pin(first),pin(second)]);
const both = structuredClone(reviews); capture(both); scan = scanHtml(render(both).html);
assert.equal(evidence(scan).length,1);
assert(textOf(scan,evidence(scan)[0]).includes('Captured source text'));
assert(textOf(scan,evidence(scan)[0]).includes('Saved source-review notes'));

const conflicting = structuredClone(reviews), saved = conflicting.projection.record_locations.find(row => pin(row.ref) === pin(first));
const other = conflicting.projection.nodes.find(row => row.detail_key !== saved.detail_key);
const section = conflicting.projection.details[other.detail_key].sections[0];
conflicting.projection.record_locations.unshift({...saved,detail_key:other.detail_key,section_key:section.key});
assert.deepEqual(links(scanHtml(render(conflicting).html)).map(row => row.attrs['data-jump-record']),[pin(second)]);
const shared = structuredClone(reviews), owner = shared.projection.nodes.find(row => row.detail_key === saved.detail_key);
const sharedOwner = shared.projection.nodes.find(row => row.id !== owner.id);
sharedOwner.detail_key = owner.detail_key; sharedOwner.assessment = structuredClone(owner.assessment);
// Selection/labels are exercised without changing the saved scientific bodies.
const sharedScan = scanHtml(render(shared).html);
assert(links(sharedScan).every(row => textOf(sharedScan,row) === 'Source-review note'));
const unowned = structuredClone(reviews);
unowned.projection.details['saved:unowned'] = {record_refs:[first],sections:[{key:'saved',title:'Saved evidence',kind:'coverage',record_refs:[first],obligation_ids:[],note:null}]};
unowned.projection.record_locations.unshift({ref:first,detail_key:'saved:unowned',section_key:'saved'});
const unownedScan = scanHtml(render(unowned).html);
assert.equal(textOf(unownedScan,links(unownedScan)[0]),'Source-review note');
const escaped = structuredClone(reviews);
escaped.projection.nodes.find(row => row.detail_key === saved.detail_key).label = '<Lemma & "A">';
scan = scanHtml(render(escaped).html);
assert.equal(textOf(scan,links(scan)[0]),'Source-review note for <Lemma & "A">');

// Optional full saved-render input from a selected report. Each report is replayed
// separately so identical IDs from different reports never acquire new meaning.
const replays = [];
for (const filename of process.argv.slice(2)) {
  const input = JSON.parse(readFileSync(filename,'utf8')), before = JSON.stringify(input.projection);
  const result = render(input), parsed = scanHtml(result.html), activated = activateLinks(input,parsed);
  assert.equal(JSON.stringify(input.projection),before);
  const selectedNotes = input.display?.source_capture_notes || [];
  const shownNotes = parsed.elements.filter(row => Object.hasOwn(row.attrs,'data-source-capture-note'));
  assert.equal(shownNotes.length,selectedNotes.length);
  shownNotes.forEach((row,index) => assert.equal(textOf(parsed,[...descendants(row)].find(child => Object.hasOwn(child.attrs,'data-source-capture-description'))),selectedNotes[index].description));
  replays.push({input:filename,capture_notes:shownNotes.length,source_review_links:activated.length,activated});
}
console.log(JSON.stringify({ok:true,capture_notes:true,exact_pin_navigation:true,single_disclosure:true,replays}));
