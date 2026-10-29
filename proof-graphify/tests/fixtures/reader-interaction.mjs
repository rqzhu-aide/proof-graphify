// Minimal adapter contract simulation, not a browser or CSS layout engine.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { decodeReaderSearchData } from '../../scripts/paper_core/renderer/scientific_reader.mjs';
import { scanHtml, decodeEntities } from '../../scripts/paper_core/renderer/html_scan.mjs';

const packet = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
packet.scripts.forEach((source, index) => new vm.Script(source, { filename: `generated-script-${index}.js` }));
if (process.argv[3] === 'compile') {
  console.log(JSON.stringify({ compiled_scripts: packet.scripts.length }));
  process.exit(0);
}

const observers = [], callbacks = new Map(), scrolls = [];
let callbackId = 0;
class Element {
  constructor(row = {}) {
    this.tagName = row.tag || 'div'; this.attrs = { ...(row.attrs || {}) };
    this.children = []; this.parentElement = null; this.listeners = new Map();
    this._html = row.innerHTML || ''; this._text = row.text || '';
    this.hidden = Object.hasOwn(this.attrs, 'hidden'); this.open = false;
    this.style = { removeProperty(key) { delete this[key]; }, setProperty(key, value) { this[key] = value; } };
    this.clientWidth = 600; this.clientHeight = 110; this.offsetWidth = 460; this.offsetHeight = 240;
    this.viewBox = { baseVal: { x: 0, y: 0, width: 600, height: 110 } };
    (row.children || []).forEach(child => this.appendChild(new Element(child)));
  }
  get id() { return this.attrs.id; }
  set id(value) { this.attrs.id = value; }
  get parentNode() { return this.parentElement; }
  get innerHTML() { return this._html; }
  set innerHTML(value) {
    this._html = value; this.children = []; this._text = '';
    const scan = scanHtml(value);
    const row = element => {
      let cursor = element.openEnd, text = '';
      for (const child of element.children) { text += scan.html.slice(cursor, child.start); cursor = child.closeEnd; }
      return {tag:element.tag,attrs:element.attrs,text:decodeEntities((text+scan.html.slice(cursor,element.closeStart)).replace(/<[^>]*>/g,'')),children:element.children.map(row)};
    };
    scan.root.children.forEach(child => this.appendChild(new Element(row(child))));
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = value; this.children = []; }
  get className() { return this.attrs.class || ''; }
  set className(value) { this.attrs.class = value; }
  get classList() {
    const self = this;
    return {contains(name) { return self.className.split(/\s+/).includes(name); },
      add(name) { if (!this.contains(name)) self.className = `${self.className} ${name}`.trim(); },
      remove(name) { self.className = self.className.split(/\s+/).filter(value => value !== name).join(' '); },
      toggle(name, on) { if (on === undefined) on = !this.contains(name); if (on) this.add(name); else this.remove(name); }};
  }
  getAttribute(key) { return this.attrs[key] ?? null; }
  hasAttribute(key) { return Object.hasOwn(this.attrs, key); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  removeAttribute(key) { delete this.attrs[key]; }
  appendChild(child) {
    if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1);
    this.children.push(child); child.parentElement = this; return child;
  }
  insertAdjacentElement(position, element) {
    assert.equal(position, 'afterend');
    const parent = this.parentElement;
    if (element.parentElement) element.parentElement.children.splice(element.parentElement.children.indexOf(element), 1);
    parent.children.splice(parent.children.indexOf(this) + 1, 0, element); element.parentElement = parent;
    return element;
  }
  contains(element) { return element === this || this.children.some(child => child.contains(element)); }
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
    for (let element = this; element; element = element.parentElement)
      if (selector.split(',').some(part => element.matches(part.trim()))) return element;
    return null;
  }
  querySelectorAll(selector) {
    const results = [];
    const matches = element => selector.split(',').some(part => {
      const terms = part.trim().split(/\s+/), last = terms.pop();
      if (!element.matches(last)) return false;
      let ancestor = element.parentElement;
      while (terms.length) {
        const term = terms.pop();
        while (ancestor && !ancestor.matches(term)) ancestor = ancestor.parentElement;
        if (!ancestor) return false;
        ancestor = ancestor.parentElement;
      }
      return true;
    });
    const walk = element => element.children.forEach(child => {
      if (matches(child)) results.push(child);
      if (child.tagName !== 'template') walk(child);
    });
    walk(this); return results;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, callback, options) {
    const list = this.listeners.get(type) || [];
    list.push({ callback, capture: options === true || options?.capture === true }); this.listeners.set(type, list);
  }
  scrollIntoView() { scrolls.push(this.id || this.tagName); }
  focus() { document.activeElement = this; }
  click() { dispatch(this,{type:'click'}); }
  getBoundingClientRect() { return { left: 0, top: 0, bottom: this.clientHeight, right: this.clientWidth, width: this.clientWidth, height: this.clientHeight }; }
  dispatchEvent(event) { dispatch(this, event); return true; }
}

