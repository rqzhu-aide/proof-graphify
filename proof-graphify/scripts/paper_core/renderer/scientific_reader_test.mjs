// Shared display contract checks. This is not a browser or visual review.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { adaptScientificReaderTemplate, archifyPage, resultsNavigation, mathDisplayNotes,
  readerRuntime, readerSearchData, decodeReaderSearchData, SCIENTIFIC_READER_CSS, sourceDisclosure, nearestProofRelationship } from './scientific_reader.mjs';
import { layoutGraph, renderProjection, validateInput } from './render_projection.mjs';
import { scanHtml } from './html_scan.mjs';
import { readerFixture } from './selftest.mjs';

const pinnedKey = ref => `${ref.collection}:${ref.id}:${ref.version}`;

test('source prerequisites sit beside the earliest consumer including hypothesis connections', () => {
  const edges = pairs => pairs.map(([from, to], i) => ({id:`edge_${i}`, from, to}));
  const model = {nodeList:['a','b','c','t','late','setup','shared','isolated'].map(id => ({id})),
    connectionList:edges([['a','b'],['b','c'],['c','t'],['late','t'],['late','t'],['shared','t']]),
    layout:{mode:'dag'}};
  model.graphConnectionList = [...model.connectionList,
    {id:'setup_use',from:'setup',to:'c',kind:'setup'},
    {id:'shared_hypothesis',from:'shared',to:'b',kind:'hypothesis'}];
  const saved = JSON.stringify(model), graph = layoutGraph(model);
  assert.deepEqual(Object.fromEntries([...graph.nodes].map(([id,node]) => [id,node.rank])),
    {a:0,b:1,c:2,t:3,late:2,setup:1,shared:0,isolated:0});
  for (const edge of model.graphConnectionList)
    assert(graph.nodes.get(edge.from).rank < graph.nodes.get(edge.to).rank);
  assert.deepEqual([...graph.nodes.values()].filter(node => node.component === graph.nodes.get('a').component && node.rank === 0)
    .map(node => node.id), ['a','shared'], 'Late prerequisites should no longer occupy the first column.');
  assert.equal(JSON.stringify(model), saved, 'Layout must not change recorded nodes or connections.');
  assert.deepEqual([...layoutGraph(model).nodes.values()], [...graph.nodes.values()]);
});

test('cycle members and isolated nodes retain their ranks while a true source moves beside its use', () => {
  const model = {nodeList:['q','x','y','z','isolated'].map(id => ({id})),
    connectionList:[['q','x'],['x','y'],['y','q'],['z','y']]
      .map(([from,to],i) => ({id:`cycle_${i}`,from,to})), layout:{mode:'cyclic'}};
  const graph = layoutGraph(model);
  assert.deepEqual(Object.fromEntries([...graph.nodes].map(([id,node]) => [id,node.rank])),
    {q:0,x:1,y:2,z:1,isolated:0});
  assert.deepEqual([...graph.feedback], ['cycle_2']);
  assert.equal(graph.outgoing.get('y')[0].to, 'q', 'The return arrow is preserved.');
});

function relocatedEvidenceFixture() {
  const input = readerFixture(), projection = input.projection;
  const major = projection.nodes.find(node => node.kind === 'theorem');
  const earlier = projection.nodes.find(node => node.kind === 'definition');
  const own = projection.details[major.detail_key], other = projection.details[earlier.detail_key];
  const argument = own.reader.arguments.find(row => row.relation === 'target');
  const hidden = own.reader.arguments.find(row => row.relation === 'subsidiary').target_ref;
  own.reader.targets.push({...own.reader.targets[0],target_ref:hidden,statement_ref:hidden});
  const observation = {collection:'observations',id:'obs_navigation',version:1};
  projection.records.push({ref:observation,body:{label:'Source comparison',target:{collection:hidden.collection,id:hidden.id},evidence_refs:[]}});
  own.record_refs.push(observation);
  // A different owner section catches accidental reuse of the downstream section key.
  own.sections.push({key:'source_comparison',kind:'sources',title:'Source comparison',record_refs:[observation],obligation_ids:[]});
  projection.record_locations.push({ref:observation,detail_key:major.detail_key,section_key:'source_comparison'});
  const owned = [argument.argument_ref,argument.groups[0].group_ref,observation];
  const oldArgument = {...argument.argument_ref,version:2};
  projection.records.push({ref:oldArgument,body:{label:'Historical argument'}});
  projection.record_locations.push({ref:oldArgument,detail_key:earlier.detail_key,section_key:other.sections[0].key});
  for (const ref of [...owned,oldArgument]) {
    other.record_refs.push(ref); other.sections[0].record_refs.push(ref);
    Object.assign(projection.record_locations.find(row => pinnedKey(row.ref) === pinnedKey(ref)),
      {detail_key:earlier.detail_key,section_key:other.sections[0].key});
  }
  return {input,projection,major,earlier,own,other,owned,hidden,oldArgument};
}

