// Frozen evidence presentation only: no assessment regeneration or browser claim.
import assert from 'node:assert/strict';
import test from 'node:test';
import { renderProjection, representationReceipt } from './render_projection.mjs';
import { scanHtml, textOf, descendants } from './html_scan.mjs';
import { readerFixture } from './selftest.mjs';

const key = ref => `${ref.collection}:${ref.id}:${ref.version}`;
const render = input => renderProjection(Buffer.from(JSON.stringify(input)));

test('nonprimary completion follows one exact saved task while scientific judgments remain frozen', () => {
  const cases = [
    ['independent gap','independent',{state:'satisfied',freshness:'current',outcome:'gap'},'Independent examination completed.'],
    ['independent refutation','independent',{state:'satisfied',freshness:'current',outcome:'refuted'},'Independent examination completed.'],
    ['settled comparison','coordinator',{state:'satisfied',freshness:'current',outcome:'supported'},'Comparison completed.'],
    ['pending comparison','coordinator',{state:'waiting',freshness:null,outcome:'supported'},'Comparison incomplete for the current material.'],
    ['unresolved comparison','coordinator',{state:'satisfied',freshness:'current',outcome:'inconclusive'},'Comparison completed.'],
    ['missing','independent',{state:'waiting',freshness:'missing',outcome:null},'incomplete for the current material'],
    ['stale','independent',{state:'satisfied',freshness:'stale',outcome:'supported'},'incomplete for the current material'],
    ['partial','independent',{state:'ready',freshness:'partial',outcome:'inconclusive'},'incomplete for the current material'],
    ['compromised','independent',{state:'ready',freshness:'current',requires_independent_context:true},'compromised independence'],
    ['legacy','independent',null,'Completion status unavailable.'],
    ['legacy satisfied','independent',{state:'satisfied',outcome:'gap'},'Completion status unavailable.'],
    ['duplicate','independent',{state:'satisfied',freshness:'current'},'Completion status unavailable.'],
    ['wrong target','independent',{state:'satisfied',freshness:'current'},'Completion status unavailable.'],
    ['wrong kind','independent',{state:'satisfied',freshness:'current'},'Completion status unavailable.'],
    ['wrong role','independent',{state:'satisfied',freshness:'current'},'Completion status unavailable.'],
  ];
  for (const [name,role,facts,expected] of cases) {
    const input = readerFixture(), projection = input.projection;
    const obligation = projection.obligations.find(row => row.role === 'independent');
    obligation.role = role;
    if (facts) {
      const task = {id:obligation.id,target:obligation.target,kind:obligation.kind,role,required:true,
        label:'Saved requirement',next_action:'SCHEDULER TEXT MUST NOT BECOME SCIENTIFIC REASONING',location:null,...facts};
      if (name === 'wrong target') task.target = {collection:'items',id:'different_target'};
      if (name === 'wrong kind') task.kind = 'source_fidelity';
      if (name === 'wrong role') task.role = 'primary';
      projection.worklist = {revision:projection.snapshot_revision,analysis_complete:false,
        tasks:name === 'duplicate' ? [task,structuredClone(task)] : [task],coordinator_actions:[]};
    }
    const before = JSON.stringify(projection), rendered = render(input), scan = scanHtml(rendered.html);
    const wrappers = scan.elements.filter(row => row.attrs['data-obligation-id'] === obligation.id);
    assert(wrappers.length,name);
    for (const wrapper of wrappers) {
      const text = textOf(scan,wrapper);
      assert(text.includes(expected),name + ': ' + text);
      assert(!text.includes('Independent review: not required'),name);
      assert(!text.includes('SCHEDULER TEXT'),name);
      if (role === 'coordinator') assert(!text.includes('Saved outcome:'),name + ': comparison status is not a scientific opinion');
      else if (facts?.outcome) assert(text.includes(`Saved outcome: ${facts.outcome}.`),name + ': retain the independent opinion');
      assert(![...descendants(wrapper)].some(row => row.attrs.class?.split(' ').includes('proof-assessment')),name);
      for (const ref of obligation.check_refs) assert([...descendants(wrapper)].some(row => row.attrs['data-jump-record'] === key(ref)),name);
    }
    assert.equal(JSON.stringify(projection),before,name + ': immutable scientific payload');
    assert.equal(rendered.receipt.representation.status,'pass',name);
    const work = [...descendants(wrappers[0])].find(row => row.attrs['data-role-work']);
    const altered = rendered.html.slice(0,work.openEnd) + '<p>Everything agreed.</p>' + rendered.html.slice(work.closeStart);
    assert.equal(representationReceipt(rendered.model,scanHtml(altered)).status,'fail',name + ': changed role status');
  }
});

