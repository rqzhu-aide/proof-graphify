// Shared display components. Scientific records, evidence and graph layouts stay in adapters.
import { readFileSync } from 'node:fs';
import { applyTemplate, esc } from './assets/archify/utils.mjs';
import { scanHtml } from './html_scan.mjs';

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
  // These native owners are replaced, not initialized and then overridden.
  for (const name of ['readerLayout', 'outline']) {
    const start = template.indexOf(`    Archify.${name} = (function () {`);
    const end = template.indexOf('\n    })();', start);
    if (start < 0 || end < start) throw new Error(`Missing Archify ${name} block`);
    template = template.slice(0, start) + template.slice(end + '\n    })();'.length);
  }
  const cssStart = template.indexOf('\n    .cards {');
  const cssEnd = template.indexOf('\n    .node-outline-item {', cssStart);
  if (cssStart < 0 || cssEnd < cssStart) throw new Error('Missing Archify rail style boundaries');
  template = template.slice(0, cssStart) + template.slice(cssEnd);
  const changes = [
    ['if (chip.hidden || activeIds.length !== 1) return;', 'if (chip.hidden || !container.contains(chip) || activeIds.length !== 1) return;'],
    ['if (chip && !chip.hidden) {', 'if (chip && !chip.hidden && container.contains(chip)) {'],
    ['if (!passport || passport.hidden || passportYielded) return passportYielded;', 'if (!passport || passport.hidden || !container.contains(passport) || passportYielded) return passportYielded;'],
    ['meta.textContent = [viewerKindLabel(item.type), item.id, item.sublabel, item.tag]', 'meta.textContent = [viewerKindLabel(item.type), item.context, item.sublabel, item.tag]'],
    ['meta.title = [viewerKindLabel(item.type), item.id, item.context, item.sublabel, item.tag]', 'meta.title = [viewerKindLabel(item.type), item.context, item.sublabel, item.tag]'],
    ["if (target.closest('[data-node-id], [data-relationship-hit-key], .overview-map')) return;", "if (target.closest('[data-node-id], [data-relationship-hit-key], .overview-map, .toolbar, .diagram-nav, .proof-view-controls, .proof-reader, #proof-selection, .proof-index, .proof-results')) return;"],
    [String.raw`\.c-|\.t-|\.a-|\.m-`, String.raw`\.c-|\.t-|\.a-|\.m-|\.proof-|\.k-`],
    ["var probe = document.createElement('div');\n          probe.setAttribute('data-theme', themeAttr);", "var probe = document.createElementNS('http://www.w3.org/2000/svg', 'svg');\n          probe.setAttribute('class', svg.getAttribute('class') || 'proof-svg');\n          probe.setAttribute('data-theme', themeAttr);"],
    ['var resolvedTheme = requestedTheme && resolveVars(lockedTheme);\n          var computed = getComputedStyle(document.documentElement);', 'var resolvedTheme = requestedTheme && resolveVars(lockedTheme);\n          var computed = getComputedStyle(svg);'],
    ['":root, svg { " + darkTheme.vars', '":root, svg.proof-svg { " + darkTheme.vars'],
    ['"@media (prefers-color-scheme: light) { :root, svg { " + lightTheme.vars', '"@media (prefers-color-scheme: light) { :root, svg.proof-svg { " + lightTheme.vars'],
    ['":root, svg { " + vars', '":root, svg.proof-svg { " + vars'],
    ['if (requestedTheme) clone.setAttribute(\'data-theme\', lockedTheme);', 'clone.setAttribute(\'data-theme\', lockedTheme);'],
    ['function beginLensDrag(event) {', 'function beginLensDrag(event) {\n        if (!container.contains(chip)) return;'],
    ['id="btn-focus-move" type="button"', 'id="btn-focus-move" type="button" hidden disabled tabindex="-1"'],
  ];
  for (const [original, replacement] of changes) template = replaceOnce(template, original, replacement);
  // Keep native node events below route-probe capture and make ordinary activation idempotent.
  // The common document bridge owns external links and badges, not a second node click.
  if (template.split('set(id);').length !== 3) throw new Error('Scientific reader native node handlers changed');
  template = template.replaceAll('set(id);', 'set(id, { toggle: false });');
  return template;
}
export function archifyPage({ templatePath, template, title, svg, beforeGraph = '', resultsHtml = '', afterGraph = '', css = '', runtime = '', data = '', fontStyle, index = false }) {
  let source = adaptScientificReaderTemplate(template ?? readFileSync(templatePath, 'utf8'));
  if (fontStyle) source = source.replace(/<style id="archify-fonts">[\s\S]*?<\/style>/, () => fontStyle);
  let html = applyTemplate(source, { title, subtitle: '', svg, cards: resultsHtml, locale: 'en' });
  const scan = scanHtml(html);
  const edits = [];
  for (const element of scan.elements) {
    const classes = (element.attrs.class || '').split(/\s+/);
    if (classes.includes('diagram-container')) {
      edits.push([element.start, index ? element.closeEnd : element.start, `<section class="proof-reader-before">${beforeGraph}</section>\n`]);
    } else if (element.attrs.id === 'reader-rail') {
      edits.push([element.closeEnd, element.closeEnd, `<section id="proof-selection-host" aria-label="Selected scientific content"></section><section class="proof-reader-after">${afterGraph}</section>`]);
      if (index || !resultsHtml) edits.push([element.start, element.closeEnd, '']);
    } else if (element.attrs.id === 'node-outline' || classes.includes('rail-controls') || element.attrs.id === 'rail-reveal') {
      // The entire rail/stage may already be removed in index mode.
      if (!index && (resultsHtml || element.attrs.id === 'rail-reveal')) edits.push([element.start, element.closeEnd, '']);
    } else if (index && classes.includes('toolbar')) {
      edits.push([element.start, element.closeEnd, '<div class="toolbar no-print"><button type="button" id="proof-index-theme" aria-label="Toggle light and dark theme">Theme</button></div>']);
    } else if (index && element.tag === 'script' && html.slice(element.openEnd, element.closeStart).includes('var Archify = {};')) {
      edits.push([element.start, element.closeEnd, '']);
    }
  }
  for (const [start, end, value] of edits.sort((a, b) => b[0] - a[0] || b[1] - a[1])) html = html.slice(0, start) + value + html.slice(end);
  html = html.replace('</head>', () => `<style id="scientific-reader-style">${SCIENTIFIC_READER_CSS}\n${css}</style>\n</head>`);
  const viewBox = scanHtml(svg).elements.find(element => element.tag === 'svg')?.attrs.viewbox?.trim().split(/[\s,]+/).map(Number);
  const wide = !index && viewBox?.[3] > 0 && viewBox[2] / viewBox[3] >= 1.55;
  if (wide) html = html.replace('class="diagram-container"', 'class="diagram-container" data-wide-diagram="true"');
  html = html.replace('<body>', () => `<body data-reader-layout="${index ? 'index' : 'graph'}" data-proof-layout="${index ? 'index' : 'dag'}"><script>document.documentElement.setAttribute('data-js','');${wide ? 'document.documentElement.setAttribute("data-diagram-shape","wide");' : ''}${index ? 'document.documentElement.removeAttribute("data-present");document.documentElement.removeAttribute("data-embed");' : ''}</script>`);
  html = html.replace('</body>', () => `${data}${runtime ? `<script id="proof-runtime">${runtime}</script>` : ''}</body>`);
  return html;
}
export function resultsNavigation({ entries, mainIds = [], heading = 'Main results', graphAvailable = true }) {
  if (!graphAvailable || !entries.length) return '';
  const remaining = new Map(entries.map(entry => [entry.nodeId, entry]));
  const main = mainIds.map(id => { const entry = remaining.get(id); remaining.delete(id); return entry; }).filter(Boolean);
  const groups = main.length ? [{heading, entries:main}] : [];
  for (const kind of [...new Set([...remaining.values()].map(entry => entry.kind))]) {
    groups.push({heading:KINDS[kind]?.[0] || 'Other results', entries:[...remaining.values()].filter(entry => entry.kind === kind)});
  }
  return `<nav class="proof-results" id="proof-results" aria-labelledby="proof-results-title"><h2 id="proof-results-title">Results</h2>${groups.map(group => `<section class="proof-results-group"><h3>${esc(group.heading)}</h3><ul class="proof-results-list">${group.entries.map(entry => `<li><a class="node-outline-item proof-result-link k-${esc(entry.kind)}" href="#${esc(entry.articleId)}" data-reader-open="${esc(entry.key)}" data-reader-node="${esc(entry.nodeId)}"><span class="node-outline-dot" aria-hidden="true"></span><strong>${esc(entry.label)}</strong>${entry.caption ? `<small>${esc(entry.caption)}</small>` : ''}</a></li>`).join('')}</ul></section>`).join('')}</nav>`;
}
export function viewControls({ traceHtml = '' } = {}) {
  return '<div class="proof-view-controls"><button id="proof-full-structure" type="button">Fit complete structure</button><button id="proof-readable-view" type="button">Readable view</button><p id="proof-view-status" role="status" aria-live="polite">Select a result or connection to read its statement and supporting evidence.</p></div>' + traceHtml;
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
  var auditReader = !!doc.querySelector('.proof-reader.proof-audit');
  var current = '', currentTarget = null, activator = null, printState = null;
  var targets = data.targets, nodeList = svg ? Array.from(svg.querySelectorAll('g[data-node-id]')) : [];
  var byKey = new Map(), byNode = new Map(), byEdge = new Map();
  targets.forEach(function (target) {
    if (!byKey.has(target.key)) byKey.set(target.key, target);
    if (target.nodeId) byNode.set(target.nodeId, target);
    if (target.edgeId) byEdge.set(target.edgeId, target);
  });
  var articles = Array.from(new Set(targets.map(function (target) { return doc.getElementById(target.articleId); }).filter(Boolean)));
  var navigation = Array.from(doc.querySelectorAll('[data-reader-node]'));
  var preview = doc.getElementById('proof-tooltip'), previewTimer = null, previewFrame = null;
  var keyboardNavigation = false, previewNode = null;
  var previewEnabled = !!(svg && preview && nodeList.some(function (node) { return doc.getElementById('proof-hover-' + node.getAttribute('data-node-id')); }));
  root.setAttribute('data-js', '');
  var selectionHost = doc.getElementById('proof-selection-host');
  var fullIndex = doc.getElementById('proof-full-index');
  if (svg && fullIndex) fullIndex.removeAttribute('open');
  if (svg && chip && selectionHost) {
    selectionHost.appendChild(chip);
    chip.removeAttribute('data-radar-yielded'); chip.removeAttribute('aria-hidden');
    if (details) { selectionHost.appendChild(details); details.classList.add('proof-reader'); }
    var reach = chip.querySelector('.semantic-passport-reach-label');
    if (reach) reach.textContent = 'Trace dependencies';
    var eyebrow = chip.querySelector('.relationship-lens-eyebrow');
    if (eyebrow) eyebrow.textContent = 'Result details';
    if (!panel && targets.some(function (target) { var element = doc.getElementById(target.articleId); return element && element.tagName.toLowerCase() === 'template'; })) {
      panel = doc.createElement('div'); panel.id = 'proof-selection'; panel.classList.add('proof-reader'); panel.setAttribute('aria-label', 'Selected statement and connections');
      chip.querySelector('.relationship-lens-head').insertAdjacentElement('afterend', panel);
    }
  }
  // Relocated details retain their original audit styling and severity palette.
  if (auditReader) {
    if (details) details.classList.add('proof-audit');
    if (panel) panel.classList.add('proof-audit');
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
    var target = (options.nodeId && byNode.get(options.nodeId)) || (options.edgeId && byEdge.get(options.edgeId)) || byKey.get(key);
    var article = target && doc.getElementById(target.articleId);
    if (!article) return false;
    previewNode = null; hidePreview();
    if (options.activator) activator = options.activator;
    var changed = current !== key; current = key; currentTarget = target;
    if (svg && viewer && viewer.focus && !options.fromViewer) {
      var focusOptions = { toggle: false, updateUrl: !options.preserveHash };
      if (target.nodeId && (viewer.focus.active() !== target.nodeId || viewer.focus.relationship())) viewer.focus.set(target.nodeId, focusOptions);
      else if (target.edgeId && (!viewer.focus.relationship() || viewer.focus.relationship().id !== target.edgeId)) viewer.focus.inspectRelationshipById(target.edgeId, focusOptions);
    }
    if (article.tagName.toLowerCase() === 'template') {
      if (!panel) panel = doc.getElementById('proof-index-item-' + target.nodeId) || doc.getElementById('proof-index-use-' + target.edgeId);
      if (!panel) return false;
      if (changed || !panel.innerHTML) panel.innerHTML = article.innerHTML;
      article = panel;
    } else {
      hydrate(article);
      articles.forEach(function (element) { if (element.tagName.toLowerCase() !== 'template') element.classList.toggle('is-active', element === article); });
      article.classList.add('is-active');
    }
    var empty = doc.getElementById('proof-detail-empty'); if (empty) empty.classList.add('is-hidden');
    navigation.forEach(function (link) { if (link.getAttribute('data-reader-node') === target.nodeId) link.setAttribute('aria-current', 'true'); else link.removeAttribute('aria-current'); });
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
  function clear(restoreFocus, fromViewer) {
    previewNode = null; hidePreview();
    if (!fromViewer && viewer && viewer.focus && data.graphAvailable) viewer.focus.clear();
    current = ''; currentTarget = null; if (panel && panel.id === 'proof-selection') panel.innerHTML = '';
    articles.forEach(function (article) { if (article.tagName.toLowerCase() !== 'template') article.classList.remove('is-active'); });
    navigation.forEach(function (link) { link.removeAttribute('aria-current'); });
    var empty = doc.getElementById('proof-detail-empty'); if (empty) empty.classList.remove('is-hidden');
    clearTargets(); if (restoreFocus) focus(activator || nodeList[0] || doc.getElementById('proof-results-title'));
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
    var target = relation ? byEdge.get(relation.id) : byNode.get(active);
    if (target && target !== currentTarget) select(target.key, { fromViewer: true, nodeId: target.nodeId, edgeId: target.edgeId });
    else if (!target && current) clear(false, true);
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
    var open = origin.closest('[data-reader-open],[data-proof-focus],.proof-jump,[data-focus-node]');
    var target, options = { activator: open || badge || origin };
    if (badge) target = byEdge.get(badge.getAttribute('data-proof-use') || badge.getAttribute('data-edge-badge'));
    else if (open) {
      var key = open.getAttribute('data-reader-open') || open.getAttribute('data-jump-detail');
      var nodeId = open.getAttribute('data-reader-node') || open.getAttribute('data-proof-focus') || open.getAttribute('data-focus-node');
      target = (nodeId && byNode.get(nodeId)) || byKey.get(key);
      options.section = open.getAttribute('data-jump-section'); options.record = open.getAttribute('data-jump-record');
    } else if (svg && svg.contains(origin)) {
      var node = origin.closest('[data-node-id]');
      if (node) { previewNode = null; hidePreview(); activator = node; setTimeout(syncViewer, 0); return; }
    }
    if (target) {
      options.nodeId = target.nodeId; options.edgeId = target.edgeId;
      event.preventDefault(); if (badge) event.stopPropagation(); select(target.key, options);
      if (open && (open.hasAttribute('data-reader-node') || open.hasAttribute('data-focus-node'))) readableView(target.nodeId);
    } else if (origin.closest('.proof-back,#btn-focus-clear')) clear(true);
    else setTimeout(syncViewer, 0);
  }
  doc.addEventListener('click', activation, true);
  doc.addEventListener('keydown', function (event) {
    keyboardNavigation = true;
    if (indexTheme && !event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === 't' && !event.target.closest('input,textarea,[contenteditable]')) { event.preventDefault(); indexTheme.click(); }
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
    printState = { key: current, target: currentTarget, activator: activator, showAll: !!showAll?.checked, classState: root.classList.contains('show-all-details'), disclosures: [] };
    allDetails(); root.classList.add('show-all-details');
    doc.querySelectorAll('details').forEach(function (element) { if (element.closest('.proof-reader') || element.closest('.proof-index') || element.hasAttribute('data-reader-disclosure')) { printState.disclosures.push([element, element.hasAttribute('open')]); element.setAttribute('open', ''); } });
  });
  window.addEventListener('afterprint', function () {
    if (!printState) return;
    printState.disclosures.forEach(function (entry) { if (entry[1]) entry[0].setAttribute('open', ''); else entry[0].removeAttribute('open'); });
    root.classList.toggle('show-all-details', printState.classState); if (showAll) showAll.checked = printState.showAll;
    current = printState.key; currentTarget = printState.target; activator = printState.activator; printState = null;
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
  function openArticleFragment() {
    if (typeof location === 'undefined' || !location.hash) return;
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    var linked = doc.getElementById(id);
    var target = linked && (byNode.get(linked.getAttribute('data-proof-index-item')) || byEdge.get(linked.getAttribute('data-proof-index-use')) || targets.find(function (entry) { return entry.articleId === linked.id; }));
    if (target) select(target.key, { preserveHash: true, nodeId: target.nodeId, edgeId: target.edgeId });
  }
  // Native hash handlers run first; restore article selection before their
  // queued focus observer runs, without replacing the public article address.
  window.addEventListener('hashchange', openArticleFragment);
  openArticleFragment();
  syncViewer();
}