test('dense proof relation picking uses visible strokes rather than overlapping hit rail order', () => {
  const svg = {querySelector:()=>true, getScreenCTM:()=>({inverse:()=>({})}), createSVGPoint:()=>({matrixTransform(){return {x:this.x/2,y:this.y/2};}})};
  const shape = d => ({getAttribute:()=>d});
  const records = [{key:'first',shapes:[shape('M0 0 L100 0')]},{key:'second',shapes:[shape('M0 3 L100 3')]}];
  assert.equal(nearestProofRelationship({detail:1,clientX:100,clientY:0.4},svg,records),'first');
  assert.equal(nearestProofRelationship({detail:1,clientX:100,clientY:5.6},svg,records),'second');
  assert.equal(nearestProofRelationship({detail:0},svg,records),null, 'Keyboard activation retains its selected relationship.');
  assert.equal(nearestProofRelationship({detail:1}, {...svg,querySelector:()=>null},records),null, 'Other diagrams retain native picking.');
});

test('result links select the exact major card while historical and hidden records retain evidence destinations', () => {
  const pin = ref => `${ref.collection}:${ref.id}:${ref.version}`;
  for (const mode of ['dag', 'index']) {
    const input = readerFixture(), projection = input.projection;
    projection.layout.mode = mode;
    const major = projection.nodes.find(node => node.kind === 'theorem');
    const earlier = projection.nodes.find(node => node.kind === 'definition');
    const own = projection.details[major.detail_key], other = projection.details[earlier.detail_key];
    const old = {...major.item_ref, version:1};
    for (const ref of [major.item_ref, old]) {
      other.record_refs.push(ref);
      other.sections[0].record_refs.push(ref);
      Object.assign(projection.record_locations.find(row => pin(row.ref) === pin(ref)),
        {detail_key:earlier.detail_key, section_key:other.sections[0].key});
    }
    const hidden = own.reader.arguments.find(argument => argument.relation === 'subsidiary').target_ref;
    for (const ref of [major.item_ref, old, hidden]) {
      own.reader.applications[0].from_ref = ref;
      const before = JSON.stringify(projection);
      const {html} = renderProjection(Buffer.from(JSON.stringify(input)));
      const scan = scanHtml(html);
      const entries = decodeReaderSearchData(JSON.parse(scan.elements.find(element => element.attrs.id === 'proof-reader-search').text));
      for (const searched of [major.item_ref, old, hidden]) {
        const entry = entries.find(row => row.key === pin(searched));
        const recorded = projection.record_locations.find(row => pin(row.ref) === pin(searched));
        const isCurrent = pin(searched) === pin(major.item_ref);
        assert(entry, 'Pinned scientific records must remain searchable.');
        assert.equal(entry.detail, isCurrent ? major.detail_key : recorded.detail_key);
        assert.equal(entry.section, isCurrent ? null : recorded.section_key,
          'Rerouted current results must not retain a section from the evidence owner.');
        assert.equal(entry.owner, isCurrent ? major.label : searched === hidden ? major.label : earlier.label);
        assert(entry.aliases.includes(pin(searched)) && entry.aliases.includes(searched.id));
        assert.equal(entry.isDirectResult, isCurrent);
      }
      const label = scan.elements.find(element => element.attrs['data-reader-context'] === 'application:0:from'
        && element.attrs['data-reader-field'] === 'label');
      const location = projection.record_locations.find(row => pin(row.ref) === pin(ref));
      const current = pin(ref) === pin(major.item_ref);
      assert.equal(label.parent.attrs['data-jump-detail'], current ? major.detail_key : location.detail_key);
      assert.equal(label.attrs['data-reader-ref'], pin(ref));
      if (current) {
        assert(!label.parent.attrs['data-jump-record'], 'Named result links open the card rather than its evidence appendix.');
        const links = scan.elements.filter(element => element.tag === 'a' && element.attrs['data-jump-record'] === pin(ref));
        assert(links.length > 0);
        assert(links.every(link => link.attrs['data-jump-detail'] === major.detail_key));
      } else {
        assert.equal(label.parent.attrs['data-jump-record'], pin(ref));
        assert.equal(label.parent.attrs['data-jump-section'], location.section_key);
      }
      assert.equal(JSON.stringify(projection), before, 'Navigation must not change the scientific payload.');
    }
    // Legacy payloads may link a current result without listing it in the search inventory.
    projection.record_locations = projection.record_locations.filter(row => pin(row.ref) !== pin(major.item_ref));
    own.reader.applications[0].from_ref = major.item_ref;
    const scan = scanHtml(renderProjection(Buffer.from(JSON.stringify(input))).html);
    const named = scan.elements.find(row => row.attrs['data-reader-context'] === 'application:0:from' && row.attrs['data-reader-field'] === 'label');
    assert.equal(named.parent.attrs['data-jump-detail'],major.detail_key);
    const links = scan.elements.filter(row => row.tag === 'a' && row.attrs['data-jump-record'] === pin(major.item_ref));
    assert(links.length && links.every(row => row.attrs['data-jump-detail'] === major.detail_key));
    const entries = decodeReaderSearchData(JSON.parse(scan.elements.find(row => row.attrs.id === 'proof-reader-search').text));
    assert(!entries.some(row => row.key === pin(major.item_ref)), 'Navigation must not expand a legacy search inventory.');
  }
});