const document = new Element(packet.document), window = new Element({ tag: 'window' });
assert.equal(document.querySelectorAll('#proof-reader-search').length,1,'Each overview must retain exactly one scientific search payload.');
const searchPayload = document.querySelector('#proof-reader-search').textContent;
assert(!/[<>&]/.test(searchPayload),'Script-like source text must remain safely escaped in the retained payload.');
assert(decodeReaderSearchData(JSON.parse(searchPayload)).some(entry => entry.text.includes('</script><script>literal_source()</script> & <literal>')),
  'The retained payload must preserve the literal source text.');
document.getElementById = id => document.querySelector('#' + id);
document.createElement = tag => new Element({ tag });
document.createTextNode = text => new Element({ tag: '#text', text });
document.body = document.querySelector('body'); document.documentElement = document.querySelector('html');
window.innerWidth = 1200; window.innerHeight = 800;
const svg = document.querySelector('.diagram-container svg'), container = svg?.parentElement;
const chip = document.getElementById('focus-chip');
if (svg) assert(container.contains(chip), 'Fixture must begin with the upstream embedded details panel.');

function schedule(callback) { callbacks.set(++callbackId, callback); return callbackId; }
function flush() {
  for (let turn = 0; callbacks.size && turn < 20; turn++) {
    const pending = [...callbacks.values()]; callbacks.clear(); pending.forEach(callback => callback());
  }
  assert.equal(callbacks.size, 0, 'Adapter did not settle.');
}
function notifyFocus() { observers.forEach(callback => schedule(callback)); }
function dispatch(target, event) {
  event.target = target; event.preventDefault ||= () => {};
  event.stopPropagation = () => { event.stopped = true; };
  event.stopImmediatePropagation = () => { event.stopped = true; event.immediate = true; };
  const path = []; for (let element = target; element; element = element.parentElement) path.push(element);
  for (const capture of [true, false]) {
    for (const element of capture ? [...path].reverse() : path) {
      for (const listener of element.listeners.get(event.type) || [])
        if (listener.capture === capture && !event.immediate) listener.callback(event);
      if (event.stopped) return;
    }
  }
}
let active = null, relation = null, centers = 0;
const focus = {
  active: () => active, relationship: () => relation,
  set(id, options) { if (active === id && options?.toggle !== false) return this.clear(); active = id; relation = null; chip.hidden = false; svg.setAttribute('data-focus-active', id); notifyFocus(); },
  clear() { active = null; relation = null; chip.hidden = true; svg.removeAttribute('data-focus-active'); notifyFocus(); },
  inspectRelationshipById(id) { active = 'result'; relation = { id }; chip.hidden = false; notifyFocus(); },
  reposition() {},
};
// Execute the emitted native handler, including its event ordering and toggle policy.
const routeContext = {mode:'idle',container,svg,chosen:null,choose(id){this.chosen=id;}};
if (svg) {
const nativeNodeClick = packet.scripts.flatMap(source => [...source.matchAll(/svg\.addEventListener\('click', function \(event\) \{\s*if \(container\.getAttribute\('data-just-panned'\) === 'true'\) return;[\s\S]*?\n      \}\);/g)]).find(([source]) => source.includes('set(id,'))?.[0];
assert(nativeNodeClick, 'Emitted native node click is missing.');
vm.runInNewContext(nativeNodeClick, {svg,container,set:(id,options)=>focus.set(id,options),clear:()=>focus.clear(),get activeIds(){return active?[active]:[];},Archify:{view:{reveal(){}}}});
const routeIntercept = packet.scripts.flatMap(source => [...source.matchAll(/function interceptSelection\(event\) \{[\s\S]*?\n      \}/g)]).find(([source]) => source.includes('stopImmediatePropagation'))?.[0];
assert(routeIntercept, 'Native route interception is missing.');
routeContext.choose = id => {routeContext.chosen=id;};
vm.runInNewContext(routeIntercept+"\nsvg.addEventListener('click', interceptSelection, true);",routeContext);
document.getElementById('btn-focus-clear').addEventListener('click', () => focus.clear());
// Exercise the actual emitted outside-click handler as well as the proof
// adapter: its capture phase can erase selection before a control runs.
const outsideClick = packet.scripts.flatMap(source => [...source.matchAll(
  /document\.addEventListener\('click', function \(event\) \{[\s\S]*?\}, true\);/g,
)]).find(([source]) => source.includes('chip.hidden || !target'))?.[0];
assert(outsideClick, 'Generated outside-click handler is missing.');
vm.runInNewContext(outsideClick, { document, chip, container, lensDragClickPointer:null, clear: () => focus.clear() });
}
let searchParses = 0;
const context = vm.createContext({
  document, window, Archify: { focus, view: { centerAt() { centers++; }, reset() {} } },
  JSON:{parse(value) { searchParses++; return JSON.parse(value); }},
  location: {hash:process.argv[3]?.startsWith('fragment') ? (process.argv[3].includes('use') ? '#proof-index-use-independence-use' : '#proof-index-item-result') : ''},
  MutationObserver: class { constructor(callback) { this.callback = callback; } observe() { observers.push(this.callback); } },
  requestAnimationFrame: schedule, cancelAnimationFrame: id => callbacks.delete(id),
  setTimeout: schedule, clearTimeout: id => callbacks.delete(id),
  MouseEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } },
});
window.Archify = { focus, view: { centerAt() { centers++; }, reset() {} } };
const runtime = packet.scripts.find(source => source.includes('function initializeScientificReader'));
assert(runtime, 'Generated proof runtime is missing.');
assert(!runtime.includes('SOURCE_QUOTE'),'The runtime must not serialize the scientific search entries again.');
const auditMode = process.argv[3] === 'audit';
if (auditMode) {
  document.querySelector('.proof-reader').classList.add('proof-audit');
}
vm.runInContext(runtime, context); flush();
assert.equal(searchParses,1,'Reader initialization must parse the retained search payload once.');
assert.equal(centers, 0, 'Opening the overview must retain the complete selected graph.');
if (process.argv[3]?.startsWith('fragment')) {
  const isUse = process.argv[3].includes('use');
  const linked = document.getElementById(isUse ? 'proof-index-use-independence-use' : 'proof-index-item-result');
  assert(linked,'Public fragments must resolve to real scientific articles.');
  if (svg) {
    assert(!document.getElementById('proof-full-index').hasAttribute('open'),'A direct link must not expand a duplicate full index when the selected panel is visible.');
    if (isUse) assert.equal(relation?.id,'independence-use');
    else assert.equal(active,'result');
    const panel = document.getElementById('proof-selection');
    assert.match(panel.innerHTML,isUse ? /RELATION_TEXT/ : /RESULT_TEXT/);
  } else {
    for (let ancestor=linked;ancestor;ancestor=ancestor.parentElement)
      if (ancestor.tagName==='details') assert(ancestor.hasAttribute('open'),'Graphless fragments reveal their containing disclosures.');
    assert(linked.classList.contains('is-active'));
    assert.equal(active,null);
  }
  console.log(JSON.stringify({public_fragment_resolved:true,graph_selection_preserved:!!svg,index_visible:true}));
  process.exit(0);
}
function sharedSourceSearchAndPrint() {
  const outgoingSearch = document.getElementById('proof-search'); outgoingSearch.value = 'RELATION_TEXT';
  dispatch(outgoingSearch,{type:'input'}); flush();
  const outgoingHit = document.getElementById('proof-search-results').querySelectorAll('button').find(button => button.textContent.includes('Used by'));
  assert(outgoingHit, 'Outgoing contributions have a separately labelled search result.');
  dispatch(outgoingHit,{type:'click'}); flush();
  const outgoing = document.querySelector('.is-target');
  assert.equal(outgoing.getAttribute('data-reader-search-key'),'item:assumption:outgoing');
  assert.equal(outgoing.tagName,'details');
  assert(outgoing.hasAttribute('open'), 'The target disclosure itself must open.');
  assert.equal(document.activeElement,outgoing);
  const search = document.getElementById('proof-search'); search.value = 'SOURCE_QUOTE';
  dispatch(search,{type:'input'}); flush();
  const hit = document.getElementById('proof-search-results').querySelector('button'); assert(hit);
  assert(!hit.textContent.includes('item:result'), 'Search aliases must stay hidden.');
  dispatch(hit,{type:'click'}); flush();
  const destination = document.querySelector('.is-target');
  assert.equal(destination.getAttribute('data-reader-search-key'),'item:result:source:0');
  assert.equal(document.activeElement,destination);
  for (let ancestor=destination;ancestor;ancestor=ancestor.parentElement) if (ancestor.tagName==='details') assert(ancestor.hasAttribute('open'));
  const disclosures = document.querySelectorAll('details').filter(element=>element.closest('.proof-reader') || element.closest('.proof-index') || element.hasAttribute('data-reader-disclosure'));
  const states=disclosures.map(element=>element.hasAttribute('open')), selected=active, relationId=relation?.id;
  window.listeners.get('beforeprint')[0].callback(); window.listeners.get('beforeprint')[0].callback();
  assert(disclosures.every(element=>element.hasAttribute('open')));
  window.listeners.get('afterprint')[0].callback();
  assert.deepEqual(disclosures.map(element=>element.hasAttribute('open')),states);
  assert.equal(active,selected); assert.equal(relation?.id,relationId);
  dispatch(destination,{type:'keydown',key:'Escape'});flush();assert.equal(document.activeElement,hit);
  return {source_search_exact_destination:true,outgoing_search_exact_destination:true,print_state_restored:true,escape_restored_activator:true};
}
if (process.argv[3]==='preview') {
  const tip=document.getElementById('proof-tooltip'),node=svg.querySelector('[data-node-id="assumption"]');
  const template=document.getElementById('proof-hover-assumption');
  assert.equal(tip.getAttribute('role'),'tooltip');assert(tip.hidden);
  dispatch(node,{type:'pointerover'});flush();assert(!tip.hidden);
  assert.equal(tip.innerHTML,template.innerHTML,'A preview must copy the already escaped prepared template exactly.');
  assert(tip.innerHTML.includes('&lt;literal&gt; &amp; finite variance'));
  assert(!tip.innerHTML.includes('ASSUMPTION_TEXT'),'A preview must remain the short source-backed summary.');
  dispatch(node,{type:'pointerout',relatedTarget:node.querySelector('text')});flush();assert(!tip.hidden);
  dispatch(node,{type:'pointerout',relatedTarget:document.body});flush();assert(tip.hidden);
  template.id='preview-template-unavailable';dispatch(node,{type:'pointerover'});flush();assert(tip.hidden);
  template.id='proof-hover-assumption';
  dispatch(node,{type:'pointerover'});flush();assert(!tip.hidden);
  dispatch(svg.querySelector('[data-node-id="result"]'),{type:'click'});flush();assert(tip.hidden);
  dispatch(node,{type:'pointerover'});flush();assert(tip.hidden,'Selection must suppress pending and subsequent previews.');
  dispatch(document.getElementById('btn-focus-clear'),{type:'click'});flush();
  dispatch(document.body,{type:'keydown',key:'Tab'});node.focus();dispatch(node,{type:'focusin'});flush();
  assert(!tip.hidden,'Keyboard focus must expose the same optional short preview.');
  assert.equal(tip.innerHTML,template.innerHTML);
  dispatch(window,{type:'scroll'});flush();assert(!tip.hidden,'A focused preview must reposition after scrolling.');
  dispatch(node,{type:'focusout'});flush();assert(tip.hidden);
  dispatch(node,{type:'pointerover'});window.listeners.get('beforeprint')[0].callback();flush();assert(tip.hidden);
  dispatch(node,{type:'pointerover'});flush();assert(tip.hidden,'Print must suppress previews, including delayed timers.');
  window.listeners.get('afterprint')[0].callback();assert(tip.hidden);
  dispatch(node,{type:'pointerover'});flush();assert(!tip.hidden);
  dispatch(document.body,{type:'keydown',key:'Escape'});flush();assert(tip.hidden);
  console.log(JSON.stringify({template_bytes_preserved:true,pointer_and_keyboard_preview:true,leave_selection_and_print_dismissal:true}));process.exit(0);
}
if (process.argv[3]==='index') {
  assert.equal(document.getElementById('btn-export'),null,'An index must omit unused graph controls.');
  assert.equal(svg,null);
  assert(document.getElementById('proof-index-theme'));
  assert.equal(document.getElementById('proof-full-structure'),null);
  assert.equal(document.querySelector('.proof-results'),null,'Index mode must not duplicate the complete index.');
  assert.equal(active,null,'Index navigation must work without graph selection.');
  const theme = document.getElementById('proof-index-theme');
  theme.click();
  const firstTheme = document.documentElement.getAttribute('data-theme');
  dispatch(document.body,{type:'keydown',key:'t'});
  assert.notEqual(document.documentElement.getAttribute('data-theme'),firstTheme,'Index keyboard theme selection must work without the graph runtime.');
  const editingTheme = document.documentElement.getAttribute('data-theme');
  dispatch(document.getElementById('proof-search'),{type:'keydown',key:'t'});
  assert.equal(document.documentElement.getAttribute('data-theme'),editingTheme,'Typing a search must not toggle the theme.');
  console.log(JSON.stringify(sharedSourceSearchAndPrint()));process.exit(0);
}
assert(!container.contains(chip), 'Details remain constrained by the shallow diagram instead of following it in document flow.');
assert.equal(chip.parentElement.id, 'proof-selection-host', 'Details must use the full-width slot below the graph and Results.');
assert.equal(chip.parentElement.parentElement, container.parentElement);
const panel = document.getElementById('proof-selection');
assert(chip.contains(panel), 'The statement reader is missing from the details panel.');
assert.equal(panel.classList.contains('proof-audit'), auditMode, 'Relocated panel must retain only its own product styling.');
if (document.getElementById('proof-details'))
  assert.equal(document.getElementById('proof-details').classList.contains('proof-audit'), auditMode);

