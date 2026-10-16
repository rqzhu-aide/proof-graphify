// Shared display contract checks. This is not a browser or visual review.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { adaptScientificReaderTemplate, archifyPage, resultsNavigation, mathDisplayNotes,
  readerRuntime, SCIENTIFIC_READER_CSS, sourceDisclosure } from './scientific_reader.mjs';
import { renderProjection, validateInput } from './render_projection.mjs';
import { scanHtml } from './html_scan.mjs';

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
  const searchText = '</script><script>alert(1)</script>';
  const runtime = readerRuntime({targets:[{key:'item:opaque-id',articleId:'article-1',nodeId:'opaque-id'}],searchEntries:[{key:'source:1',aliases:['opaque-id'],label:'Theorem 1',detail:'item:opaque-id',section:null,owner:'Main result',text:searchText}],graphAvailable:false});
  new vm.Script(runtime);
  assert(!runtime.includes(searchText),'Untrusted saved text must not terminate the script.');
  const entries = [{key:'item:opaque-id',nodeId:'opaque-id',articleId:'article-1',label:'Theorem 1',caption:'Variance identity',kind:'theorem'}];
  const navigation = resultsNavigation({entries,mainIds:['opaque-id'],heading:'Main results',graphAvailable:true});
  const scan = scanHtml(navigation), link = scan.elements.find(element=>element.tag==='a');
  assert.equal(link.attrs.href,'#article-1','Navigation needs a real article destination without JavaScript.');
  assert.equal(link.attrs['data-reader-node'],'opaque-id');
  assert(!navigation.slice(link.openEnd,link.closeStart).includes('opaque-id'));
  assert(!navigation.includes('proof-full-structure'));
  assert.equal(resultsNavigation({entries,mainIds:['opaque-id'],graphAvailable:false}),'','Index mode must not duplicate the complete index with a Results rail.');
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