test('owned proof evidence shares exact destinations across search, record and named links', () => {
  for (const mode of ['dag','index']) {
    const {input,projection,major,own,owned,oldArgument} = relocatedEvidenceFixture();
    projection.layout.mode = mode;
    for (const ref of owned) {
      own.reader.applications[0].from_ref = ref;
      const before = JSON.stringify(projection);
      const {html,receipt} = renderProjection(Buffer.from(JSON.stringify(input)));
      assert.equal(receipt.representation.status,'pass');
      const scan = scanHtml(html), entries = decodeReaderSearchData(JSON.parse(scan.elements.find(row => row.attrs.id === 'proof-reader-search').text));
      for (const evidence of owned) {
        const key = pinnedKey(evidence), entry = entries.find(row => row.key === key);
        const section = own.sections.find(row => row.record_refs.some(value => pinnedKey(value) === key)).key;
        assert.equal(entry.detail,major.detail_key);
        assert.equal(entry.section,section);
        assert.equal(entry.isDirectResult,false);
        const links = scan.elements.filter(row => row.tag === 'a' && row.attrs['data-jump-record'] === key);
        if (key === pinnedKey(ref) || evidence.collection !== 'observations') assert(links.length);
        for (const link of links) {
          assert.equal(link.attrs['data-jump-detail'],major.detail_key);
          assert.equal(link.attrs['data-jump-section'],section);
        }
      }
      const history = entries.find(row => row.key === pinnedKey(oldArgument));
      assert.equal(history.detail,projection.record_locations.find(row => pinnedKey(row.ref) === history.key).detail_key);
      assert.equal(JSON.stringify(projection),before);
    }
  }
});

