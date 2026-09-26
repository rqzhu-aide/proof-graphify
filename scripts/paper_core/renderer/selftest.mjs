// Renderer self-test: vendored-file hashes, fixture renders, and explicit cycle modes.
//
// Usage: node selftest.mjs            (exit 0 when every check passes, 1 otherwise)
// Prints one JSON object with the individual check results.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync, rmSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderProjection, representationReceipt } from './render_projection.mjs';
import { scanHtml, textOf } from './html_scan.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RENDERER = path.join(HERE, 'render_projection.mjs');
const NOTICES = path.join(HERE, 'THIRD_PARTY_NOTICES.md');
const FIXTURES = path.join(HERE, 'fixtures');
const PASSING = ['dag_small.json', 'index_fallback.json', 'long_math.json'];
const FAILING = [{ file: 'cycle_dag.json', stage: 'layout' }];

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function noticeTable() {
  const rows = [];
  for (const line of readFileSync(NOTICES, 'utf8').split(/\r?\n/)) {
    const match = /^\|\s*`([^`]+)`\s*\|[^|]*\|[^|]*\|\s*`([0-9a-f]{64})`\s*\|/.exec(line);
    if (match) rows.push({ file: match[1], sha256: match[2] });
  }
  return rows;
}

function checkHashes(results) {
  const rows = noticeTable();
  if (rows.length === 0) results.push({ check: 'notices', ok: false, error: 'no hash rows found in THIRD_PARTY_NOTICES.md' });
  for (const row of rows) {
    const target = path.join(HERE, ...row.file.split('/'));
    if (!existsSync(target)) {
      results.push({ check: `hash:${row.file}`, ok: false, error: 'vendored file missing' });
      continue;
    }
    const actual = sha256(readFileSync(target));
    results.push({ check: `hash:${row.file}`, ok: actual === row.sha256, expected: row.sha256, actual });
  }
}

function runRenderer(input, output) {
  const run = spawnSync(process.execPath, [RENDERER, input, output], { encoding: 'utf8' });
  let stdout = null;
  let stderr = null;
  try { stdout = run.stdout.trim() ? JSON.parse(run.stdout) : null; } catch { stdout = { unparsable: run.stdout }; }
  try { stderr = run.stderr.trim() ? JSON.parse(run.stderr) : null; } catch { stderr = { unparsable: run.stderr }; }
  return { status: run.status, stdout, stderr };
}

// A compact reader fixture exercises pinned text and context; it makes no
// claim that a browser has rendered or visually inspected the page.
export function readerFixture() {
  const input = JSON.parse(readFileSync(path.join(FIXTURES, 'dag_small.json'), 'utf8'));
  const projection = input.projection, node = projection.nodes.find(row => row.kind === 'theorem');
  const detail = projection.details[node.detail_key], old = projection.records.find(row => row.ref.id === node.item_ref.id);
  const put = (collection, id, body, version = 1) => {
    const record = {ref:{collection,id,version},body}; projection.records.push(record);
    detail.record_refs.push(record.ref); detail.sections[0].record_refs.push(record.ref);
    projection.record_locations.push({ref:record.ref,detail_key:node.detail_key,section_key:detail.sections[0].key});
    return record.ref;
  };
  const current = put('items', old.ref.id, {...old.body, statement:{form:'text',text:'Current synopsis differs from the pinned claim.'}, proof_idea:'Reduce by the supplier criterion, then verify the final restriction.'}, 2);
  node.item_ref = current;
  const supplier = projection.nodes.find(row => row.kind === 'assumption').item_ref;
  const definition = projection.nodes.find(row => row.kind === 'definition').item_ref;
  const scope = put('scopes','scp_reader',{argument_id:null,parent_id:null,assumptions:[supplier,definition].map(ref => ({collection:ref.collection,id:ref.id})),binders:[{symbol:'x',domain:'positive reals',quantifier:'forall'}],conditions:['x > 0'],evidence_refs:[]});
  const spec = put('target_specs','tgt_reader',{target:{collection:current.collection,id:current.id},statement_ref:old.ref,statement:null,scope_id:scope.id,evidence_refs:[],state:'registered',fidelity_ref:null});
  const argument = put('arguments','arg_reader',{target:{collection:current.collection,id:current.id},label:'Written argument',origin:'source',lifecycle:'registered',scope_id:scope.id,final_group_id:'grp_reader',evidence_refs:[]});
  const group = put('groups','grp_reader',{argument_id:argument.id,conclusion:{collection:current.collection,id:current.id},kind:'cases',scope_id:scope.id,case_scope_ids:[scope.id],discharges:[scope.id],rationale:'Apply the criterion in the recorded case.',evidence_refs:[]});
  const use = put('uses','use_reader',{from:{collection:supplier.collection,id:supplier.id},to:{collection:current.collection,id:current.id},type:'dependency',reason:'Supplies the criterion used at the final inference.',regime:'Only for x > 0.',uncertainty:'The boundary case is unexamined.',evidence_refs:[]});
  const application = put('application_details','app_reader',{use_id:use.id,group_id:group.id,needed_form:{form:'text',text:'Criterion at positive x.'},scope_id:scope.id,state:'registered',substitutions:[]});
  const finding = put('findings','fnd_reader',{target:{collection:'groups',id:group.id},category:'inconclusive',lifecycle:'open',description:'Boundary case remains unable to verify.',impact_reason:'The conclusion is restricted to positive x.',evidence_refs:[],check_refs:[],affected_uses:[use.id]});
  const localPremise = put('items','itm_reader_application_premise',{kind:'assumption',label:'Application assumption C',statement:{form:'text',text:'Assume the application-specific integrability condition.'},owner_id:null,scope_id:null});
  const local = put('scopes','scp_reader_local',{argument_id:argument.id,parent_id:scope.id,assumptions:[{collection:localPremise.collection,id:localPremise.id}],binders:[{symbol:'y',domain:'strictly positive reals',quantifier:'forall'}],conditions:['x < 1'],evidence_refs:[]});
  const newPremise = put('items','itm_reader_new_premise',{kind:'assumption',label:'Local assumption B',statement:{form:'text',text:'Assume the local sign restriction.'},owner_id:null,scope_id:null});
  const formerlyHidden = put('scopes','scp_reader_hidden',{argument_id:null,parent_id:null,assumptions:[supplier,newPremise].map(ref => ({collection:ref.collection,id:ref.id})),binders:[],conditions:['y < 0'],evidence_refs:[]});
  const auxiliary = put('items','itm_reader_aux',{kind:'intermediate_result',label:'Subsidiary calculation',statement:{form:'text',text:'Auxiliary target.'},owner_id:current.id,scope_id:formerlyHidden.id});
  const subsidiary = put('arguments','arg_reader_subsidiary',{target:{collection:auxiliary.collection,id:auxiliary.id},label:'Subsidiary argument',origin:'reconstruction',lifecycle:'registered',scope_id:formerlyHidden.id,final_group_id:null,evidence_refs:[]});
  const chain = [{scope_ref:scope,assumption_refs:[supplier,definition]}];
  const hiddenChain = [{scope_ref:formerlyHidden,assumption_refs:[supplier,newPremise]}];
  detail.reader = {version:1,item_ref:current,strategy_ref:current,
    targets:[{target_ref:current,spec_ref:spec,statement_ref:old.ref,statement_field:'statement',exact_state:'registered',scope_chain:chain,assessment:node.assessment}],
    arguments:[{argument_ref:subsidiary,target_ref:auxiliary,relation:'subsidiary',reaches_target_refs:[],scope_chain:hiddenChain,groups:[]},
      {argument_ref:argument,target_ref:current,relation:'target',reaches_target_refs:[current],scope_chain:[...hiddenChain,...chain],groups:[{group_ref:group,scope_chain:chain,case_scopes:[{scope_ref:scope,scope_chain:chain}],discharged_scope_refs:[scope]}]}],
    applications:[{use_ref:use,application_ref:application,from_ref:supplier,to_ref:current,argument_ref:argument,group_ref:group,scope_chain:[{scope_ref:local,assumption_refs:[localPremise]},...chain],relation:'target',reaches_target_refs:[current],assessment:node.assessment,refinement_refs:[],refined_use_refs:[],summary_use_refs:[]}],
    provenance_groups:[],finding_refs:[finding],source_limit_refs:[]};
  input.display ||= {}; input.display.refs ||= {};
  input.display.refs[`${current.collection}:${current.id}:${current.version}`] = {proof_idea_html:'Reduce by the supplier criterion, then verify the final restriction.'};
  return input;
}

function checkReader(results) {
  const input = readerFixture(), rendered = renderProjection(Buffer.from(JSON.stringify(input)));
  const scan = scanHtml(rendered.html), overview = scan.elements.find(row => row.attrs['data-reader-overview'] && row.attrs.class === 'proof-reader-overview');
  const overviewText = textOf(scan, overview), problems = [];
  for (const text of ['Exact audited statement','Main proof strategy','Dependencies and their roles','Boundary case remains unable to verify.','Only for x > 0.','cases inference'])
    if (!overviewText.includes(text)) problems.push(`missing ${text}`);
  const fields = scan.elements.filter(row => row.attrs['data-reader-detail'] === overview.attrs['data-reader-overview'] && row.attrs['data-reader-field']);
  if (!fields.some(row => row.attrs['data-reader-context'] === 'target:0' && row.attrs['data-reader-field'] === 'statement.text' && row.attrs['data-reader-ref'].endsWith(':1')))
    problems.push('the opening statement lost its historical pin');
  const strategy = fields.find(row => row.attrs['data-reader-field'] === 'proof_idea');
  const enclosedBy = (element, attribute) => { for (let parent = element.parent; parent; parent = parent.parent) if (Object.hasOwn(parent.attrs,attribute)) return true; return false; };
  const repeated = fields.find(row => row.attrs['data-reader-context'] === 'application:0:scope:1' && row.attrs['data-reader-field'] === 'conditions.0');
  const novel = fields.find(row => row.attrs['data-reader-context'] === 'application:0:scope:0' && row.attrs['data-reader-field'] === 'conditions.0');
  const previouslyHidden = fields.find(row => row.attrs['data-reader-context'] === 'argument:1:scope:0' && row.attrs['data-reader-field'] === 'conditions.0');
  if (!repeated || !enclosedBy(repeated,'data-reader-repeated-scope')) problems.push('identical setup repeated after its visible occurrence did not fold');
  if (!novel || enclosedBy(novel,'data-reader-repeated-scope')) problems.push('an additional local condition was folded');
  if (!previouslyHidden || enclosedBy(previouslyHidden,'data-reader-repeated-scope')) problems.push('a collapsed subsidiary context incorrectly seeded visible setup');
  const premiseField = (context,field) => fields.find(row => row.attrs['data-reader-context'] === context && row.attrs['data-reader-field'] === field);
  const initiallyDisclosed = element => { for (let parent = element?.parent; parent; parent = parent.parent) if (parent.tag === 'details' && !Object.hasOwn(parent.attrs,'open')) return false; return Boolean(element); };
  for (const [context,field] of [['application:0:scope:0:assumption:0','label'],['application:0:scope:0:assumption:0','statement.text'],['application:0:scope:0','binders.0.domain'],['application:0:scope:0','binders.0.quantifier']])
    if (!initiallyDisclosed(premiseField(context,field))) problems.push(`application-only restriction was initially hidden: ${context} ${field}`);
  const definitionText = premiseField('target:0:scope:0:assumption:1','statement.text');
  const definitionLabel = premiseField('target:0:scope:0:assumption:1','label');
  if (!definitionText || !enclosedBy(definitionText,'data-reader-definition') || enclosedBy(definitionLabel,'data-reader-definition')) problems.push('definition disclosure must preserve its visible named label');
  const initialAssumption = premiseField('target:0:scope:0:assumption:0','statement.text');
  const repeatedAssumption = premiseField('argument:1:scope:0:assumption:0','statement.text');
  const hiddenAssumption = premiseField('argument:1:scope:0:assumption:1','statement.text');
  if (enclosedBy(initialAssumption,'data-reader-repeated-premise') || !enclosedBy(repeatedAssumption,'data-reader-repeated-premise')) problems.push('only the repeated pinned assumption should fold across scopes');
  if (enclosedBy(hiddenAssumption,'data-reader-repeated-premise')) problems.push('a collapsed context incorrectly seeded a premise');
  const changed = rendered.html.slice(0,strategy.openEnd) + 'Changed strategy.' + rendered.html.slice(strategy.closeStart);
  if (representationReceipt(rendered.model,scanHtml(changed)).status !== 'fail') problems.push('altered opening strategy passed representation acceptance');
  const removed = rendered.html.slice(0,strategy.start) + rendered.html.slice(strategy.closeEnd);
  if (representationReceipt(rendered.model,scanHtml(removed)).status !== 'fail') problems.push('hidden template strategy masked missing overview strategy');
  results.push({check:'reader:pinned-context-and-tampering',ok:!problems.length,problems});
  const node = input.projection.nodes.find(row => row.kind === 'theorem');
  delete input.projection.records.find(row => row.ref.id === node.item_ref.id && row.ref.version === 2).body.proof_idea;
  delete input.display.refs[`${node.item_ref.collection}:${node.item_ref.id}:${node.item_ref.version}`];
  node.assessment.label = 'stale'; node.assessment.explanation = 'stale';
  const missing = renderProjection(Buffer.from(JSON.stringify(input))).html;
  results.push({check:'reader:missing-strategy',ok:missing.includes('Proof-strategy summary not recorded.') && (missing.match(/proof-muted proof-stale-hint/g) || []).length === 1 && missing.includes('This status summary does not identify which change made the work stale.')});
}

function checkFixtures(results, workdir) {
  for (const name of PASSING) {
    const output = path.join(workdir, name.replace(/\.json$/, '.html'));
    const run = runRenderer(path.join(FIXTURES, name), output);
    const receipt = run.stdout || {};
    const problems = [];
    if (run.status !== 0) problems.push(`exit ${run.status}: ${JSON.stringify(run.stderr)}`);
    if (!receipt.representation || receipt.representation.status !== 'pass') problems.push('representation check did not pass');
    if (!receipt.geometry || receipt.geometry.status === 'fail') problems.push('geometry check failed');
    if (run.status === 0) {
      const actual = sha256(readFileSync(output));
      if (actual !== receipt.artifact_sha256) problems.push('artifact hash does not match the written file');
    }
    results.push({ check: `render:${name}`, ok: problems.length === 0, problems, layout_mode: receipt.layout_mode,
      nodes: receipt.nodes, connections: receipt.connections });
  }
  for (const entry of FAILING) {
    const output = path.join(workdir, entry.file.replace(/\.json$/, '.html'));
    const run = runRenderer(path.join(FIXTURES, entry.file), output);
    const problems = [];
    if (run.status !== 1) problems.push(`expected exit 1, got ${run.status}`);
    if (!run.stderr || run.stderr.stage !== entry.stage) problems.push(`expected failure stage ${entry.stage}, got ${JSON.stringify(run.stderr && run.stderr.stage)}`);
    if (existsSync(output)) problems.push('a failed render left an output file behind');
    results.push({ check: `fail:${entry.file}`, ok: problems.length === 0, problems });
  }
  // The same cyclic dataset is drawable when it declares its actual layout
  // mode. The dag declaration above must still fail, rather than change mode.
  const cyclic = JSON.parse(readFileSync(path.join(FIXTURES, 'cycle_dag.json'), 'utf8'));
  cyclic.title = 'Cycle sample with every recorded direction';
  cyclic.projection.layout = { mode: 'cyclic', reasons: ['Every recorded arrow is retained.'] };
  const source = path.join(workdir, 'cyclic.json'), output = path.join(workdir, 'cyclic.html');
  writeFileSync(source, JSON.stringify(cyclic));
  const run = runRenderer(source, output), receipt = run.stdout || {};
  const problems = [];
  if (run.status !== 0) problems.push(`exit ${run.status}: ${JSON.stringify(run.stderr)}`);
  if (receipt.representation?.status !== 'pass') problems.push('representation check did not pass');
  if (receipt.geometry?.status !== 'pass') problems.push('geometry check did not pass');
  if (receipt.nodes !== cyclic.projection.nodes.length || receipt.connections !== cyclic.projection.connections.length)
    problems.push('cycle rendering changed the graph counts');
  results.push({ check: 'render:cyclic', ok: problems.length === 0, problems, layout_mode: receipt.layout_mode,
    nodes: receipt.nodes, connections: receipt.connections });
  // Dense return edges exercise distinct rails, both directions between each
  // pair, and routes that pass other ranks and rows without crossing boxes.
  const template = cyclic.projection.connections[0];
  cyclic.projection.connections = cyclic.projection.nodes.flatMap((from) => cyclic.projection.nodes
    .filter((to) => to.id !== from.id).map((to) => ({ ...template, id: `dense_${from.id}_${to.id}`, from: from.id, to: to.id })));
  writeFileSync(source, JSON.stringify(cyclic));
  const denseRun = runRenderer(source, output), denseReceipt = denseRun.stdout || {};
  results.push({ check: 'render:cyclic-dense', ok: denseRun.status === 0 && denseReceipt.geometry?.status === 'pass'
    && denseReceipt.representation?.status === 'pass' && denseReceipt.connections === cyclic.projection.connections.length,
  diagnostics: denseRun.stderr, nodes: denseReceipt.nodes, connections: denseReceipt.connections });
}

export function main() {
  const results = [];
  const workdir = mkdtempSync(path.join(tmpdir(), 'paper-core-selftest-'));
  try {
    checkHashes(results);
    checkFixtures(results, workdir);
    checkReader(results);
  } finally {
    rmSync(workdir, { recursive: true, force: true });
  }
  const ok = results.every((r) => r.ok);
  process.stdout.write(JSON.stringify({ ok, checks: results }, null, 1) + '\n');
  return ok ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