dispatch(svg.querySelector('[data-node-id="assumption"]'), { type: 'click' }); flush();
assert(!chip.hidden); assert.match(panel.innerHTML, /ASSUMPTION_TEXT/);
assert(!panel.innerHTML.includes('RESULT_TEXT'));
assert.equal(scrolls.at(-1), 'proof-selection', 'Selecting an ordinary item must reveal its reading panel.');
dispatch(svg.querySelector('[data-node-id="assumption"]'), { type: 'click' }); flush();
assert.equal(active, 'assumption', 'Repeated native activation must retain the result.');
routeContext.mode='source';
dispatch(svg.querySelector('[data-node-id="result"]'),{type:'click'});flush();
assert.equal(routeContext.chosen,'result');assert.equal(active,'assumption','Route-probe capture must precede ordinary node selection.');
routeContext.mode='idle';

const resultLink = document.querySelector('.proof-results [data-reader-node="result"]');
assert.equal(resultLink.tagName,'a');
assert.equal(resultLink.getAttribute('href'),'#proof-index-item-result');
dispatch(resultLink, { type: 'click' }); flush();
assert(centers > 0, 'Explicit result navigation must retain its readable camera view.');
assert.match(panel.innerHTML, /RESULT_TEXT/);
assert.equal(resultLink.getAttribute('aria-current'),'true','The current Results entry must be announced.');
assert.equal(scrolls.at(-1), 'proof-selection', 'Result navigation must reveal the reading panel.');
for (const selector of ['#btn-theme', '#btn-preset', '#proof-readable-view', '[data-view="in"]']) {
  dispatch(document.querySelector(selector), { type: 'click' }); flush();
  assert.equal(active, 'result', `${selector} discarded the selected result.`);
  assert(!chip.hidden); assert.match(panel.innerHTML, /RESULT_TEXT/);
}

dispatch(svg.querySelector('[data-proof-use="independence-use"]'), { type: 'click' }); flush();
assert.match(panel.innerHTML, /RELATION_TEXT/);
assert.equal(scrolls.at(-1), 'proof-selection');
dispatch(document.getElementById('btn-theme'), { type: 'click' }); flush();
assert.equal(relation?.id, 'independence-use');
assert.match(panel.innerHTML, /RELATION_TEXT/);
dispatch(document.getElementById('btn-focus-clear'), { type: 'click' }); flush();
assert(chip.hidden); assert.equal(panel.innerHTML, '');
focus.set('result'); flush();
dispatch(document.getElementById('proof-full-structure'), { type: 'click' }); flush();
assert(chip.hidden); assert.equal(active, null);
focus.set('result'); flush();
dispatch(document.body, { type: 'click' }); flush();
assert(chip.hidden); assert.equal(active, null);
console.log(JSON.stringify({ details_outside_diagram: true, checked_selections: ['assumption', 'result', 'independence-use'], close_cleared_details: true, controls_preserved_selection: true, background_and_fit_cleared_details: true,...sharedSourceSearchAndPrint() }));
