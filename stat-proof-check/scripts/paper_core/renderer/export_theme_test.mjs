// Executes the adapted serializer with minimal DOM/CSSOM stubs. The evaluator
// covers custom-property cascade for root/descendant selectors and light media,
// not browser layout, rasterization, or general CSS conformance.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { adaptScientificReaderTemplate, SCIENTIFIC_READER_CSS } from './scientific_reader.mjs';
import { scanHtml } from './html_scan.mjs';

const adapted = adaptScientificReaderTemplate(readFileSync(new URL('./assets/archify/template.html', import.meta.url), 'utf8'));
const start = adapted.indexOf('function serializeSvg(scale, opts) {');
const end = adapted.indexOf('\n      function download(', start);
assert(start >= 0 && end > start, 'The emitted export serializer must be located.');
const serializer = adapted.slice(start, end);
const tokens = ['--state-red', '--state-orange', '--state-yellow'];
const expected = { dark: ['#f87171', '#fb923c', '#fde047'], light: ['#b91c1c', '#9a3412', '#854d0e'] };

// Keep actual custom-property declarations and selectors from the stylesheets.
// Only the serializer's light media branch is relevant in the exported SVG.
function rules(css, media = '') {
  const output = [];
  css = css.replace(/\/\*[\s\S]*?\*\//g, '');
  for (let cursor = 0; cursor < css.length;) {
    const open = css.indexOf('{', cursor);
    if (open < 0) break;
    let close = open + 1, depth = 1;
    while (depth && close < css.length) {
      if (css[close] === '{') depth++;
      if (css[close] === '}') depth--;
      close++;
    }
    assert.equal(depth, 0, 'CSS block boundaries must be complete.');
    const selector = css.slice(cursor, open).trim(), body = css.slice(open + 1, close - 1);
    if (selector.startsWith('@media')) {
      if (selector === '@media (prefers-color-scheme: light)') output.push(...rules(body, 'light'));
    } else if (!selector.startsWith('@')) {
      const declarations = [...body.matchAll(/(--[\w-]+)\s*:\s*([^;{}]*)(?:;|$)/g)].map(([, name, value]) => [name, value.trim()]);
      if (declarations.length) output.push({ selectorText: selector, declarations, media,
        type: 1, cssText: `${selector} { ${declarations.map(([name, value]) => `${name}: ${value};`).join(' ')} }` });
    }
    cursor = close;
  }
  return output;
}
const sourceRules = rules(scanHtml(adapted).elements.filter(element => element.tag === 'style').map(element => element.text).join('\n') + '\n' + SCIENTIFIC_READER_CSS);

function element(tag, attrs = {}, parent = null) {
  return { tag, attrs: { ...attrs }, parent, style: {}, children: [],
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return this.attrs[name] ?? null; },
    removeAttribute(name) { delete this.attrs[name]; },
    insertBefore(child) { this.children.push(child); },
  };
}

function matches(node, selector) {
  selector = selector.trim();
  const parts = selector.split(/\s+/);
  if (parts.length > 1) {
    if (!matches(node, parts.pop())) return false;
    for (let parent = node.parent; parent; parent = parent.parent) if (matches(parent, parts.join(' '))) return true;
    return false;
  }
  let rejected = false;
  selector = selector.replace(/:not\(([^()]*)\)/g, (_, excluded) => { rejected ||= matches(node, excluded); return ''; });
  if (rejected) return false;
  if (selector.includes(':root')) {
    if (node.parent) return false;
    selector = selector.replaceAll(':root', '');
  }
  selector = selector.replace(/\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]/g, (_, name, value) => {
    rejected ||= value === undefined ? node.getAttribute(name) === null : node.getAttribute(name) !== value;
    return '';
  });
  selector = selector.replace(/\.([\w-]+)/g, (_, name) => { rejected ||= !(node.attrs.class || '').split(/\s+/).includes(name); return ''; });
  return !rejected && (!selector || selector === '*' || selector === node.tag);
}
function specificity(selector) {
  // :not contributes its argument's specificity, without an extra pseudo-class.
  selector = selector.replace(/:not\(([^()]*)\)/g, '$1');
  const classes = (selector.match(/\.[\w-]+|\[[^\]]+\]|:root/g) || []).length;
  const types = selector.replace(/\.[\w-]+|\[[^\]]+\]|:root/g, '').trim().split(/\s+/).filter(part => /^[a-z]+$/i.test(part)).length;
  return classes * 100 + types;
}
function cascade(node, stylesheet, preference) {
  const values = node.parent ? cascade(node.parent, stylesheet, preference) : {};
  const winners = {};
  for (const rule of stylesheet) {
    if (rule.media && rule.media !== preference) continue;
    for (const selector of rule.selectorText.split(',')) {
      if (!matches(node, selector)) continue;
      const weight = specificity(selector);
      for (const [name, value] of rule.declarations) if (!winners[name] || weight >= winners[name].weight) winners[name] = { weight, value };
    }
  }
  for (const [name, winner] of Object.entries(winners)) values[name] = winner.value;
  return values;
}

