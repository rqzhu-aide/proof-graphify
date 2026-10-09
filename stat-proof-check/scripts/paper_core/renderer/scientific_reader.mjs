// Shared display components. Scientific records, evidence and graph layouts stay in adapters.
import { readFileSync } from 'node:fs';
import { applyTemplate, esc } from './assets/archify/utils.mjs';

export const KINDS = {
  assumption: ['Assumption', '#60a5fa', '#2563eb'], definition: ['Definition', '#94a3b8', '#475569'],
  lemma: ['Lemma', '#c4b5fd', '#7c3aed'], proposition: ['Proposition', '#a5b4fc', '#4f46e5'],
  theorem: ['Theorem', '#e879f9', '#a21caf'], corollary: ['Corollary', '#67e8f9', '#0e7490'],
  external_result: ['External result', '#cbd5e1', '#64748b'],
};
export const BOX = { w: 170, h: 64, column: 275, row: 108, margin: 36 };
export const SCIENTIFIC_READER_CSS = readFileSync(new URL('./scientific_reader.css', import.meta.url), 'utf8');

function replaceOnce(template, original, replacement) {
  if (template.split(original).length !== 2) throw new Error(`Scientific reader adaptation point changed: ${original}`);
  return template.replace(original, () => replacement);
}
export function adaptScientificReaderTemplate(template) {
  const changes = [
    ['if (chip.hidden || activeIds.length !== 1) return;', 'if (chip.hidden || !container.contains(chip) || activeIds.length !== 1) return;'],
    ['if (chip && !chip.hidden) {', 'if (chip && !chip.hidden && container.contains(chip)) {'],
    ['if (!passport || passport.hidden || passportYielded) return passportYielded;', 'if (!passport || passport.hidden || !container.contains(passport) || passportYielded) return passportYielded;'],
    ['var desiredWidth = availableSvgHeight * ratio + chrome.diagramX;', 'var desiredWidth = maxWidth;'],
    ['settleOverflow(minWidth);', '// Scientific disclosures use document scrolling without resizing the graph.'],
    ['meta.textContent = [viewerKindLabel(item.type), item.id, item.sublabel, item.tag]', 'meta.textContent = [viewerKindLabel(item.type), item.context, item.sublabel, item.tag]'],
    ['meta.title = [viewerKindLabel(item.type), item.id, item.context, item.sublabel, item.tag]', 'meta.title = [viewerKindLabel(item.type), item.context, item.sublabel, item.tag]'],
    ["if (target.closest('[data-node-id], [data-relationship-hit-key], .overview-map')) return;", "if (target.closest('[data-node-id], [data-relationship-hit-key], .overview-map, .toolbar, .diagram-nav, .proof-view-controls, .proof-reader, #proof-selection, .proof-index, .proof-main-navigation')) return;"],
    [String.raw`\.c-|\.t-|\.a-|\.m-`, String.raw`\.c-|\.t-|\.a-|\.m-|\.proof-|\.k-`],
    ["probe.setAttribute('data-theme', themeAttr);", "probe.setAttribute('data-theme', themeAttr); probe.className = 'proof-svg';"],
    ["var themeHost = document.querySelector('[data-theme=\"' + theme + '\"]') || document.documentElement;", "var themeHost = document.querySelector('svg.proof-svg') || document.documentElement;"],
  ];
  for (const [original, replacement] of changes) template = replaceOnce(template, original, replacement);
  // Keep native node events below route-probe capture and make ordinary activation idempotent.
  // The common document bridge owns external links and badges, not a second node click.
  if (template.split('set(id);').length !== 3) throw new Error('Scientific reader native node handlers changed');
  template = template.replaceAll('set(id);', 'set(id, { toggle: false });');
  return template;
}
export function archifyPage({ templatePath, template, title, svg, beforeGraph = '', afterGraph = '', css = '', runtime = '', data = '', fontStyle, index = false }) {
  let source = adaptScientificReaderTemplate(template ?? readFileSync(templatePath, 'utf8'));
  if (fontStyle) source = source.replace(/<style id="archify-fonts">[\s\S]*?<\/style>/, () => fontStyle);
  let html = applyTemplate(source, { title, subtitle: '', svg, cards: afterGraph, locale: 'en' });
  html = html.replace('<div class="diagram-container"', () => `${beforeGraph}\n<div class="diagram-container"`);
  html = html.replace('</head>', () => `<style id="scientific-reader-style">${SCIENTIFIC_READER_CSS}\n${css}</style>\n</head>`);
  html = html.replace('<body>', () => `<body data-reader-layout="${index ? 'index' : 'graph'}" data-proof-layout="${index ? 'index' : 'dag'}"><script>document.documentElement.setAttribute('data-js','');</script>`);
  html = html.replace('</body>', () => `${data}${runtime ? `<script id="proof-runtime">${runtime}</script>` : ''}</body>`);
  return html;
}
export function mainResultNavigation({ entries, heading = 'Main results', graphAvailable = true, traceHtml = '' }) {
  return `<section class="proof-main-navigation proof-navigation" aria-labelledby="proof-main-title"><h2 id="proof-main-title">${esc(heading)}</h2><div class="proof-main-list" id="proof-main-results">${entries.map(entry => `<button type="button" data-reader-open="${esc(entry.key)}" data-proof-main="${esc(entry.nodeId || '')}" class="k-${esc(entry.kind)} c-${esc(entry.kind)}" aria-pressed="false" title="${esc(`${entry.label}: ${entry.caption || ''}. Open statement and supporting dependencies.`)}"><strong>${esc(entry.label)}</strong><span>${esc(entry.caption || '')}</span></button>`).join('')}</div>${graphAvailable ? '<div class="proof-view-controls"><button id="proof-full-structure" type="button">Fit complete structure</button><button id="proof-readable-view" type="button">Readable view</button><p id="proof-view-status" role="status" aria-live="polite">Select a result or connection to read its statement and supporting evidence.</p></div>' : ''}${traceHtml}</section>`;
}
function attributes(attrs = {}) {
  return Object.entries(attrs).map(([key, value]) => ` ${key}="${esc(value)}"`).join('');
}
export function readingSection({ role = 'logic', title, bodyHtml, attrs = {} }) {
  return `<section class="proof-reading-section proof-${role}-section"${attributes(attrs)}>${title ? `<h4>${esc(title)}</h4>` : ''}${bodyHtml}</section>`;
}
export function sourceDisclosure({ title = 'Sources and locators', bodyHtml, attrs = {} }) {
  return `<details class="proof-evidence proof-disclosure" data-reader-disclosure="sources"${attributes(attrs)}><summary>${esc(title)}</summary>${bodyHtml}</details>`;
}
export function scientificSearchPanel() {
  return `<section id="proof-search-panel" class="proof-panel" aria-labelledby="proof-search-heading"><h2 id="proof-search-heading">Search the saved scientific content</h2><div class="proof-search-row"><label for="proof-search">Search statements, source passages, assumptions and explanations</label><input id="proof-search" type="search" autocomplete="off" spellcheck="false" placeholder="Search a result, condition or explanation"></div><p id="proof-search-status" class="proof-muted" role="status" aria-live="polite">Search runs entirely in this page over the saved scientific content.</p><ol id="proof-search-results" class="proof-search-results" aria-label="Search results"></ol></section>`;
}
export function mathDisplayNotes(summary, bodyHtml = '') {
  const messages = (summary?.messages || []).map(message => typeof message === 'string' ? message : message.message || '').filter(Boolean);
  if (!messages.length) return '';
  return `<aside class="proof-render-warnings" role="note" data-reader-math-notes><strong>Math display notes</strong><ul>${messages.slice(0, 8).map(message => `<li>${esc(message)}</li>`).join('')}</ul>${bodyHtml ? sourceDisclosure({title:'Affected formulas and source text',bodyHtml}) : ''}${messages.length > 8 || summary.messages_truncated || summary.groups_truncated ? '<p>The displayed notes are truncated. The saved build contains the complete diagnostics.</p>' : ''}<p>These notes concern mathematical display and do not change the scientific assessment.</p></aside>`;
}
function safeJson(value) { return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026'); }
export function readerRuntime({ targets, searchEntries, graphAvailable = true }) {
  return `(${initializeScientificReader.toString()})(${safeJson({ targets, searchEntries, graphAvailable })});`;
}

function initializeScientificReader(data) {
  'use strict';
  var doc = document, root = doc.documentElement, viewer = window.Archify;
  var svg = data.graphAvailable ? doc.querySelector('.diagram-container svg') : null;
  var chip = doc.getElementById('focus-chip'), container = doc.querySelector('.diagram-container');
  var details = doc.getElementById('proof-details'), panel = doc.getElementById('proof-selection');
  var current = '', activator = null, printState = null;
  var targets = data.targets, nodeList = svg ? Array.from(svg.querySelectorAll('g[data-node-id]')) : [];
  var preview = doc.getElementById('proof-tooltip'), previewTimer = null, previewFrame = null;
  var keyboardNavigation = false, previewNode = null;
  var previewEnabled = !!(svg && preview && nodeList.some(function (node) { return doc.getElementById('proof-hover-' + node.getAttribute('data-node-id')); }));
  root.setAttribute('data-js', '');
  if (svg && chip && container) {
    container.insertAdjacentElement('afterend', chip);
    chip.removeAttribute('data-radar-yielded'); chip.removeAttribute('aria-hidden');
    if (details) { chip.insertAdjacentElement('afterend', details); details.classList.add('proof-reader'); }
    var reach = chip.querySelector('.semantic-passport-reach-label');
    if (reach) reach.textContent = 'Trace dependencies';
    var eyebrow = chip.querySelector('.relationship-lens-eyebrow');
    if (eyebrow) eyebrow.textContent = 'Result details';
    if (!panel && targets.some(function (target) { var element = doc.getElementById(target.articleId); return element && element.tagName.toLowerCase() === 'template'; })) {
      panel = doc.createElement('div'); panel.id = 'proof-selection'; panel.classList.add('proof-reader'); panel.setAttribute('aria-label', 'Selected statement and connections');
      chip.querySelector('.relationship-lens-head').insertAdjacentElement('afterend', panel);
    }
  }
  var clearButton = doc.getElementById('btn-focus-clear');
  if (clearButton) clearButton.setAttribute('aria-label', 'Close result details');
  var indexTheme = doc.getElementById('proof-index-theme');
  if (indexTheme) indexTheme.addEventListener('click', function () { root.setAttribute('data-theme', root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'); });
  function hidePreview() {
    if (previewTimer !== null) clearTimeout(previewTimer); previewTimer = null;
    if (previewFrame !== null) cancelAnimationFrame(previewFrame); previewFrame = null;
    if (preview) preview.hidden = true;
  }
  function showPreview(node) {
    if (!previewEnabled || current || printState || viewer?.focus?.active() || viewer?.focus?.relationship()) return;
    var template = doc.getElementById('proof-hover-' + node.getAttribute('data-node-id'));
    if (!template) return;
    // The adapter has already escaped and prepared this short scientific preview.
    preview.innerHTML = template.innerHTML; preview.hidden = false;
    var rect = node.getBoundingClientRect();
    var left = Math.max(12, Math.min(rect.left, window.innerWidth - preview.offsetWidth - 12));
    var top = rect.bottom + 10;
    if (top + preview.offsetHeight > window.innerHeight - 12) top = Math.max(12, rect.top - preview.offsetHeight - 10);
    preview.style.left = left + 'px'; preview.style.top = top + 'px';
  }
  function showFocusedPreview() {
    if (previewFrame !== null) cancelAnimationFrame(previewFrame);
    previewFrame = requestAnimationFrame(function () {
      previewFrame = null;
      if (previewNode && doc.activeElement === previewNode) showPreview(previewNode);
    });
  }
  if (previewEnabled) {
    svg.addEventListener('pointerover', function (event) {
      var node = event.target.closest('[data-node-id]'); if (!node || current || printState) return;
      hidePreview(); previewTimer = setTimeout(function () { previewTimer = null; showPreview(node); }, 280);
    });
    svg.addEventListener('pointerout', function (event) {
      var node = event.target.closest('[data-node-id]'); if (node && node.contains(event.relatedTarget)) return;
      hidePreview();
    });
    svg.addEventListener('focusin', function (event) {
      previewNode = keyboardNavigation ? event.target.closest('[data-node-id]') : null;
      if (previewNode) showFocusedPreview();
    });
    svg.addEventListener('focusout', function () { previewNode = null; hidePreview(); });
    doc.addEventListener('pointerdown', function () { keyboardNavigation = false; previewNode = null; hidePreview(); }, true);
    function previewViewportChanged() {
      if (previewNode && doc.activeElement === previewNode) showFocusedPreview(); else hidePreview();
    }
    window.addEventListener('resize', previewViewportChanged);
    window.addEventListener('scroll', previewViewportChanged, true);
  }
  function query(scope, attr, value) {
    var escaped = String(value).replace(/["\\]/g, '\\$&');
    return scope.querySelector('[' + attr + '="' + escaped + '"]');
  }
  function hydrate(article) {
    if (!article || article.getAttribute('data-hydrated') === 'true') return;
    article.querySelectorAll('.proof-record-slot[data-record-ref]').forEach(function (slot) {
      var template = query(doc, 'data-record-template', slot.getAttribute('data-record-ref'));
      if (template) slot.replaceChildren(template.content.cloneNode(true));
    });
    article.setAttribute('data-hydrated', 'true');
  }
  function reveal(target) {
    for (var element = target; element; element = element.parentElement) if (element.tagName.toLowerCase() === 'details') element.setAttribute('open', '');
  }
  function focus(target) {
    if (!target) return;
    target.setAttribute('tabindex', '-1'); target.scrollIntoView({ block: 'start' });
    if (typeof target.focus === 'function') target.focus({ preventScroll: true });
  }
  function clearTargets() { doc.querySelectorAll('.is-target').forEach(function (element) { element.classList.remove('is-target'); }); }
  function select(key, options) {
    options = options || {};
    var target = targets.find(function (entry) { return entry.key === key; });
    var article = target && doc.getElementById(target.articleId);
    if (!article) return false;
    previewNode = null; hidePreview();
    if (options.activator) activator = options.activator;
    var changed = current !== key; current = key;
    if (svg && viewer && viewer.focus && !options.fromViewer) {
      if (target.nodeId && viewer.focus.active() !== target.nodeId) viewer.focus.set(target.nodeId, { toggle: false });
      else if (target.edgeId && (!viewer.focus.relationship() || viewer.focus.relationship().id !== target.edgeId)) viewer.focus.inspectRelationshipById(target.edgeId, { toggle: false });
    }
    if (article.tagName.toLowerCase() === 'template') {
      if (!panel) panel = doc.getElementById('proof-index-item-' + target.nodeId) || doc.getElementById('proof-index-use-' + target.edgeId);
      if (!panel) return false;
      if (changed || !panel.innerHTML) panel.innerHTML = article.innerHTML;
      article = panel;
    } else {
      hydrate(article);
      targets.forEach(function (entry) { var element = doc.getElementById(entry.articleId); if (element && element.tagName.toLowerCase() !== 'template') element.classList.toggle('is-active', element === article); });
      article.classList.add('is-active');
    }
    var empty = doc.getElementById('proof-detail-empty'); if (empty) empty.classList.add('is-hidden');
    doc.querySelectorAll('[data-proof-main]').forEach(function (button) { button.setAttribute('aria-pressed', String(button.getAttribute('data-proof-main') === target.nodeId)); });
    nodeList.forEach(function (node) { node.setAttribute('aria-pressed', String(node.getAttribute('data-node-id') === target.nodeId)); });
    var destination = options.section ? query(article, 'data-proof-section', options.section) : article;
    destination = destination || article;
    if (options.record) destination = query(destination, 'data-record-ref', options.record) || query(article, 'data-record-ref', options.record) || query(article, 'data-reader-search-key', options.record) || destination;
    if (options.obligationId) destination = query(destination, 'data-obligation-id', options.obligationId) || destination;
    clearTargets(); if (destination !== article) destination.classList.add('is-target');
    reveal(destination);
    if (!options.silent) focus(destination === article ? article.querySelector('.proof-detail-heading') || article : destination);
    return true;
  }
  function clear(restoreFocus) {
    previewNode = null; hidePreview();
    if (viewer && viewer.focus && data.graphAvailable) viewer.focus.clear();
    current = ''; if (panel && panel.id === 'proof-selection') panel.innerHTML = '';
    targets.forEach(function (entry) { var article = doc.getElementById(entry.articleId); if (article && article.tagName.toLowerCase() !== 'template') article.classList.remove('is-active'); });
    doc.querySelectorAll('[data-proof-main]').forEach(function (button) { button.setAttribute('aria-pressed', 'false'); });
    var empty = doc.getElementById('proof-detail-empty'); if (empty) empty.classList.remove('is-hidden');
    clearTargets(); if (restoreFocus) focus(activator || nodeList[0] || doc.getElementById('proof-main-title'));
  }
  function readableView(id) {
    if (!svg || !viewer || !viewer.view) return;
    var node = nodeList.find(function (entry) { return entry.getAttribute('data-node-id') === id; }) || nodeList[0];
    if (!node) return;
    var label = node.querySelector('text[data-node-label]'), vb = svg.viewBox.baseVal;
    var size = label ? Number(label.getAttribute('font-size')) || 14 : 14;
    var base = Math.min(svg.clientWidth / vb.width, svg.clientHeight / vb.height);
    var scale = Math.max(1, Math.min(3, Math.ceil(12 / (size * base) * 4) / 4));
    var x = Number(node.getAttribute('data-node-x')), y = Number(node.getAttribute('data-node-y'));
    if (!node.hasAttribute('data-node-x')) { var rect = node.querySelector('rect'); x = rect ? Number(rect.getAttribute('x')) : 0; y = rect ? Number(rect.getAttribute('y')) : 0; }
    viewer.view.centerAt(x + 85, y + 32, { scale: scale, minimumScale: scale, instant: true });
    var status = doc.getElementById('proof-view-status'); if (status) status.textContent = 'Readable view shows part of the selected graph. Drag the background or select a result to navigate.';
  }
  function syncViewer() {
    if (!svg || !viewer || !viewer.focus || printState) return;
    var active = viewer.focus.active(), relation = viewer.focus.relationship();
    var target = targets.find(function (entry) { return relation ? entry.edgeId === relation.id : typeof active === 'string' && entry.nodeId === active; });
    if (target && target.key !== current) select(target.key, { fromViewer: true });
    else if (!target && current) clear(false);
    svg.querySelectorAll('[data-edge-badge]').forEach(function (badge) {
      var path = query(svg, 'data-edge-id', badge.getAttribute('data-edge-badge'));
      if (path && (svg.hasAttribute('data-reach-active') ? path.hasAttribute('data-reach-match') : path.hasAttribute('data-focus-match'))) badge.setAttribute('data-proof-emphasized', '');
      else badge.removeAttribute('data-proof-emphasized');
    });
  }
  if (svg && viewer && viewer.focus) new MutationObserver(syncViewer).observe(svg, { subtree: true, attributes: true, attributeFilter: ['data-focus-active', 'data-focus-selected', 'data-relationship-pin-active', 'data-relationship-pinned', 'data-reach-active', 'data-reach-match'] });
  else ['btn-export', 'proof-full-structure', 'proof-readable-view'].forEach(function (id) { var button = doc.getElementById(id); if (button) { button.disabled = true; button.hidden = true; } });
  function activation(event) {
    var origin = event.target; if (!origin || typeof origin.closest !== 'function') return;
    var badge = origin.closest('[data-proof-use],[data-edge-badge]');
    var open = origin.closest('[data-reader-open],[data-proof-focus],[data-proof-main],.proof-jump,[data-focus-node]');
    var target, options = { activator: open || badge || origin };
    if (badge) target = targets.find(function (entry) { return entry.edgeId === (badge.getAttribute('data-proof-use') || badge.getAttribute('data-edge-badge')); });
    else if (open) {
      var key = open.getAttribute('data-reader-open') || open.getAttribute('data-jump-detail');
      target = key ? targets.find(function (entry) { return entry.key === key; }) : targets.find(function (entry) { return entry.nodeId === (open.getAttribute('data-proof-main') || open.getAttribute('data-proof-focus') || open.getAttribute('data-focus-node')); });
      options.section = open.getAttribute('data-jump-section'); options.record = open.getAttribute('data-jump-record');
    } else if (svg && svg.contains(origin)) {
      var node = origin.closest('[data-node-id]');
      if (node) { previewNode = null; hidePreview(); activator = node; setTimeout(syncViewer, 0); return; }
    }
    if (target) {
      event.preventDefault(); if (badge) event.stopPropagation(); select(target.key, options);
      if (open && (open.hasAttribute('data-proof-main') || open.hasAttribute('data-focus-node'))) readableView(target.nodeId);
    } else if (origin.closest('.proof-back,#btn-focus-clear')) clear(true);
    else setTimeout(syncViewer, 0);
  }
  doc.addEventListener('click', activation, true);
  doc.addEventListener('keydown', function (event) {
    keyboardNavigation = true;
    if (event.key === 'Escape') { previewNode = null; hidePreview(); }
    if (event.key === 'Escape' && current) { event.preventDefault(); clear(true); return; }
    var badge = event.target.closest && event.target.closest('[data-proof-use],[data-edge-badge]');
    if (badge && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); activation(event); }
    var node = event.target.closest && event.target.closest('[data-node-id]');
    if (!svg || !node) return;
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activation(event); return; }
    var next = null, index = nodeList.indexOf(node), y = Number(node.getAttribute('data-node-y'));
    if (event.key === 'Home') next = nodeList[0];
    else if (event.key === 'End') next = nodeList[nodeList.length - 1];
    else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      var forward = event.key === 'ArrowRight', id = node.getAttribute('data-node-id');
      var edges = Array.from(svg.querySelectorAll('path[data-edge-' + (forward ? 'from' : 'to') + '="' + id + '"]'));
      var candidates = edges.map(function (edge) { return nodeList.find(function (entry) { return entry.getAttribute('data-node-id') === edge.getAttribute('data-edge-' + (forward ? 'to' : 'from')); }); }).filter(Boolean);
      next = candidates.sort(function (a, b) { return Math.abs(Number(a.getAttribute('data-node-y')) - y) - Math.abs(Number(b.getAttribute('data-node-y')) - y); })[0] || nodeList[index + (forward ? 1 : -1)];
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      var direction = event.key === 'ArrowDown' ? 1 : -1;
      next = nodeList.filter(function (entry) { return entry !== node && entry.getAttribute('data-node-rank') === node.getAttribute('data-node-rank') && (Number(entry.getAttribute('data-node-y')) - y) * direction > 0; }).sort(function (a, b) { return Math.abs(Number(a.getAttribute('data-node-y')) - y) - Math.abs(Number(b.getAttribute('data-node-y')) - y); })[0];
    } else return;
    event.preventDefault(); if (next) { readableView(next.getAttribute('data-node-id')); if (typeof next.focus === 'function') next.focus({ preventScroll: true }); }
  });
  var fit = doc.getElementById('proof-full-structure'), readable = doc.getElementById('proof-readable-view');
  if (fit) fit.addEventListener('click', function () {
    clear(false); if (viewer?.semanticLens) viewer.semanticLens.clear({ preserveView: true });
    if (viewer?.routeProbe) viewer.routeProbe.clear({ restoreFocus: false }); if (viewer?.view) viewer.view.reset();
  });
  if (readable) readable.addEventListener('click', function () { readableView(viewer?.focus?.active()); });
  var showAll = doc.getElementById('proof-show-all');
  function allDetails() { doc.querySelectorAll('[data-reader-article]').forEach(hydrate); }
  function applyShowAll() { if (showAll?.checked) allDetails(); root.classList.toggle('show-all-details', !!showAll?.checked); }
  if (showAll) showAll.addEventListener('change', applyShowAll); applyShowAll();
  window.addEventListener('beforeprint', function () {
    previewNode = null; hidePreview();
    if (printState) return;
    printState = { key: current, activator: activator, showAll: !!showAll?.checked, classState: root.classList.contains('show-all-details'), disclosures: [] };
    allDetails(); root.classList.add('show-all-details');
    doc.querySelectorAll('details').forEach(function (element) { if (element.closest('.proof-reader') || element.closest('.proof-index') || element.hasAttribute('data-reader-disclosure')) { printState.disclosures.push([element, element.hasAttribute('open')]); element.setAttribute('open', ''); } });
  });
  window.addEventListener('afterprint', function () {
    if (!printState) return;
    printState.disclosures.forEach(function (entry) { if (entry[1]) entry[0].setAttribute('open', ''); else entry[0].removeAttribute('open'); });
    root.classList.toggle('show-all-details', printState.classState); if (showAll) showAll.checked = printState.showAll;
    current = printState.key; activator = printState.activator; printState = null;
  });
  var search = doc.getElementById('proof-search'), results = doc.getElementById('proof-search-results'), searchStatus = doc.getElementById('proof-search-status');
  var entries = data.searchEntries.map(function (entry) { return { ...entry, lower: entry.text.toLowerCase(), lookup: (entry.text + ' ' + (entry.aliases || []).join(' ')).toLowerCase() }; });
  function element(tag, className, text) { var node = doc.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function runSearch() {
    if (!search || !results || !searchStatus) return;
    var raw = (search.value || '').trim().toLowerCase(); results.textContent = '';
    if (!raw) { searchStatus.textContent = 'Type to search the saved scientific content.'; return; }
    var terms = raw.split(/\s+/), matches = entries.filter(function (entry) { return terms.every(function (term) { return entry.lookup.includes(term); }); });
    searchStatus.textContent = matches.length > 40 ? 'Showing the first 40 matching passages; further matches exist.' : matches.length ? matches.length + ' matching passage' + (matches.length === 1 ? '.' : 's.') : 'No matches.';
    matches.slice(0, 40).forEach(function (entry) {
      var li = doc.createElement('li'), button = element('button', 'proof-search-hit'); button.type = 'button';
      button.appendChild(element('strong', '', entry.label || 'Scientific evidence')); button.appendChild(element('span', 'proof-search-where', 'in ' + (entry.owner || 'Saved paper')));
      var position = entry.lower.indexOf(terms[0]), start = Math.max(0, position - 60), end = Math.min(entry.text.length, Math.max(0, position) + terms[0].length + 90);
      var snippet = element('span', 'proof-search-snippet');
      if (position >= 0) { snippet.appendChild(doc.createTextNode((start ? '…' : '') + entry.text.slice(start, position))); var mark = element('mark', '', entry.text.slice(position, position + terms[0].length)); snippet.appendChild(mark); snippet.appendChild(doc.createTextNode(entry.text.slice(position + terms[0].length, end) + (end < entry.text.length ? '…' : ''))); }
      else snippet.textContent = entry.text.slice(0, 150) + (entry.text.length > 150 ? '…' : '');
      button.appendChild(snippet); button.addEventListener('click', function () { select(entry.detail, { section: entry.section, record: entry.key, activator: button }); });
      li.appendChild(button); results.appendChild(li);
    });
  }
  var timer = null;
  if (search) { search.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(runSearch, 120); }); search.addEventListener('keydown', function (event) { if (event.key === 'Enter') { runSearch(); var first = results.querySelector('button'); if (first) first.click(); } }); runSearch(); }
  if (typeof location !== 'undefined' && location.hash) { var linked = doc.getElementById(location.hash.slice(1)); var target = targets.find(function (entry) { return entry.articleId === linked?.id; }); if (target) select(target.key, { silent: true }); }
  syncViewer();
}
