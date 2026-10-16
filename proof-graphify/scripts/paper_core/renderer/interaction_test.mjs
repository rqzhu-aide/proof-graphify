// Deterministic adapter contract simulation. This does not claim browser/CSS acceptance.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { BOX, layoutGraph, renderProjection } from './render_projection.mjs';
import { scanHtml, textOf, decodeEntities } from './html_scan.mjs';
import { readerFixture } from './selftest.mjs';

function disconnectedLayout() {
  const isolated = {nodeList:Array.from({length:18}, (_, i) => ({id:`isolated_${i}`})), connectionList:[], layout:{mode:'dag'}};
  const compact = layoutGraph(isolated);
  assert(compact.height < 1200, 'An unconnected inventory must not become an unreadably tall single column.');
  assert(new Set([...compact.nodes.values()].map(node => node.x)).size > 1,
    'Disconnected components should use the available horizontal space.');
  assert.deepEqual([...compact.nodes.keys()], isolated.nodeList.map(node => node.id));
  assert.deepEqual([...layoutGraph(isolated).nodes.values()], [...compact.nodes.values()], 'Packing must remain deterministic.');

  // Different component widths/heights and a return edge exercise row packing,
  // while all inferential ranks and directions stay inside their own component.
  const mixed = {nodeList:Array.from({length:14}, (_, i) => ({id:`mixed_${i}`})),
    connectionList:[[0,1],[1,2],[2,0],[3,4],[4,5],[3,5],[6,7],[6,8],[6,9]]
      .map(([from,to],i) => ({id:`edge_${i}`,from:`mixed_${from}`,to:`mixed_${to}`})), layout:{mode:'cyclic'}};
  const graph = layoutGraph(mixed);
  for (const edge of mixed.connectionList)
    assert.equal(graph.nodes.get(edge.from).component, graph.nodes.get(edge.to).component);
  for (const component of graph.components) {
    assert(component.left >= 0 && component.left + component.width <= graph.width);
    assert(component.top >= 0 && component.bottom <= graph.height);
    for (const node of component.members) {
      assert(node.x >= component.left && node.x + BOX.w <= component.left + component.width);
      assert(node.y >= component.top && node.y + BOX.h <= component.bottom);
    }
    for (const other of graph.components) if (component !== other)
      assert(component.left + component.width <= other.left || other.left + other.width <= component.left ||
        component.bottom <= other.top || other.bottom <= component.top, 'Packed components must not overlap.');
  }
  return {fixture:'disconnected components', nodes:compact.nodes.size, width:compact.width, height:compact.height,
    mixed_components:graph.components.length, stable_layout:true};
}

