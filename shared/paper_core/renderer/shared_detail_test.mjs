// Shared details retain each owner's assessment and contextual reader identity.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {renderProjection, representationReceipt} from './render_projection.mjs';
import {readerFixture} from './selftest.mjs';
import {scanHtml, descendants, textOf} from './html_scan.mjs';

export function sharedOwnerCases() {
  const cases = [];
  const render = (name, input) => {
    // The small historical fixture uses bare item IDs; the Python publication
    // path consumes the current structured endpoint references.
    for (const record of input.projection.records) if (record.ref.collection === 'uses') {
      for (const field of ['from', 'to']) if (typeof record.body[field] === 'string')
        record.body[field] = {collection:'items', id:record.body[field]};
    }
    const saved = JSON.stringify(input.projection);
    const rendered = renderProjection(Buffer.from(JSON.stringify(input)));
    assert.equal(rendered.receipt.representation.status, 'pass');
    assert.equal(JSON.stringify(input.projection), saved);
    assert.deepEqual(JSON.parse(scanHtml(rendered.html).elements.find(e => e.attrs.id === 'proof-projection').text), input.projection);
    cases.push({name, html:rendered.html, projection:input.projection, build:input.build, valid:true});
    return rendered;
  };
  const corrupt = (name, rendered, input, html, diagnostic) => {
    const receipt = representationReceipt(rendered.model, scanHtml(html));
    assert.equal(receipt.status, 'fail');
    assert(receipt.diagnostics.some(message => message.includes(diagnostic)), JSON.stringify(receipt));
    cases.push({name, html, projection:input.projection, build:input.build, valid:false});
  };
  const input = JSON.parse(readFileSync(new URL('fixtures/dag_small.json', import.meta.url), 'utf8'));
  const key = input.projection.nodes[0].detail_key;
  input.projection.nodes[1].detail_key = key;
  input.projection.connections[0].detail_key = key;
  input.projection.connections[1].detail_key = key;
  for (const [i, owner] of [input.projection.nodes[0], input.projection.nodes[1], input.projection.connections[0], input.projection.connections[1]].entries()) {
    owner.assessment = {...owner.assessment, label:`Owner ${i} assessment`, explanation:`Saved conclusion for owner ${i}.`};
  }
  const rendered = render('distinct-node-connection-owners', input);
  const scan = scanHtml(rendered.html);
  for (const [kind, owner] of [['node', input.projection.nodes[1]], ['connection', input.projection.connections[1]]]) {
    const header = scan.elements.find(e => e.attrs[`data-proof-owner-${kind}`] === owner.id);
    const label = [...descendants(header)].find(e => (e.attrs.class || '').split(' ').includes('proof-assessment-label'));
    assert.equal(textOf(scan, label), owner.assessment.label);
    const changed = rendered.html.slice(0, label.openEnd) + 'Borrowed assessment' + rendered.html.slice(label.closeStart);
    corrupt(`tampered-${kind}-assessment`, rendered, input, changed, 'visible assessment');
    const duplicate = rendered.html.slice(0, header.closeEnd) + rendered.html.slice(header.start, header.closeEnd) + rendered.html.slice(header.closeEnd);
    corrupt(`duplicated-${kind}-owner`, rendered, input, duplicate, 'visible assessment');
  }
  const readerInput = readerFixture();
  const theorem = readerInput.projection.nodes.find(n => n.kind === 'theorem');
  const assumption = readerInput.projection.nodes.find(n => n.kind === 'assumption');
  assumption.detail_key = theorem.detail_key;
  const readerRendered = render('reader-only-for-matching-owner', readerInput);
  const readerScan = scanHtml(readerRendered.html);
  const assumptionHeader = readerScan.elements.find(e => e.attrs['data-proof-owner-node'] === assumption.id);
  assert(![...descendants(assumptionHeader)].some(e => e.attrs['data-reader-target-ref']));
  assert([...descendants(assumptionHeader)].some(e => e.attrs['data-reader-context'] === 'legacy'));
  const overview = readerScan.elements.find(e => (e.attrs.class || '').split(' ').includes('proof-reader-overview'));
  assert.equal(overview.parent.attrs['data-proof-owner-node'], theorem.id);
  // Move the complete contextual overview under the assumption without changing its contents.
  const block = readerRendered.html.slice(overview.start, overview.closeEnd);
  const moved = readerRendered.html.slice(0, assumptionHeader.closeStart) + block
    + readerRendered.html.slice(assumptionHeader.closeStart, overview.start) + readerRendered.html.slice(overview.closeEnd);
  corrupt('reader-moved-to-unmatched-owner', readerRendered, readerInput, moved, 'contextual dependencies');
  return cases;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const cases = sharedOwnerCases();
  console.log(JSON.stringify(process.argv.includes('--json') ? cases : {ok:true, checks:cases.map(({name,valid}) => ({name,valid}))}));
}