function applicationFixture() {
  const input = readerFixture(), projection = input.projection;
  const node = projection.nodes.find(row => row.kind === 'theorem');
  const otherNode = projection.nodes.find(row => row.kind === 'definition');
  const own = projection.details[node.detail_key], other = projection.details[otherNode.detail_key];
  const application = own.reader.applications[0], oldUse = structuredClone(application.use_ref);
  const useRecord = projection.records.find(row => key(row.ref) === key(oldUse));
  const currentUse = {...oldUse,version:2};
  projection.records.push({ref:currentUse,body:structuredClone(useRecord.body)});
  application.use_ref = currentUse;
  own.record_refs.push(currentUse); own.sections[0].record_refs.push(currentUse);
  projection.record_locations.push({ref:currentUse,detail_key:node.detail_key,section_key:own.sections[0].key});
  const refs = [currentUse,application.application_ref];
  for (const ref of [...refs,oldUse]) {
    other.record_refs.push(ref); other.sections[0].record_refs.push(ref);
    Object.assign(projection.record_locations.find(row => key(row.ref) === key(ref)),
      {detail_key:otherNode.detail_key,section_key:other.sections[0].key});
  }
  return {input,projection,node,otherNode,own,other,application,oldUse,refs};
}

test('applications resolve independent version pins to the exact consuming occurrence in graph and index modes', () => {
  const changes = [
    ['exact consumer',() => {}],
    ['two owners',f => { f.other.reader = structuredClone(f.own.reader); f.other.reader.item_ref = f.otherNode.item_ref; }],
    ['missing application occurrence',f => { for (const section of f.own.sections) section.record_refs = section.record_refs.filter(ref => key(ref) !== key(f.refs[1])); }],
    ['folded intermediate',f => { f.application.to_ref = f.own.reader.arguments.find(row => row.relation === 'subsidiary').target_ref; }],
    ['historical reader',f => { f.own.reader.item_ref = {...f.node.item_ref,version:1}; }],
    ['already owned section',f => {
      f.own.sections.push({key:'custom_application',title:'Application',kind:'applications',record_refs:f.refs,obligation_ids:[]});
      for (const ref of f.refs) Object.assign(f.projection.record_locations.find(row => key(row.ref) === key(ref)),{detail_key:f.node.detail_key,section_key:'custom_application'});
    }],
    ['represented part',f => {
      const part = {collection:'parts',id:'part_consumer',version:1};
      f.projection.records.push({ref:part,body:{label:'Claim part',statement:{form:'text',text:'The represented part.'}}});
      f.own.record_refs.push(part); f.own.sections[0].record_refs.push(part);
      f.projection.record_locations.push({ref:part,detail_key:f.node.detail_key,section_key:f.own.sections[0].key});
      f.own.reader.targets.push({...f.own.reader.targets[0],target_ref:part,statement_ref:part}); f.application.to_ref = part;
    }],
  ];
  for (const mode of ['dag','index']) for (const [name,change] of changes) {
    const f = applicationFixture(); f.projection.layout.mode = mode; change(f);
    const before = JSON.stringify(f.projection), rendered = render(f.input), scan = scanHtml(rendered.html);
    const entries = JSON.parse(scan.elements.find(row => row.attrs.id === 'proof-reader-search').text);
    for (const ref of f.refs) {
      const saved = f.projection.record_locations.find(row => key(row.ref) === key(ref));
      const entry = entries.find(row => row.key === key(ref));
      const relocates = ['exact consumer','represented part'].includes(name) || name === 'missing application occurrence' && ref.collection === 'uses';
      const detail = relocates ? f.node.detail_key : saved.detail_key;
      const section = relocates ? f.own.sections.find(row => row.record_refs.some(value => key(value) === key(ref))).key : saved.section_key;
      assert.equal(entry.detail,detail,name); assert.equal(entry.section,section,name);
      const links = scan.elements.filter(row => row.tag === 'a' && row.attrs['data-jump-record'] === key(ref));
      if (name !== 'historical reader') assert(links.length,name);
      for (const link of links) { assert.equal(link.attrs['data-jump-detail'],detail,name); assert.equal(link.attrs['data-jump-section'],section,name); }
      const owner = scan.elements.find(row => row.attrs['data-proof-detail'] === detail);
      assert([...descendants(owner)].some(row => row.attrs['data-record-ref'] === key(ref)),name + ': focused record actually occurs');
    }
    assert.equal(entries.find(row => row.key === key(f.oldUse)).detail,f.otherNode.detail_key,name + ': old version stays saved');
    assert.equal(JSON.stringify(f.projection),before,name + ': immutable scientific payload');
  }
});