function runFixture(name, withWork = false, withReader = false, buildKind = null, sharedOwners = false) {
  const input = withReader ? readerFixture() : JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8'));
  if (sharedOwners) {
    // The article's saved assessment is shared too; only graph identity differs.
    input.projection.nodes[1].detail_key = input.projection.nodes[0].detail_key;
    input.projection.nodes[1].assessment = structuredClone(input.projection.nodes[0].assessment);
  }
  if (buildKind) input.build.kind = buildKind;
  if (withWork) {
    input.projection.projection_version = 2;
    const target = input.projection.records.find(row => row.body.kind === 'intermediate_result') ||
      input.projection.records.find(row => row.ref.collection === 'uses');
    const location = input.projection.record_locations.find(row => row.ref.id === target.ref.id && row.ref.collection === target.ref.collection);
    const detailKey = location.detail_key;
    const detail = input.projection.details[detailKey];
    const section = detail.sections.find(row => row.key === location.section_key);
    const baseObligation = input.projection.obligations[0];
    const tasks = [];
    for (let index = 0; index < 25; index++) {
      const id = 'obl_work_' + index;
      input.projection.obligations.push({...baseObligation, id, target:{collection:target.ref.collection, id:target.ref.id}});
      section.obligation_ids.push(id);
      tasks.push({id, target:{collection:target.ref.collection, id:target.ref.id}, kind:'derivation', role:'primary', required:true,
        label:'Hidden bound: local derivation ' + index, state:index ? 'waiting' : 'ready',
        waiting_on:index ? ['obl_work_0'] : [], next_action:index ? null : 'Read the last inequality.',
        outcome:index < 2 ? 'gap' : null, freshness:index === 0 ? 'current' : index === 1 ? 'needs_review' : null, dependency_support:'conditional',
        location:{ref:target.ref, detail_key:detailKey, section_key:section.key, obligation_id:id}});
    }
    input.projection.worklist = {revision:input.projection.snapshot_revision, analysis_complete:true, tasks,
      coordinator_actions:[{message:'An upstream proof is incomplete; local support remains conditional.'}]};
  }
  input.projection.summary.limitations = ['Coverage incomplete: a < b & c.'];
  const { html } = renderProjection(Buffer.from(JSON.stringify(input)));
  const scan = scanHtml(html);
  const reportState = scan.elements.find(e => Object.hasOwn(e.attrs, 'data-reader-report-state'));
  const openingText = textOf(scan, reportState);
  const completion = input.projection.summary.progress.process_complete ? 'Registered examinations complete.' : 'Registered examinations incomplete.';
  assert(openingText.includes(completion), 'The opening state must identify registered examination completion.');
  assert(openingText.startsWith(input.build.kind === 'release' ? 'Release report' : 'Working report'), 'The opening must retain the frozen report kind.');
  assert.equal(openingText.includes('This working report does not establish completion of the promised audit scope.'), input.build.kind === 'working',
    'A working report must state that promised audit coverage is not established.');
  const scripts = scan.elements.filter(e => e.tag === 'script' && e.attrs.type !== 'application/json');
  scripts.forEach((script, i) => new vm.Script(script.text, { filename: `generated-${i}.js` }));
  const native = scripts.find(s => s.text.includes('var Archify = {}'))?.text || '';
  if (native) {
  for (const api of ['Archify.focus =', 'Archify.view =', 'Archify.exportMenu =', 'Archify.presentation ='])
    assert(native.includes(api), `Native runtime missing ${api}`);
  assert(!native.includes('Archify.readerLayout = (function'), 'Scientific output must omit the unused adaptive layout.');
  assert(!native.includes('Archify.outline = (function'), 'Scientific output must not build a competing outline.');
  const filter = native.match(/if \((\/\(\^\|,\).*?\/)\.test\(sel\)\)/);
  assert(filter, 'Native export style filter must remain available.');
  const selectorFilter = vm.runInNewContext(filter[1]);
  for (const selector of ['.proof-node-box', '.proof-node.s-red', '.proof-edge.s-amber', '.k-theorem', '.proof-arrowhead'])
    assert(selectorFilter.test(selector), `Export would omit verdict/kind style ${selector}`);
  }

  const callbacks = new Map(), observers = [], moves = [];
  let timer = 0, document;
  class Element {
    constructor(row = {}) {
      this.tagName = row.tag || 'div'; this.attrs = { ...row.attrs }; this.children = [];
      this.parentElement = null; this.listeners = []; this._text = row.text || '';
      this.hidden = Object.hasOwn(this.attrs, 'hidden'); this.checked = false;
      this.clientWidth = 600; this.clientHeight = 300;
      const vb = (this.attrs.viewbox || '0 0 600 300').split(' ').map(Number);
      this.viewBox = { baseVal: { x: vb[0], y: vb[1], width: vb[2], height: vb[3] } };
      for (const child of row.children || []) this.appendChild(new Element(child));
    }
    get id() { return this.attrs.id; }
    get parentNode() { return this.parentElement; }
    get className() { return this.attrs.class || ''; }
    set className(value) { this.attrs.class = value; }
    get classList() {
      const self = this;
      return { contains(c) { return self.className.split(/\s+/).includes(c); },
        add(c) { if (!this.contains(c)) self.className = `${self.className} ${c}`.trim(); },
        remove(c) { self.className = self.className.split(/\s+/).filter(s => s !== c).join(' '); },
        toggle(c, on) { if (on === undefined) on = !this.contains(c); if (on) this.add(c); else this.remove(c); } };
    }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
    set textContent(value) { this._text = value; this.children.forEach(c => c.parentElement = null); this.children = []; }
    getAttribute(key) { return this.attrs[key] ?? null; }
    hasAttribute(key) { return Object.hasOwn(this.attrs, key); }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    removeAttribute(key) { delete this.attrs[key]; }
    appendChild(child) {
      if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1);
      this.children.push(child); child.parentElement = this; return child;
    }
    cloneNode(deep) {
      const clone = new Element({tag:this.tagName, attrs:this.attrs, text:this._text});
      if (deep) this.children.forEach(child => clone.appendChild(child.cloneNode(true)));
      return clone;
    }
    get content() {
      const fragment = new Element({tag:'#fragment'});
      this.children.forEach(child => fragment.appendChild(child.cloneNode(true)));
      return fragment;
    }
    replaceChildren(child) {
      this.textContent = '';
      if (child.tagName === '#fragment') [...child.children].forEach(entry => this.appendChild(entry));
      else this.appendChild(child);
    }
    insertAdjacentElement(position, child) {
      assert.equal(position, 'afterend');
      if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1);
      const p = this.parentElement; p.children.splice(p.children.indexOf(this) + 1, 0, child); child.parentElement = p;
    }
    contains(e) { return e === this || this.children.some(c => c.contains(e)); }
    matches(selector) {
      const tag = selector.match(/^[\w-]+/);
      if (tag && this.tagName !== tag[0]) return false;
      for (const match of selector.matchAll(/#([\w-]+)|\.([\w-]+)|\[([^\]=]+)(?:="([^"]*)")?\]/g)) {
        if (match[1] && this.id !== match[1]) return false;
        if (match[2] && !this.classList.contains(match[2])) return false;
        if (match[3] && (!this.hasAttribute(match[3]) || match[4] !== undefined && this.getAttribute(match[3]) !== match[4])) return false;
      }
      return true;
    }
    closest(selector) {
      for (let e = this; e; e = e.parentElement) if (selector.split(',').some(s => e.matches(s.trim()))) return e;
      return null;
    }
    querySelectorAll(selector) {
      const result = [], selectors = selector.split(',').map(s => s.trim());
      const matches = (child, s) => {
        const terms = s.split(/\s+/), last = terms.pop();
        if (!child.matches(last)) return false;
        let ancestor = child.parentElement;
        while (terms.length) {
          const term = terms.pop();
          while (ancestor && !ancestor.matches(term)) ancestor = ancestor.parentElement;
          if (!ancestor) return false;
          ancestor = ancestor.parentElement;
        }
        return true;
      };
      const walk = e => e.children.forEach(child => { if (selectors.some(s => matches(child,s))) result.push(child); walk(child); });
      walk(this); return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener(type, callback, options) { this.listeners.push({ type, callback, capture: options === true }); }
    scrollIntoView() { moves.push(this.id || this.tagName); }
    focus() { document.activeElement = this; }
    click() { dispatch(this, { type: 'click' }); }
  }
  const directText = el => {
    if (el.tag === 'script' || el.tag === 'style') return el.text;
    let cursor = el.openEnd, text = '';
    for (const child of el.children) { text += scan.html.slice(cursor,child.start); cursor = child.closeEnd; }
    return decodeEntities((text + scan.html.slice(cursor,el.closeStart)).replace(/<[^>]*>/g,''));
  };
  const row = el => ({ tag: el.tag, attrs: el.attrs, text: directText(el), children: el.children.map(row) });
  document = new Element(row(scan.root));
  document.documentElement = document.querySelector('html'); document.body = document.querySelector('body');
  document.getElementById = id => document.querySelector('#' + id);
  document.createElement = tag => new Element({ tag });
  document.createTextNode = text => new Element({ tag: '#text', text });
  const svg = document.querySelector('svg.proof-svg'), container = document.querySelector('.diagram-container');
  const chip = document.getElementById('focus-chip');
  const schedule = cb => { callbacks.set(++timer, cb); return timer; };
  const flush = () => {
    for (let i = 0; callbacks.size && i < 20; i++) { const list = [...callbacks.values()]; callbacks.clear(); list.forEach(cb => cb()); }
    assert.equal(callbacks.size, 0, 'Adapter never settled.');
  };
  const notify = attribute => observers.forEach(o => { if (o.options.attributeFilter.includes(attribute)) schedule(o.callback); });
  function dispatch(target, event) {
    event.target = target; event.preventDefault = () => {}; event.stopPropagation = () => { event.stopped = true; };
    event.stopImmediatePropagation = () => { event.stopped = true; };
    const path = []; for (let e = target; e; e = e.parentElement) path.push(e);
    for (const capture of [true, false]) for (const e of capture ? [...path].reverse() : path) {
      e.listeners.filter(l => l.type === event.type && l.capture === capture).forEach(l => l.callback(event));
      if (event.stopped) return;
    }
  }
  let active = null, relation = null, reset = 0, centers = 0;
  const location = {hash: ''};
  const focus = {
    active: () => active, relationship: () => relation,
    set(id,options) { if (active === id && options?.toggle !== false) return this.clear(); active = id; relation = null; chip.hidden = false; svg.setAttribute('data-focus-active', id); if (options?.updateUrl !== false) location.hash = '#focus='+id; notify('data-focus-active'); return true; },
    clear(options) { active = null; relation = null; chip.hidden = true; svg.removeAttribute('data-focus-active'); if (options?.updateUrl !== false) location.hash = ''; notify('data-focus-active'); },
    inspectRelationshipById(id,options) {
      relation = input.projection.connections.find(c => c.id === id); active = relation.from; chip.hidden = false;
      if (options?.updateUrl !== false) location.hash = '#relation='+id;
      svg.setAttribute('data-relationship-pin-active', id); notify('data-relationship-pin-active'); return true;
    },
  };
  const Archify = { focus, view: { centerAt(x, y) { assert(Number.isFinite(x) && Number.isFinite(y)); centers++; }, reset() { reset++; } } };
  if (svg) {
    const native = scripts.flatMap(script => [...script.text.matchAll(/svg\.addEventListener\('click', function \(event\) \{\s*if \(container\.getAttribute\('data-just-panned'\) === 'true'\) return;[\s\S]*?\n      \}\);/g)]).find(([source]) => source.includes('set(id,'))?.[0];
    assert(native,'Emitted native node handler is missing.');
    vm.runInNewContext(native,{svg,container,set:(id,options)=>focus.set(id,options),clear:()=>focus.clear(),get activeIds(){return active?[active]:[];},Archify});
    const outside = scripts.flatMap(script => [...script.text.matchAll(/document\.addEventListener\('click', function \(event\) \{[\s\S]*?\}, true\);/g)]).find(([source])=>source.includes('chip.hidden || !target'))?.[0];
    assert(outside,'Emitted outside-click handler is missing.');
    vm.runInNewContext(outside,{document,chip,container,lensDragClickPointer:null,clear:()=>focus.clear()});
  }
  const windowEvents = new Map();
  const initialArticle = document.querySelector('[data-reader-article]');
  location.hash = '#'+initialArticle.id;
  const context = vm.createContext({ document, window: { Archify, addEventListener(type,callback) { windowEvents.set(type,callback); } }, location,
    MutationObserver: class { constructor(callback) { this.callback = callback; } observe(target, options) { observers.push({ callback: this.callback, options }); } },
    requestAnimationFrame: schedule, setTimeout: schedule, clearTimeout: id => callbacks.delete(id) });
  const stateBeforeInteraction = document.querySelector('[data-reader-report-state]').textContent;
  const runtime = scripts.find(s => s.attrs.id === 'proof-runtime');
  vm.runInContext(runtime.text, context); flush();
  assert.equal(location.hash,'#'+initialArticle.id,'Fresh article links retain their public address.');
  assert(initialArticle.classList.contains('is-active'));
  assert(initialArticle.contains(document.activeElement),'Fresh links focus the requested scientific content.');
  assert(moves.length,'Fresh links must bring the content into view.');
  if (svg) {
    const hashHandler = native.match(/function syncFocusFromHash\(\) \{[\s\S]*?\n      \}/)?.[0];
    assert(hashHandler,'Native hash integration must be exercised.');
    const hashContext = {location,URLSearchParams,html:document.documentElement,set:(...args)=>focus.set(...args),clear:(...args)=>focus.clear(...args),inspectRelationshipById:(...args)=>focus.inspectRelationshipById(...args),applyReachability(){}};
    const nativeHashChange = vm.runInNewContext(hashHandler+'; syncFocusFromHash;',hashContext);
    const navigateHash = hash => { location.hash = hash; nativeHashChange(); windowEvents.get('hashchange')(); flush(); };
    for (const owner of [input.projection.nodes[1],input.projection.connections[0],input.projection.nodes[0]]) {
      const article = document.querySelector(`[data-proof-detail="${owner.detail_key}"]`);
      navigateHash('#'+article.id);
      assert.equal(location.hash,'#'+article.id,'Same-document links must survive native hash changes.');
      assert(article.classList.contains('is-active'));
      assert(article.contains(document.activeElement));
    }
    navigateHash('#focus='+input.projection.nodes[1].id);
    assert.equal(active,input.projection.nodes[1].id,'Native graph focus links remain available.');
    navigateHash('#relation='+input.projection.connections[0].id);
    assert.equal(relation.id,input.projection.connections[0].id,'Native connection links remain available.');
    for (const hash of ['#unknown-fragment','#lens=theorem','#route=start,end']) {
      navigateHash('#focus='+input.projection.nodes[0].id);
      navigateHash(hash);
      assert.equal(location.hash,hash,'Mirroring native dismissal must not erase unrelated or reserved hashes.');
      assert(!document.querySelector('.proof-detail.is-active'));
    }
    focus.clear(); flush();
  }
  assert.equal(centers, 0, 'Opening a report must retain the complete graph instead of zooming into an arbitrary node.');
  const detail = key => document.querySelector(`[data-proof-detail="${key}"]`);
  if (withWork) {
    assert.equal(document.getElementById('proof-work-panel'), null, 'The coordinator queue must not enter the scientific reader.');
    const limits = document.querySelectorAll('[data-proof-review-limit]');
    assert.equal(limits.length,25,'Every unfinished saved examination needs its scientific consequence.');
    assert(limits[0].textContent.includes('Initial assessment: gap. Examination remains incomplete for the current material.'),
      'A partial current opinion must not imply a completed current examination.');
    assert(limits[1].textContent.includes('Earlier initial assessment: gap.'), 'Stale saved opinions need their historical context.');
    assert(limits[0].textContent.includes('Premise support: conditional'), 'Readiness must not replace proof support.');
    assert(limits.every(row => !row.textContent.includes('obl_work_') && !row.textContent.includes('Waiting for:')),
      'Review limits must omit scheduling identifiers and instructions.');
    const evidenceLink = limits[0].querySelector('[data-jump-record]');
    evidenceLink.click(); flush();
    assert.equal(document.querySelector('.is-target').getAttribute('data-record-ref'), evidenceLink.getAttribute('data-jump-record'),
      'An incomplete-examination notice must reach the affected scientific material.');
    if (svg) assert.equal(active, input.projection.worklist.tasks[0].location.detail_key.slice('item:'.length),
      'Review-limit navigation selects the existing major owner.');
    const search = document.getElementById('proof-search'); search.value = 'obl_work_24';
    dispatch(search, {type:'input'}); flush();
    const hit = document.getElementById('proof-search-results').querySelector('button');
    assert.equal(hit,null, 'Scheduling IDs must not supply ordinary scientific search results.');
  }
  const first = input.projection.nodes[0];
  if (svg) {
    assert(!container.contains(chip));
    assert(!container.contains(document.getElementById('proof-details')));
    assert.equal(chip.parentElement.id,'proof-selection-host');
    const nativeNode = svg.querySelector('[data-node-id]');
    nativeNode.click(); flush(); nativeNode.click(); flush();
    assert.equal(active,first.id,'Repeated native activation must retain its scientific selection.');
    focus.set(first.id,{toggle:false}); flush();
    assert(detail(first.detail_key).classList.contains('is-active'));
    const sourceSummary = detail(first.detail_key).querySelector('summary');
    if (sourceSummary) { sourceSummary.click(); flush(); assert.equal(active,first.id,'Source and audit disclosures must preserve the selected result.'); }
    const edge = input.projection.connections[0];
    focus.inspectRelationshipById(edge.id); flush();
    assert(detail(edge.detail_key).classList.contains('is-active'), 'Native edge selection must open its canonical evidence.');
    assert(!detail(first.detail_key).classList.contains('is-active'));
    focus.clear(); flush();
    assert(!detail(edge.detail_key).classList.contains('is-active'), 'Native close must clear the reader.');
    const main = document.querySelector('.proof-results [data-reader-node]'); main.click(); flush();
    assert.equal(active, main.getAttribute('data-reader-node'));
    assert.equal(main.getAttribute('aria-current'),'true');
    document.getElementById('proof-full-structure').click(); flush(); assert.equal(reset, 1);
    const beforeReadable = centers;
    document.getElementById('proof-readable-view').click(); assert(centers > beforeReadable);
    const previousCenters = centers;
    const showInGraph = document.querySelector('[data-focus-node]'); showInGraph.click(); flush();
    assert.equal(active, showInGraph.getAttribute('data-focus-node'));
    assert(centers > previousCenters, 'Show in graph must center the native camera on the requested item.');
    const beforeKeyboard = centers, selectedBeforeKeyboard = active;
    dispatch(svg.querySelector('[data-node-id]'), { type: 'keydown', key: 'End' }); flush();
    assert(centers > beforeKeyboard, 'Keyboard navigation must bring off-screen items into the native camera.');
    assert.equal(active, selectedBeforeKeyboard, 'Moving keyboard focus must not open a different evidence panel before Enter.');
    const badge = svg.querySelector('[data-edge-badge]');
    if (badge) { badge.click(); flush(); assert.equal(relation.id, badge.getAttribute('data-edge-badge')); }
  } else {
    assert.equal(native,'','Index mode must not initialize an unused graph viewer.');
    assert.equal(document.getElementById('btn-export'),null, 'Index fallback must omit graph-only controls.');
    assert(document.getElementById('proof-index-theme'),'Index mode retains theme selection.');
    assert.equal(document.querySelector('.proof-results'),null, 'Index mode uses its complete scientific index.');
  }
  if (sharedOwners) {
    const owners = input.projection.nodes.slice(0,2);
    const article = detail(owners[0].detail_key);
    assert.equal(document.querySelectorAll(`[data-proof-detail="${owners[0].detail_key}"]`).length,1,
      'Shared ownership must not duplicate the scientific article.');
    for (const owner of owners) {
      const link = document.querySelector(`.proof-results [data-reader-node="${owner.id}"]`);
      assert(link,'Each graph owner needs its own Results entry.');
      link.click(); flush();
      assert.equal(active,owner.id,'Selecting a shared article must focus the clicked graph owner.');
      assert(article.classList.contains('is-active'));
      assert.equal(link.getAttribute('aria-current'),'true');
      assert.equal(document.querySelectorAll('.proof-results [aria-current="true"]').length,1);
      dispatch(article,{type:'keydown',key:'Escape'}); flush();
      assert.equal(document.activeElement,link,'Closing shared content must restore the clicked owner entry.');
    }
  }
  const hidden = input.projection.records.find(r => r.body.kind === 'intermediate_result');
  const record = hidden || input.projection.records.find(r => r.ref.collection === 'uses');
  const search = document.getElementById('proof-search'); search.value = record.ref.id;
  dispatch(search, { type: 'input' }); flush();
  const hit = document.getElementById('proof-search-results').querySelector('button');
  assert(hit, 'Hidden/canonical record must be searchable.'); hit.click(); flush();
  assert(document.querySelector('.is-target'), 'Search must reach the actual canonical record section.');
  const reached = document.querySelector('.is-target');
  for (let ancestor = reached; ancestor; ancestor = ancestor.parentElement)
    if (ancestor.tagName === 'details') assert(ancestor.hasAttribute('open'), 'Every enclosing evidence disclosure must open before focus.');
  const fields = document.querySelectorAll('[data-reader-field]');
  const fieldState = fields.map(field => [field,field.getAttribute('data-reader-ref'),field.children.length]);
  const disclosures = document.querySelectorAll('details').filter(element => element.closest('.proof-reader'));
  assert(disclosures.some(element => !element.hasAttribute('open')), 'Secondary evidence should initially be collapsed.');
  const priorOpen = disclosures.map(element => element.hasAttribute('open'));
  windowEvents.get('beforeprint')();
  assert(disclosures.every(element => element.hasAttribute('open')), 'Print must include expanded evidence and reader contexts.');
  windowEvents.get('beforeprint')();
  windowEvents.get('afterprint')();
  assert.deepEqual(disclosures.map(element => element.hasAttribute('open')), priorOpen, 'Printing must restore every disclosure to its previous state.');
  for (const [field,ref,children] of fieldState) {
    assert.equal(field.getAttribute('data-reader-ref'),ref);
    assert.equal(field.children.length,children,'Hydration must leave overview fields intact.');
    assert(!field.hasAttribute('data-record-ref'),'Overview text must not act as a canonical record slot.');
  }
  if (withReader) {
    const strategy = document.querySelector('[data-reader-field="proof_idea"]');
    assert(strategy && strategy.closest('[data-reader-overview]'),'Saved strategy must be static overview content.');
    const sourceLink = strategy.closest('[data-reader-overview]').querySelector('.proof-jump[data-jump-record]');
    sourceLink.click(); flush();
    const destination = document.querySelector('.is-target');
    assert.equal(destination.getAttribute('data-record-ref'),sourceLink.getAttribute('data-jump-record'));
    for (let ancestor = destination; ancestor; ancestor = ancestor.parentElement)
      if (ancestor.tagName === 'details') assert(ancestor.hasAttribute('open'),'Reader links must reveal canonical evidence.');
    const label = document.querySelector('[data-reader-context="application:0:from"]');
    assert(label.querySelector('math'), 'A linked supplier label must retain its typeset formula.');
    const labelLink = label.closest('.proof-jump');
    labelLink.click(); flush();
    assert.equal(document.querySelector('.is-target').getAttribute('data-record-ref'), labelLink.getAttribute('data-jump-record'),
      'Typesetting a label must preserve its exact evidence destination.');
    search.value = 'Bound $J_\\lambda$';
    dispatch(search, {type:'input'}); flush();
    const labelHit = document.getElementById('proof-search-results').querySelector('button');
    assert(labelHit, 'Search must keep the original plain-text mathematical label.');
    labelHit.click(); flush();
    assert(document.querySelector('.is-target'), 'Label search must retain a navigable result.');
    for (const role of ['application','blocking_scope']) {
      const supportLink = document.querySelector(`[data-reader-support-link="${role}"]`).querySelector('.proof-jump');
      supportLink.click(); flush();
      assert.equal(document.querySelector('.is-target').getAttribute('data-record-ref'), supportLink.getAttribute('data-jump-record'),
        'Blocking support must link to the exact application or scope evidence.');
    }
  }
  assert.equal(document.querySelector('[data-reader-report-state]').textContent, stateBeforeInteraction,
    'Navigation and printing must preserve registered completion and the working scope limitation.');
  const notices = scan.elements.filter(e => Object.hasOwn(e.attrs, 'data-proof-limitation'));
  assert.deepEqual(notices.map(e => textOf(scan, e)), input.projection.summary.limitations);
  return { fixture: name, compiled_scripts: scripts.length, canonical_reader_bridge: true, worklist:withWork, contextual_reader:withReader, shared_detail_owners:sharedOwners, print_state_restored:true };
}

console.log(JSON.stringify([
  disconnectedLayout(),
  ...['dag_small.json', 'index_fallback.json', 'long_math.json'].map(name => runFixture(name)),
  runFixture('dag_small.json', true), runFixture('index_fallback.json', true),
  runFixture('dag_small.json', false, true),
  runFixture('long_math.json', false, false, 'release'),
  runFixture('dag_small.json', false, false, null, true),
]));