function exported(viewerTheme, opts, code = serializer) {
  const root = element('html', { 'data-theme': viewerTheme, 'data-preset': 'classic' });
  const body = element('body', {}, root);
  const svg = element('svg', { class: 'proof-svg proof-audit' }, body);
  svg.viewBox = { baseVal: { x: 0, y: 0, width: 200, height: 100 } };
  let clone;
  svg.cloneNode = () => (clone = element('svg', svg.attrs));
  body.appendChild = probe => { probe.parent = body; };
  body.removeChild = probe => { probe.parent = null; };
  const document = {
    documentElement: root, body,
    styleSheets: [{ cssRules: sourceRules.filter(rule => !rule.media) }],
    querySelector: selector => { assert.equal(selector, '.diagram-container svg'); return svg; },
    createElement: tag => element(tag),
    createElementNS: (_, tag) => element(tag),
    getElementById: id => { assert.equal(id, 'archify-fonts'); return { textContent: '' }; },
  };
  const context = vm.createContext({ document, cleanExportClone: () => true,
    getComputedStyle: node => ({ getPropertyValue: name => cascade(node, sourceRules, viewerTheme)[name] || '' }),
    XMLSerializer: class { serializeToString() { return '<svg/>'; } },
  });
  const result = vm.runInContext(`(${code})`, context)(2, opts);
  assert.equal(result.width, 400);
  assert.equal(result.height, 200);
  assert(result.svgString.startsWith('<?xml'));
  const style = clone.children.find(child => child.tag === 'style');
  assert(style, 'The actual serializer must insert its export stylesheet.');
  return { clone, stylesheet: rules(style.textContent) };
}

for (const viewerTheme of ['dark', 'light']) {
  for (const preference of ['dark', 'light']) test(`auto SVG from ${viewerTheme} viewer uses ${preference} semantic colors`, () => {
    const { clone, stylesheet } = exported(viewerTheme, { theme: 'auto' });
    assert.equal(clone.getAttribute('data-theme'), null);
    const actual = cascade(clone, stylesheet, preference);
    assert.deepEqual(tokens.map(token => actual[token]), expected[preference]);
  });
  test(`default raster SVG locks the ${viewerTheme} viewer theme`, () => {
    const { clone, stylesheet } = exported(viewerTheme, { figure: true });
    assert.equal(clone.getAttribute('data-theme'), viewerTheme);
    const opposite = viewerTheme === 'dark' ? 'light' : 'dark';
    const actual = cascade(clone, stylesheet, opposite);
    assert.deepEqual(tokens.map(token => actual[token]), expected[viewerTheme]);
  });
  const requested = viewerTheme === 'dark' ? 'light' : 'dark';
  test(`explicit ${requested} SVG overrides the ${viewerTheme} viewer theme`, () => {
    const { clone, stylesheet } = exported(viewerTheme, { theme: requested });
    assert.equal(clone.getAttribute('data-theme'), requested);
    const actual = cascade(clone, stylesheet, viewerTheme);
    assert.deepEqual(tokens.map(token => actual[token]), expected[requested]);
  });
}

test('old export selector demonstrably loses the audit orange/yellow cascade', () => {
  const old = serializer.replaceAll(':root, svg.proof-svg { ', ':root, svg { ');
  assert.notEqual(old, serializer);
  const { clone, stylesheet } = exported('light', { theme: 'auto' }, old);
  const actual = cascade(clone, stylesheet, 'dark');
  assert.deepEqual(tokens.slice(1).map(token => actual[token]), expected.light.slice(1), 'svg.proof-audit outranks the old export selector.');
  assert.notDeepEqual(tokens.map(token => actual[token]), expected.dark, 'The regression must be observable as incorrect colors.');
});
