// Shared display contract checks. This is not a browser or visual review.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { adaptScientificReaderTemplate, archifyPage, mainResultNavigation, mathDisplayNotes,
  readerRuntime, SCIENTIFIC_READER_CSS, sourceDisclosure } from './scientific_reader.mjs';
import { renderProjection, validateInput } from './render_projection.mjs';
import { scanHtml } from './html_scan.mjs';

test('native node activation remains below route capture and cannot toggle off a repeated selection', () => {
  const template = readFileSync(new URL('./assets/archify/template.html', import.meta.url),'utf8');
  const adapted = adaptScientificReaderTemplate(template);
  assert.equal((adapted.match(/set\(id, \{ toggle: false \}\);/g)||[]).length,(template.match(/set\(id, \{ toggle: false \}\);/g)||[]).length+2);
  assert(adapted.includes("svg.addEventListener('click', interceptSelection, true)"));
  assert(adapted.includes('.proof-reader, #proof-selection, .proof-index, .proof-main-navigation'));
  assert(adapted.includes("probe.className = 'proof-svg'"));
  assert(adapted.includes('var desiredWidth = maxWidth;'));
  const page = archifyPage({template,title:'Test',svg:'<svg viewBox="0 0 100 100"></svg>',runtime:''});
  assert(!page.includes('id="proof-runtime"'),'The content adapter must be able to supply exactly one runtime.');
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
  const searchText = '</script><script>alert(1)</script>';
  const runtime = readerRuntime({targets:[{key:'item:opaque-id',articleId:'article-1',nodeId:'opaque-id'}],searchEntries:[{key:'source:1',aliases:['opaque-id'],label:'Theorem 1',detail:'item:opaque-id',section:null,owner:'Main result',text:searchText}],graphAvailable:false});
  new vm.Script(runtime);
  assert(!runtime.includes(searchText),'Untrusted saved text must not terminate the script.');
  const navigation = mainResultNavigation({entries:[{key:'item:opaque-id',nodeId:'opaque-id',label:'Theorem 1',caption:'Variance identity',kind:'theorem'}],graphAvailable:false});
  const scan = scanHtml(navigation), button = scan.elements.find(element=>element.tag==='button');
  assert(!navigation.slice(button.openEnd,button.closeStart).includes('opaque-id'));
  assert(!navigation.includes('proof-full-structure'));
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
  assert(SCIENTIFIC_READER_CSS.includes('.proof-index details[open]>summary{display:list-item!important'));
  assert(SCIENTIFIC_READER_CSS.includes('[data-reader-article]{display:block!important}'));
  assert(!SCIENTIFIC_READER_CSS.includes('[data-proof-detail]:not(.is-active)'));
});