test('ambiguous or missing ownership retains saved evidence navigation', () => {
  const cases = [
    ['target history', fixture => fixture.projection.records.push({ref:{...fixture.hidden,version:2},body:{label:'Historical target'}}), 'observations'],
    ['observation history', fixture => fixture.projection.records.push({ref:{...fixture.owned[2],version:2},body:{label:'Historical comparison'}}), 'observations'],
    ['two owners', fixture => { fixture.other.reader = structuredClone(fixture.own.reader); fixture.other.reader.item_ref = fixture.earlier.item_ref; }, 'arguments'],
    ['missing exact section', fixture => { for (const section of fixture.own.sections) section.record_refs = section.record_refs.filter(ref => pinnedKey(ref) !== pinnedKey(fixture.owned[0])); }, 'arguments'],
    ['no reader', fixture => { delete fixture.own.reader; }, 'arguments'],
    ['historical reader', fixture => { fixture.own.reader.item_ref = {...fixture.major.item_ref,version:1}; }, 'arguments'],
    ['legacy shared refs in ownership fields', fixture => {
      const refs = ['anchors','uses'].map(collection => fixture.projection.records.find(row => row.ref.collection === collection).ref);
      for (const ref of refs) {
        for (const detail of [fixture.own,fixture.other]) {
          if (!detail.record_refs.some(row => pinnedKey(row) === pinnedKey(ref))) detail.record_refs.push(ref);
          if (!detail.sections[0].record_refs.some(row => pinnedKey(row) === pinnedKey(ref))) detail.sections[0].record_refs.push(ref);
        }
        Object.assign(fixture.projection.record_locations.find(row => pinnedKey(row.ref) === pinnedKey(ref)), {detail_key:fixture.earlier.detail_key,section_key:fixture.other.sections[0].key});
      }
      fixture.own.reader.arguments[1].argument_ref = refs[0];
      fixture.own.reader.arguments[1].groups[0].group_ref = refs[1];
      fixture.own.reader.provenance_groups = [{...fixture.own.reader.arguments[1].groups[0],group_ref:refs[0]}];
    }, 'arguments'],
    ['already owned section', fixture => { const saved = fixture.projection.record_locations.find(row => pinnedKey(row.ref) === pinnedKey(fixture.owned[0])); fixture.own.sections.push({key:'saved_owner_section',kind:'derivations',title:'Saved section',record_refs:[fixture.owned[0]],obligation_ids:[]}); Object.assign(saved,{detail_key:fixture.major.detail_key,section_key:'saved_owner_section'}); }, 'arguments'],
  ];
  for (const [name,change,collection] of cases) {
    const fixture = relocatedEvidenceFixture(); change(fixture);
    const before = JSON.stringify(fixture.projection);
    const {html} = renderProjection(Buffer.from(JSON.stringify(fixture.input)));
    const entries = decodeReaderSearchData(JSON.parse(scanHtml(html).elements.find(row => row.attrs.id === 'proof-reader-search').text));
    const refs = [fixture.owned.find(ref => ref.collection === collection), ...fixture.projection.records.filter(row => ['anchors','uses','application_details'].includes(row.ref.collection)).map(row => row.ref)];
    for (const ref of refs) {
      const saved = fixture.projection.record_locations.find(row => pinnedKey(row.ref) === pinnedKey(ref));
      const entry = entries.find(row => row.key === pinnedKey(ref));
      if (!saved || !entry) continue;
      assert.equal(entry.detail,saved.detail_key,name);
      assert.equal(entry.section,saved.section_key,name);
    }
    assert.equal(JSON.stringify(fixture.projection),before,name);
  }
});

test('native node activation remains below route capture and cannot toggle off a repeated selection', () => {
  const template = readFileSync(new URL('./assets/archify/template.html', import.meta.url),'utf8');
  const adapted = adaptScientificReaderTemplate(template);
  assert(!/\bset\(id\);/.test(adapted),'Ordinary node activation must remain idempotent.');
  assert(adapted.includes("svg.addEventListener('click', interceptSelection, true)"));
  assert(adapted.includes('.proof-results'), 'Results clicks must not clear the scientific selection.');
  assert(!adapted.includes('Archify.readerLayout = (function'), 'Scientific pages must not run the competing adaptive layout.');
  assert(!adapted.includes('Archify.outline = (function'), 'Scientific pages must not build a second navigator.');
  assert(adapted.includes('Archify.waitForStableLayout ='), 'Camera/export layout settling remains available.');
  const page = archifyPage({template,title:'Test',svg:'<svg viewBox="0 0 100 100"></svg>',runtime:''});
  assert(!page.includes('id="proof-runtime"'),'The content adapter must be able to supply exactly one runtime.');
});

test('replacing the native rail preserves complete upstream font, responsive, print and toolbar CSS', () => {
  const template = readFileSync(new URL('./assets/archify/template.html', import.meta.url),'utf8');
  const adapted = adaptScientificReaderTemplate(template);
  const styles = scanHtml(template).elements.filter(element=>element.tag==='style');
  const fonts = styles.find(element=>element.attrs.id==='archify-fonts');
  assert(fonts && adapted.includes(template.slice(fonts.start,fonts.closeEnd)), 'Bundled font rules must survive intact.');
  for (const marker of ['@media (min-width: 768px) and (max-height: 920px)', '@media print', '.toolbar']) {
    const start = template.indexOf('\n    '+marker+' {');
    assert(start>=0, 'Missing upstream CSS section '+marker);
    const open = template.indexOf('{',start);
    let end = open + 1, depth = 1;
    while (depth && end < template.length) {
      if (template[end]==='{') depth++;
      if (template[end]==='}') depth--;
      end++;
    }
    assert.equal(depth,0);
    assert(adapted.includes(template.slice(start,end)), 'Scientific rail replacement cut the '+marker+' section.');
  }
  for (const style of scanHtml(adapted).elements.filter(element=>element.tag==='style')) {
    const css = style.text.replace(/\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g,'');
    let depth = 0;
    for (const character of css) {
      if (character==='{') depth++;
      if (character==='}') depth--;
      assert(depth>=0,'Generated CSS must not close an absent media/rule block.');
    }
    assert.equal(depth,0,'Generated CSS must not leave a media/rule block open.');
  }
});

test('graphless pages clear graph presentation URL modes while retaining the theme', () => {
  const template = readFileSync(new URL('./assets/archify/template.html', import.meta.url),'utf8');
  const html = archifyPage({template,title:'Index',svg:'',index:true});
  const scripts = scanHtml(html).elements.filter(element=>element.tag==='script');
  const attributes = new Map();
  const root = {setAttribute:(key,value)=>attributes.set(key,value),removeAttribute:key=>attributes.delete(key)};
  const context = vm.createContext({document:{documentElement:root},window:{location:{search:'?present=1&embed=1&theme=light'}},URLSearchParams});
  vm.runInContext(scripts.find(script=>script.text.includes('window.location.search')).text,context);
  assert.equal(attributes.get('data-present'),'true');
  assert.equal(attributes.get('data-embed'),'true');
  vm.runInContext(scripts.find(script=>script.text.includes("setAttribute('data-js'")).text,context);
  assert(!attributes.has('data-present'));
  assert(!attributes.has('data-embed'));
  assert.equal(attributes.get('data-theme'),'light');
});

test('pretruncated math summaries disclose the limit and preserve literal source bytes', () => {
  const html = mathDisplayNotes({total:12,messages:['5 expressions use a literal fallback.'],messages_truncated:true});
  assert(html.includes('displayed notes are truncated'));
  assert(html.includes('do not change the scientific assessment'));
  const quoted = sourceDisclosure({title:'Statement source: main.tex:42',bodyHtml:'<pre>literal source excerpt</pre>',attrs:{'data-reader-search-key':'source:42'}});
  assert(quoted.includes('<summary>Statement source: main.tex:42</summary>'));
  assert(quoted.includes('<pre>literal source excerpt</pre>'));
});

test('reader payload keeps scientific text literal and aliases out of navigation labels', () => {
  const searchText = '</script><script>alert(1)</script> & <literal>';
  const searchEntries = [{key:'source:1',aliases:['opaque-id'],label:'Theorem 1',detail:'item:opaque-id',section:null,owner:'Main result',text:searchText}];
  const payload = readerSearchData(searchEntries);
  const searchScripts = scanHtml(payload).elements.filter(element => element.tag === 'script');
  assert.equal(searchScripts.length,1);
  assert.equal(searchScripts[0].attrs.id,'proof-reader-search');
  assert.equal(searchScripts[0].attrs.type,'application/json');
  assert(!/[<>&]/.test(searchScripts[0].text),'Saved text must not terminate the JSON script.');
  assert.deepEqual(decodeReaderSearchData(JSON.parse(searchScripts[0].text)),searchEntries);
  const runtime = readerRuntime({targets:[{key:'item:opaque-id',articleId:'article-1',nodeId:'opaque-id'}],graphAvailable:false});
  new vm.Script(runtime);
  assert(!runtime.includes('source:1'),'The runtime must not serialize the search entries again.');
  const entries = [{key:'item:opaque-id',nodeId:'opaque-id',articleId:'article-1',label:'Theorem 1',caption:'Variance identity',kind:'theorem'}];
  const navigation = resultsNavigation({entries,mainIds:['opaque-id'],heading:'Main results',graphAvailable:true});
  const scan = scanHtml(navigation), link = scan.elements.find(element=>element.tag==='a');
  assert.equal(link.attrs.href,'#article-1','Navigation needs a real article destination without JavaScript.');
  assert.equal(link.attrs['data-reader-node'],'opaque-id');
  assert(!navigation.slice(link.openEnd,link.closeStart).includes('opaque-id'));
  assert(!navigation.includes('proof-full-structure'));
  assert.equal(resultsNavigation({entries,mainIds:['opaque-id'],graphAvailable:false}),'','Index mode must not duplicate the complete index with a Results rail.');
});

test('source pooling restores complete entries, literal source bytes and property order', () => {
  const excerpt = ('e\u0301 α 🧪 </script><script>literal_source()</script> & <source>\r\n\t').repeat(12);
  const normalized = excerpt.replace(/\s+/gu,' ').trim();
  const short = excerpt.slice(0,-3);
  const entries = Array.from({length:8}, (_,index) => ({
    key:`source:${index}`,aliases:['opaque-id'],label:'Theorem 1',detail:'item:1',
    section:'sources',owner:'Main result',text:` before ${excerpt}${excerpt}${short} after ${normalized} `,
    isDirectResult:false,
  }));
  entries.push({...entries[0],key:'empty',text:''});
  const before = JSON.stringify(entries);
  const payload = readerSearchData(entries,{excerptCandidates:['',short,excerpt,excerpt,normalized,'unused candidate']});
  const scripts = scanHtml(payload).elements.filter(row => row.tag === 'script');
  assert.equal(scripts.length,1);
  assert(!/[<>&]/.test(scripts[0].text));
  const encoded = JSON.parse(scripts[0].text);
  assert.equal(encoded.format,'source-pool-v1');
  assert(encoded.strings.includes(excerpt));
  assert(encoded.strings.includes(normalized));
  assert(!encoded.strings.includes('unused candidate'));
  assert(encoded.entries[0].text.some(segment => Number.isInteger(segment)));
  assert.deepEqual(decodeReaderSearchData(encoded),entries);
  assert.equal(JSON.stringify(decodeReaderSearchData(encoded)),before);
  assert.equal(JSON.stringify(entries),before);
  const ordinary = scanHtml(readerSearchData(entries)).elements.find(row => row.tag === 'script').text;
  assert(Buffer.byteLength(scripts[0].text,'utf8') < Buffer.byteLength(ordinary,'utf8'));
});

test('search pooling preserves arrays and chooses the ordinary payload when it cannot save bytes', () => {
  for (const entries of [[],[{text:''}],[{key:'small',text:'α 🧪'}]]) {
    assert.equal(decodeReaderSearchData(entries),entries);
    const ordinary = scanHtml(readerSearchData(entries)).elements.find(row => row.tag === 'script').text;
    for (const excerptCandidates of [[],['absent'],['α 🧪']]) {
      const payload = scanHtml(readerSearchData(entries,{excerptCandidates})).elements.find(row => row.tag === 'script').text;
      assert.equal(payload,ordinary);
      assert.deepEqual(decodeReaderSearchData(JSON.parse(payload)),entries);
    }
  }
});

test('search decoding rejects malformed pools and invalid references', () => {
  const envelope = text => ({format:'source-pool-v1',strings:['source'],entries:[{key:'source:1',text}]});
  assert.deepEqual(decodeReaderSearchData(envelope('literal')),[{key:'source:1',text:'literal'}]);
  assert.deepEqual(decodeReaderSearchData(envelope(['before ',0,0,' after'])),[{key:'source:1',text:'before sourcesource after'}]);
  for (const segment of [-1,1,0.5,null,{},['nested']]) assert.throws(() => decodeReaderSearchData(envelope([segment])));
  for (const value of [
    {...envelope([0]),strings:[7]}, {...envelope([0]),strings:null},
    {...envelope([0]),entries:null}, {...envelope([0]),format:'unknown-pool'},
    envelope(true),
  ]) assert.throws(() => decodeReaderSearchData(value));
});

test('located diagnostics survive validation and rendering without entering scientific records', () => {
  const input = JSON.parse(readFileSync(new URL('./fixtures/dag_small.json',import.meta.url),'utf8'));
  const record = input.projection.records[0];
  const records = JSON.stringify(input.projection.records);
  input.display.math_diagnostics=[{kind:'literal_fallback',classification:'literal_fallback',reason:'Unknown mathematical command',excerpt:'\\unknown{x}',display:'inline',expression_index:0,collection:record.ref.collection,record_id:record.ref.id,record_version:record.ref.version,field_path:'statement.text'}];
  input.display.math_diagnostic_summary={total:1,messages:['One formula remains labeled TeX.'],groups_truncated:true};
  const model = validateInput(input);
  assert.deepEqual(model.mathDiagnostics,input.display.math_diagnostics);
  const rendered = renderProjection(Buffer.from(JSON.stringify(input)));
  assert(rendered.html.includes('One formula remains labeled TeX.'));
  assert(rendered.html.includes('displayed notes are truncated'));
  assert.equal(JSON.stringify(input.projection.records),records);
  const notes = scanHtml(rendered.html).elements.find(element=>Object.hasOwn(element.attrs,'data-reader-math-notes'));
  assert(!rendered.html.slice(notes.openEnd,notes.closeStart).includes(record.ref.id));
});

test('print styles keep source and qualification labels visible while long formulas remain bounded', () => {
  assert(SCIENTIFIC_READER_CSS.includes('.proof-formula{display:inline-block;max-width:100%'));
  assert(SCIENTIFIC_READER_CSS.includes('overflow-x:auto'));
  const printRules = [...SCIENTIFIC_READER_CSS.slice(SCIENTIFIC_READER_CSS.indexOf('@media print')).matchAll(/([^{}]+)\{([^{}]+)\}/g)];
  const indexSummary = printRules.find(([,selectors]) => selectors.split(',').some(selector => selector.trim() === '.proof-index summary'));
  assert(indexSummary && /display\s*:\s*list-item\s*!important/.test(indexSummary[2]), 'Print must keep source and qualification labels visible.');
  assert(SCIENTIFIC_READER_CSS.includes('[data-reader-article]{display:block!important}'));
  assert(!SCIENTIFIC_READER_CSS.includes('[data-proof-detail]:not(.is-active)'));
});

test('printing a presentation or embedded reader retains the title and scientific content in page flow', () => {
  // Screen-only stage hiding must not hide expanded scientific sections during print.
  const printableCss = SCIENTIFIC_READER_CSS.replace(/@media\s+screen\s*\{(?:[^{}]|\{[^{}]*\})*\}/g, '');
  const hiddenContent = [...printableCss.matchAll(/([^{}]+)\{([^{}]+)\}/g)]
    .filter(([, selector, declarations]) => /\.proof-reader-before|#proof-selection-host|\.proof-reader-after/.test(selector)
      && /display\s*:\s*none\b/.test(declarations));
  assert.equal(hiddenContent.length, 0, 'Stage mode must not hide the scientific content when printing.');
  const rules = [...SCIENTIFIC_READER_CSS.slice(SCIENTIFIC_READER_CSS.indexOf('@media print')).matchAll(/([^{}]+)\{([^{}]+)\}/g)];
  for (const selector of ['html body[data-reader-layout]', 'html body[data-reader-layout]>.container']) {
    const rule = rules.find(([, selectors]) => selectors.trim() === selector);
    assert(rule && /height\s*:\s*auto\s*!important/.test(rule[2]) && /overflow\s*:\s*visible\s*!important/.test(rule[2]),
      'Print must remove the viewport clipping imposed by presentation/embed mode: ' + selector);
  }
  const header = rules.find(([, selectors]) => selectors.includes('.container>.header'));
  assert(header && /display\s*:\s*block\s*!important/.test(header[2]) && /padding-right\s*:\s*0\s*!important/.test(header[2]),
    'Print must show the paper title without the presentation toolbar gutter.');
});
