#!/usr/bin/env node
// render_projection.mjs - self-contained HTML renderer for proof-audit projections.
//
//   node render_projection.mjs INPUT.json OUTPUT.html
//
// Writes one self-contained HTML file (inline CSS/JS, embedded fonts, no
// external requests), prints one JSON receipt to stdout and exits 0. On any
// failure it prints a JSON diagnostic to stderr, exits nonzero and leaves no
// output file behind (the page is written next to OUTPUT and renamed only
// after every verification passed). Output is deterministic: identical input
// bytes produce identical HTML bytes.
//
// The palette, box metrics, longest-path layering, orthogonal edge routing and
// badge placement are adapted from proof-graphify/scripts/render.mjs
// (MIT). See THIRD_PARTY_NOTICES.md.

import { readFileSync, writeFileSync, renameSync, unlinkSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { esc, textUnits } from './assets/archify/utils.mjs';
import { scanHtml, textOf, descendants, hasAttr, sameMultiset } from './html_scan.mjs';
import { archifyPage, auditResults } from './archify_adapter.mjs';
import { KINDS, BOX, alignSourcePrerequisites, readerRuntime, readerSearchData, decodeReaderSearchData, viewControls, scientificSearchPanel, readingSection, sourceDisclosure, mathDisplayNotes, SCIENTIFIC_READER_CSS } from './scientific_reader.mjs';
import { createReaderContent } from './reader_content.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TEMPLATE_PATH = path.join(HERE, 'assets', 'archify', 'template.html');

// ---------------------------------------------------------------------------
// Vocabulary
// ---------------------------------------------------------------------------

// [display name, dark-theme tone, light-theme tone] - the archify palette.
export { KINDS, BOX } from './scientific_reader.mjs';
export const STATES = ['green', 'red', 'gray', 'amber'];
const DISPLAY_STATES = ['red', 'orange', 'yellow', 'green', 'gray'];
const STATE_LABELS = { green: 'Checked', red: 'Severe', orange: 'Moderate', yellow: 'Minor', gray: 'Unresolved or unrated' };
const STATE_GLYPHS = { green: '✓', red: '✕', orange: '!', yellow: 'i', gray: '?' };
const DISPLAY = {
  severe: ['red', 'Severe'], moderate: ['orange', 'Moderate'], minor: ['yellow', 'Minor'],
  checked: ['green', 'Checked'], unrated: ['gray', 'Severity not rated'],
  unresolved: ['gray', 'Unable to assess'], unassessed: ['gray', 'Not assessed'],
  dependency: ['gray', 'Depends on unresolved result'], historical: ['gray', 'Saved assessment, not rated'],
};
const reviewDisplay = assessment => {
  const saved = assessment?.review_display;
  const status = saved && Object.hasOwn(DISPLAY, saved.status) ? saved.status : 'historical';
  const [color, label] = DISPLAY[status];
  if (status === 'unassessed' && assessment?.label === 'examined in proof') {
    return {status, color, label:'Examined in proof', explanation:assessment.explanation,
      unrated_count:saved?.unrated_count || 0};
  }
  return {status, color, label, explanation:saved?.explanation || '', unrated_count:saved?.unrated_count || 0};
};
const displayState = assessment => reviewDisplay(assessment).color;
const FINDING_STATUSES = ['severe', 'moderate', 'minor', 'unresolved', 'unrated'];
const REVIEWS = ['not_required', 'pending', 'complete', 'disputed', 'compromised'];
const REVIEW_LABELS = { not_required: 'not required', pending: 'pending', complete: 'complete', disputed: 'disputed', compromised: 'compromised' };
const SECTION_KINDS = ['statement', 'applications', 'derivations', 'premises', 'coverage', 'findings', 'sources', 'review', 'composition', 'limitations'];
const ROLES = ['primary', 'independent', 'coordinator'];
const BUILD_KINDS = ['working', 'release'];
const LAYOUT_MODES = ['dag', 'cyclic', 'index'];
const DISPLAY_KEYS = ['label_html', 'statement_html', 'reason_html', 'needed_form_html', 'rationale_html', 'conditions_html', 'reasoning_html', 'description_html', 'proof_idea_html', 'regime_html', 'uncertainty_html', 'impact_reason_html', 'resolution_html', 'note_html', 'coverage_note_html', 'next_action_html', 'caption_html'];
// Record body field -> display fragment that replaces its raw text.
const FRAGMENT_FIELDS = { label: 'label_html', statement: 'statement_html', reason: 'reason_html', needed_form: 'needed_form_html', rationale: 'rationale_html', conditions: 'conditions_html', reasoning: 'reasoning_html', description: 'description_html', proof_idea: 'proof_idea_html', regime: 'regime_html', uncertainty: 'uncertainty_html', impact_reason: 'impact_reason_html', resolution: 'resolution_html', note: 'note_html', coverage_note: 'coverage_note_html', next_action: 'next_action_html', caption: 'caption_html' };
const PROGRESS_FIELDS = ['required_obligations', 'completed_current_obligations', 'draft_checks', 'major_results', 'source_unbound_items'];

const ID_PATTERN = /^[A-Za-z][A-Za-z0-9_.:-]{0,254}$/;
const COLLECTION_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
const KEY_PATTERN = /^[^\u0000-\u001f\u007f]{1,512}$/u;

// ---------------------------------------------------------------------------
// Errors and small helpers
// ---------------------------------------------------------------------------

export class RenderError extends Error {
  constructor(stage, message, diagnostics = []) {
    super(message);
    this.name = 'RenderError';
    this.stage = stage;
    this.diagnostics = diagnostics;
  }
}

function fail(stage, message, diagnostics = []) {
  throw new RenderError(stage, message, diagnostics);
}

const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isString = (value) => typeof value === 'string';
const isCount = (value) => Number.isInteger(value) && value >= 0;
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const round2 = (value) => Math.round(value * 100) / 100;
const fmt = (value) => String(round2(value));
const refKey = (ref) => `${ref.collection}:${ref.id}:${ref.version}`;
const looseKey = (ref) => `${ref.collection}:${ref.id}`;
const humanize = (key) => String(key).replaceAll('_', ' ');

export function jsonForScript(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
}

// ---------------------------------------------------------------------------
// Input parsing
// ---------------------------------------------------------------------------

// JSON.parse silently keeps the last duplicate key; a projection with two
// different bodies for one key must not be rendered as if it were unambiguous.
function findDuplicateKey(text) {
  const stack = [];
  const length = text.length;
  let i = 0;
  while (i < length) {
    const ch = text[i];
    if (ch === '"') {
      let j = i + 1;
      while (j < length && text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
      const value = JSON.parse(text.slice(i, j + 1));
      const top = stack[stack.length - 1];
      if (top && top.type === 'object' && top.expectKey) {
        if (top.keys.has(value)) {
          const where = stack.map((frame) => (frame.type === 'object' ? frame.current : `[${frame.index}]`)).filter((part) => part !== null).join('.');
          return { key: value, path: where || '(root)' };
        }
        top.keys.add(value);
        top.current = value;
        top.expectKey = false;
      }
      i = j + 1;
      continue;
    }
    if (ch === '{') stack.push({ type: 'object', keys: new Set(), expectKey: true, current: null });
    else if (ch === '[') stack.push({ type: 'array', index: 0 });
    else if (ch === '}' || ch === ']') stack.pop();
    else if (ch === ',') {
      const top = stack[stack.length - 1];
      if (top && top.type === 'object') top.expectKey = true;
      else if (top) top.index += 1;
    }
    i += 1;
  }
  return null;
}

export function parseInput(bytes) {
  let text = Buffer.isBuffer(bytes) ? bytes.toString('utf8') : String(bytes);
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    fail('parse', `Input is not valid JSON: ${error.message}`);
  }
  if (!isObject(value)) fail('parse', 'Input must be a JSON object.');
  const duplicate = findDuplicateKey(text);
  if (duplicate) fail('parse', `Input contains duplicate key ${JSON.stringify(duplicate.key)} in object ${duplicate.path}.`);
  return value;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

export function validateInput(input) {
  const problems = [];
  const bad = (message) => { if (problems.length < 60) problems.push(message); };
  const done = () => { if (problems.length) fail('validate', `Input rejected: ${problems.length} problem${problems.length === 1 ? '' : 's'}.`, problems); };

  if (input.render_input_version !== 1) bad('render_input_version must be 1');
  if (!isString(input.title) || !input.title.trim()) bad('title must be a nonempty string');
  const build = input.build;
  if (!isObject(build)) bad('build must be an object');
  else {
    if (!isString(build.core_version)) bad('build.core_version must be a string');
    if (!isCount(build.revision)) bad('build.revision must be a nonnegative integer');
    if (!(build.audit_id === null || isString(build.audit_id))) bad('build.audit_id must be a string or null');
    if (!isString(build.built_at)) bad('build.built_at must be a string');
    if (!isString(build.source_identity)) bad('build.source_identity must be a string');
    if (!BUILD_KINDS.includes(build.kind)) bad(`build.kind must be one of ${BUILD_KINDS.join(', ')}`);
  }
  const projection = input.projection;
  if (!isObject(projection)) { bad('projection must be an object'); done(); }
  if (![1, 2].includes(projection.projection_version)) bad('projection.projection_version must be 1 or 2');
  if (!isCount(projection.snapshot_revision)) bad('projection.snapshot_revision must be a nonnegative integer');
  if (!(projection.audit_id === null || isString(projection.audit_id))) bad('projection.audit_id must be a string or null');
  for (const field of ['nodes', 'connections', 'records', 'obligations', 'record_locations']) {
    if (!Array.isArray(projection[field])) bad(`projection.${field} must be an array`);
  }
  if (!isObject(projection.details)) bad('projection.details must be an object');
  if (!isObject(projection.summary)) bad('projection.summary must be an object');
  if (!isObject(projection.layout)) bad('projection.layout must be an object');
  done();

  const validateRef = (ref, where, pinned) => {
    if (!isObject(ref)) { bad(`${where} must be an object`); return null; }
    let ok = true;
    if (!isString(ref.collection) || !COLLECTION_PATTERN.test(ref.collection)) { bad(`${where}.collection must be a lowercase collection name`); ok = false; }
    if (!isString(ref.id) || !ID_PATTERN.test(ref.id)) { bad(`${where}.id must be a safe identifier`); ok = false; }
    if (pinned && !(Number.isInteger(ref.version) && ref.version >= 1)) { bad(`${where}.version must be a positive integer`); ok = false; }
    if (!pinned && ref.version !== undefined) { bad(`${where} must not carry a version`); ok = false; }
    return ok ? (pinned ? refKey(ref) : looseKey(ref)) : null;
  };
  const validateRefList = (list, where, pinned) => {
    if (!Array.isArray(list)) { bad(`${where} must be an array`); return []; }
    return list.map((ref, i) => validateRef(ref, `${where}[${i}]`, pinned));
  };
  const validateIdList = (list, where, options = {}) => {
    if (!Array.isArray(list)) { bad(`${where} must be an array`); return []; }
    const seen = new Set();
    list.forEach((id, i) => {
      if (!isString(id) || !ID_PATTERN.test(id)) { bad(`${where}[${i}] must be a safe identifier`); return; }
      if (options.unique && seen.has(id)) bad(`${where}[${i}] repeats ${id}`);
      seen.add(id);
      if (options.within && !options.within.has(id)) bad(`${where}[${i}] references unknown ${options.kind || 'identifier'} ${id}`);
    });
    return list;
  };
  const validateAssessment = (assessment, where) => {
    if (!isObject(assessment)) { bad(`${where}.assessment must be an object`); return; }
    if (!STATES.includes(assessment.state)) bad(`${where}.assessment.state must be one of ${STATES.join(', ')}`);
    if (!isString(assessment.label)) bad(`${where}.assessment.label must be a string`);
    if (!isString(assessment.explanation)) bad(`${where}.assessment.explanation must be a string`);
    validateRefList(assessment.check_refs, `${where}.assessment.check_refs`, true);
    validateIdList(assessment.finding_refs, `${where}.assessment.finding_refs`);
    validateIdList(assessment.missing_obligation_ids, `${where}.assessment.missing_obligation_ids`);
    if (!REVIEWS.includes(assessment.independent_review)) bad(`${where}.assessment.independent_review must be one of ${REVIEWS.join(', ')}`);
    if (assessment.review_display !== undefined) {
      const display = assessment.review_display;
      if (!isObject(display) || !Object.hasOwn(DISPLAY, display.status) || !isCount(display.unrated_count)
          || !isString(display.explanation) || !Array.isArray(display.finding_refs)) bad(`${where}.assessment.review_display is invalid`);
    }
  };

  // Records first: everything else points at them.
  const records = new Map();
  projection.records.forEach((record, i) => {
    const where = `projection.records[${i}]`;
    if (!isObject(record)) { bad(`${where} must be an object`); return; }
    const key = validateRef(record.ref, `${where}.ref`, true);
    if (!key) return;
    if (records.has(key)) { bad(`${where} repeats record ${key}`); return; }
    if (!isObject(record.body)) { bad(`${where}.body must be an object`); return; }
    records.set(key, record);
  });
  const recordsByLoose = new Map();
  for (const record of records.values()) {
    const loose = looseKey(record.ref);
    if (!recordsByLoose.has(loose) || recordsByLoose.get(loose).ref.version < record.ref.version) recordsByLoose.set(loose, record);
  }
  const requirePinned = (ref, where) => {
    const key = validateRef(ref, where, true);
    if (key && !records.has(key)) bad(`${where} references ${key}, which is not in projection.records`);
    return key;
  };
  const validateSupportExplanation = (value, assessment, where) => {
    if (value === undefined || value === null) return;
    if (!isObject(value)) { bad(`${where} must be an object or null`); return; }
    if (!['conditional', 'unavailable'].includes(value.availability) || value.availability !== assessment?.availability)
      bad(`${where} must describe the same blocked support as its assessment`);
    if (!isString(value.code) || !/^[a-z][a-z0-9_]*$/.test(value.code) || !isString(value.message) || !value.message.trim())
      bad(`${where} must have a cause code and message`);
    for (const field of ['target_ref', 'source_scope_ref', 'active_scope_ref', 'blocking_scope_ref', 'group_scope_ref'])
      if (value[field] != null) requirePinned(value[field], `${where}.${field}`);
    if (!Array.isArray(value.path_refs)) bad(`${where}.path_refs must be an array`);
    else value.path_refs.forEach((ref, index) => requirePinned(ref, `${where}.path_refs[${index}]`));
  };

  const obligations = new Map();
  projection.obligations.forEach((obligation, i) => {
    const where = `projection.obligations[${i}]`;
    if (!isObject(obligation)) { bad(`${where} must be an object`); return; }
    if (!isString(obligation.id) || !ID_PATTERN.test(obligation.id)) { bad(`${where}.id must be a safe identifier`); return; }
    if (obligations.has(obligation.id)) { bad(`${where} repeats obligation ${obligation.id}`); return; }
    validateRef(obligation.target, `${where}.target`, false);
    if (!isString(obligation.kind) || !obligation.kind.trim()) bad(`${where}.kind must be a nonempty string`);
    if (!ROLES.includes(obligation.role)) bad(`${where}.role must be one of ${ROLES.join(', ')}`);
    validateRefList(obligation.check_refs, `${where}.check_refs`, true);
    validateAssessment(obligation.assessment, where);
    obligations.set(obligation.id, obligation);
  });
  const obligationIds = new Set(obligations.keys());

  const details = new Map();
  Object.entries(projection.details).forEach(([key, detail]) => {
    const where = `projection.details[${JSON.stringify(key)}]`;
    if (!KEY_PATTERN.test(key)) { bad(`${where}: detail keys must be 1-512 characters without control characters`); return; }
    if (!isObject(detail)) { bad(`${where} must be an object`); return; }
    if (!Array.isArray(detail.record_refs)) bad(`${where}.record_refs must be an array`);
    else detail.record_refs.forEach((ref, i) => requirePinned(ref, `${where}.record_refs[${i}]`));
    if (!Array.isArray(detail.sections)) { bad(`${where}.sections must be an array`); return; }
    const sectionKeys = new Set();
    detail.sections.forEach((section, i) => {
      const at = `${where}.sections[${i}]`;
      if (!isObject(section)) { bad(`${at} must be an object`); return; }
      if (!isString(section.key) || !KEY_PATTERN.test(section.key)) { bad(`${at}.key must be 1-512 characters without control characters`); return; }
      if (sectionKeys.has(section.key)) bad(`${at}.key repeats ${section.key} within the detail`);
      sectionKeys.add(section.key);
      if (!isString(section.title)) bad(`${at}.title must be a string`);
      if (!SECTION_KINDS.includes(section.kind)) bad(`${at}.kind must be one of ${SECTION_KINDS.join(', ')}`);
      if (!(section.note === null || section.note === undefined || isString(section.note))) bad(`${at}.note must be a string or null`);
      if (!Array.isArray(section.record_refs)) bad(`${at}.record_refs must be an array`);
      else {
        const seen = new Set();
        section.record_refs.forEach((ref, j) => {
          const pinned = requirePinned(ref, `${at}.record_refs[${j}]`);
          if (pinned && seen.has(pinned)) bad(`${at}.record_refs[${j}] repeats ${pinned} within the section`);
          if (pinned) seen.add(pinned);
        });
      }
      validateIdList(section.obligation_ids, `${at}.obligation_ids`, { unique: true, within: obligationIds, kind: 'obligation' });
    });
    if (detail.reader !== undefined) {
      const reader = detail.reader;
      if (!isObject(reader) || reader.version !== 1) bad(`${where}.reader must be a version 1 reader block`);
      else {
        for (const field of ['item_ref', 'strategy_ref']) requirePinned(reader[field], `${where}.reader.${field}`);
        const visit = (value, at) => {
          if (!isObject(value)) { bad(`${at} must be an object`); return; }
          for (const [field, child] of Object.entries(value)) {
            if (field.endsWith('_ref')) { if (child !== null) requirePinned(child, `${at}.${field}`); }
            else if (field.endsWith('_refs')) {
              if (!Array.isArray(child)) bad(`${at}.${field} must be an array`);
              else child.forEach((ref, index) => requirePinned(ref, `${at}.${field}[${index}]`));
            } else if (field === 'assessment') validateAssessment(child, at);
            else if (['scope_chain', 'groups', 'case_scopes'].includes(field)) {
              if (!Array.isArray(child)) bad(`${at}.${field} must be an array`);
              else child.forEach((entry, index) => visit(entry, `${at}.${field}[${index}]`));
            }
          }
          validateSupportExplanation(value.support_explanation, value.assessment, `${at}.support_explanation`);
          if (value.relation !== undefined && !['target', 'linked_intermediate', 'subsidiary', 'unassociated'].includes(value.relation)) bad(`${at}.relation is unknown`);
        };
        for (const field of ['targets', 'arguments', 'applications']) {
          if (!Array.isArray(reader[field])) bad(`${where}.reader.${field} must be an array`);
          else reader[field].forEach((entry, index) => visit(entry, `${where}.reader.${field}[${index}]`));
        }
        if (reader.provenance_groups !== undefined) {
          if (!Array.isArray(reader.provenance_groups)) bad(`${where}.reader.provenance_groups must be an array`);
          else reader.provenance_groups.forEach((entry, index) => visit(entry, `${where}.reader.provenance_groups[${index}]`));
        }
        for (const field of ['finding_refs', 'source_limit_refs']) {
          if (!Array.isArray(reader[field])) bad(`${where}.reader.${field} must be an array`);
          else reader[field].forEach((ref, index) => requirePinned(ref, `${where}.reader.${field}[${index}]`));
        }
        (Array.isArray(reader.targets) ? reader.targets : []).forEach((target, index) => {
          if (!isObject(target)) return;
          if (!['registered', 'draft', 'missing'].includes(target.exact_state)) bad(`${where}.reader.targets[${index}].exact_state is unknown`);
          if (target.statement_field !== 'statement') bad(`${where}.reader.targets[${index}].statement_field must be statement`);
        });
      }
    }
    details.set(key, detail);
  });

  const nodes = new Map();
  projection.nodes.forEach((node, i) => {
    const where = `projection.nodes[${i}]`;
    if (!isObject(node)) { bad(`${where} must be an object`); return; }
    if (!isString(node.id) || !ID_PATTERN.test(node.id)) { bad(`${where}.id must be a safe identifier`); return; }
    if (nodes.has(node.id)) { bad(`${where} repeats node ${node.id}`); return; }
    validateRef(node.item_ref, `${where}.item_ref`, true);
    if (!isString(node.kind) || !Object.hasOwn(KINDS, node.kind)) bad(`${where}.kind ${JSON.stringify(node.kind)} is not one of ${Object.keys(KINDS).join(', ')}`);
    if (!isString(node.label) || !node.label.trim()) bad(`${where}.label must be a nonempty string`);
    if (!isString(node.caption)) bad(`${where}.caption must be a string`);
    validateAssessment(node.assessment, where);
    if (!isString(node.detail_key) || !details.has(node.detail_key)) bad(`${where}.detail_key must name a key of projection.details`);
    nodes.set(node.id, node);
  });

  const connections = new Map();
  projection.connections.forEach((connection, i) => {
    const where = `projection.connections[${i}]`;
    if (!isObject(connection)) { bad(`${where} must be an object`); return; }
    if (!isString(connection.id) || !ID_PATTERN.test(connection.id)) { bad(`${where}.id must be a safe identifier`); return; }
    if (connections.has(connection.id)) { bad(`${where} repeats connection ${connection.id}`); return; }
    if (!isString(connection.from) || !nodes.has(connection.from)) bad(`${where}.from must name a node`);
    if (!isString(connection.to) || !nodes.has(connection.to)) bad(`${where}.to must name a node`);
    validateIdList(connection.primary_use_ids, `${where}.primary_use_ids`, { unique: true });
    if (!Array.isArray(connection.groups)) bad(`${where}.groups must be an array`);
    else connection.groups.forEach((group, j) => {
      const at = `${where}.groups[${j}]`;
      if (!isObject(group)) { bad(`${at} must be an object`); return; }
      for (const field of ['argument_id', 'group_id']) {
        if (!(group[field] === null || (isString(group[field]) && ID_PATTERN.test(group[field])))) bad(`${at}.${field} must be a safe identifier or null`);
      }
      validateIdList(group.use_ids, `${at}.use_ids`);
      validateIdList(group.obligation_ids, `${at}.obligation_ids`, { within: obligationIds, kind: 'obligation' });
      validateAssessment(group.assessment, at);
    });
    validateRefList(connection.support_refs, `${where}.support_refs`, false);
    validateIdList(connection.obligation_ids, `${where}.obligation_ids`, { within: obligationIds, kind: 'obligation' });
    validateRefList(connection.context_refs, `${where}.context_refs`, false);
    validateAssessment(connection.assessment, where);
    for (const [index, application] of (connection.applications || []).entries())
      validateSupportExplanation(application.support_explanation, application.assessment, `${where}.applications[${index}].support_explanation`);
    if (!isString(connection.detail_key) || !details.has(connection.detail_key)) bad(`${where}.detail_key must name a key of projection.details`);
    connections.set(connection.id, connection);
  });

  const hypotheses = new Map();
  const hypothesisPairs = new Set();
  const hypothesisList = projection.hypothesis_connections ?? [];
  if (!Array.isArray(hypothesisList)) bad('projection.hypothesis_connections must be an array');
  else hypothesisList.forEach((relation, i) => {
    const where = `projection.hypothesis_connections[${i}]`;
    if (!isObject(relation)) { bad(`${where} must be an object`); return; }
    if (!isString(relation.id) || !ID_PATTERN.test(relation.id) || hypotheses.has(relation.id) || connections.has(relation.id)) bad(`${where} needs a unique safe id`);
    if (!nodes.has(relation.from) || !nodes.has(relation.to) || relation.from === relation.to) bad(`${where} needs distinct displayed endpoints`);
    const pair = JSON.stringify([relation.from, relation.to]);
    if (hypothesisPairs.has(pair)) bad(`${where} repeats a premise/result pair`);
    hypothesisPairs.add(pair);
    if (!['hypothesis', 'setup'].includes(relation.kind)) bad(`${where} has an unknown kind`);
    for (const field of ['premise_ref', 'target_ref', 'spec_ref', 'statement_ref']) requirePinned(relation[field], `${where}.${field}`);
    if (!Array.isArray(relation.scope_refs) || !relation.scope_refs.length) bad(`${where} needs authorizing scopes`);
    else relation.scope_refs.forEach((ref, j) => requirePinned(ref, `${where}.scope_refs[${j}]`));
    const target = nodes.get(relation.to), premise = nodes.get(relation.from);
    if (target && (relation.detail_key !== target.detail_key || refKey(relation.target_ref) !== refKey(target.item_ref))) bad(`${where} differs from its target`);
    if (premise && refKey(relation.premise_ref) !== refKey(premise.item_ref)) bad(`${where} differs from its premise`);
    const existing = projection.connections.find(edge => edge.from === relation.from && edge.to === relation.to);
    if ((relation.proof_connection_id ?? null) !== (existing?.id ?? null)) bad(`${where} has an incorrect proof connection`);
    if (relation.assessment !== undefined) bad(`${where} must not carry a proof assessment`);
    hypotheses.set(relation.id, relation);
  });

  projection.record_locations.forEach((location, i) => {
    const where = `projection.record_locations[${i}]`;
    if (!isObject(location)) { bad(`${where} must be an object`); return; }
    requirePinned(location.ref, `${where}.ref`);
    if (!isString(location.detail_key) || !details.has(location.detail_key)) { bad(`${where}.detail_key must name a key of projection.details`); return; }
    const detail = details.get(location.detail_key);
    if (!isString(location.section_key) || !Array.isArray(detail.sections) || !detail.sections.some((section) => isObject(section) && section.key === location.section_key)) {
      bad(`${where}.section_key must name a section of detail ${JSON.stringify(location.detail_key)}`);
    }
  });

  if (projection.projection_version === 2 && projection.worklist === undefined) bad('projection.worklist must be present in version 2');
  if (projection.worklist !== undefined && projection.worklist !== null) {
    const work = projection.worklist;
    if (!isObject(work)) bad('projection.worklist must be an object or null');
    else {
      if (work.revision !== projection.snapshot_revision) bad('projection.worklist.revision must match the snapshot');
      if (typeof work.analysis_complete !== 'boolean') bad('projection.worklist.analysis_complete must be boolean');
      if (!Array.isArray(work.tasks)) bad('projection.worklist.tasks must be an array');
      else work.tasks.forEach((task, i) => {
        const where = `projection.worklist.tasks[${i}]`;
        if (!isObject(task)) { bad(`${where} must be an object`); return; }
        if (!obligationIds.has(task.id)) bad(`${where}.id must name a represented obligation`);
        if (!isString(task.label)) bad(`${where}.label must be a string`);
        if (!ROLES.includes(task.role)) bad(`${where}.role must be a checking role`);
        if (typeof task.required !== 'boolean') bad(`${where}.required must be boolean`);
        if (!['ready', 'waiting', 'needs_coordinator', 'satisfied'].includes(task.state)) bad(`${where}.state is unknown`);
        if (!(task.next_action === null || isString(task.next_action))) bad(`${where}.next_action must be text or null`);
        if (task.location !== null) {
          const location = task.location;
          if (!isObject(location)) { bad(`${where}.location must be an object or null`); return; }
          requirePinned(location.ref, `${where}.location.ref`);
          const detail = details.get(location.detail_key);
          const section = detail && detail.sections.find(row => row.key === location.section_key);
          if (!section) bad(`${where}.location must name an existing reader section`);
          if (location.obligation_id !== undefined && (location.obligation_id !== task.id || !section || !section.obligation_ids.includes(task.id)))
            bad(`${where}.location must name this task's actual obligation`);
        }
      });
      if (!Array.isArray(work.coordinator_actions) || work.coordinator_actions.some(action => !isObject(action) || !isString(action.message)))
        bad('projection.worklist.coordinator_actions must contain readable messages');
    }
  }

  const summary = projection.summary;
  if (!isObject(summary.scope)) bad('projection.summary.scope must be an object');
  else {
    if (!isString(summary.scope.mode)) bad('projection.summary.scope.mode must be a string');
    validateRefList(summary.scope.target_refs, 'projection.summary.scope.target_refs', false);
    if (!Array.isArray(summary.scope.exclusions)) bad('projection.summary.scope.exclusions must be an array');
  }
  if (summary.overview_scope !== undefined) {
    if (!isObject(summary.overview_scope)) bad('projection.summary.overview_scope must be an object');
    else {
      if (!(summary.overview_scope.text === null || isString(summary.overview_scope.text))) bad('projection.summary.overview_scope.text must be text or null');
      if (!Array.isArray(summary.overview_scope.exclusions) || !summary.overview_scope.exclusions.every(isString)) bad('projection.summary.overview_scope.exclusions must be an array of strings');
    }
  }
  if (!isObject(summary.progress)) bad('projection.summary.progress must be an object');
  else {
    if (typeof summary.progress.process_complete !== 'boolean') bad('projection.summary.progress.process_complete must be a boolean');
    for (const field of PROGRESS_FIELDS) if (!isCount(summary.progress[field])) bad(`projection.summary.progress.${field} must be a nonnegative integer`);
  }
  if (!isObject(summary.findings)) bad('projection.summary.findings must be an object');
  else {
    for (const field of ['open', 'resolved', 'superseded']) if (!isCount(summary.findings[field])) bad(`projection.summary.findings.${field} must be a nonnegative integer`);
    validateIdList(summary.findings.refs, 'projection.summary.findings.refs', { unique: true });
    const counts = summary.findings.current_by_review_status;
    if (counts !== undefined) {
      if (!isObject(counts)) bad('projection.summary.findings.current_by_review_status must be an object');
      else for (const status of FINDING_STATUSES) if (!isCount(counts[status]))
        bad(`projection.summary.findings.current_by_review_status.${status} must be a count`);
    }
  }
  validateIdList(summary.source_limits, 'projection.summary.source_limits', { unique: true });
  if (summary.limitations !== undefined && (!Array.isArray(summary.limitations) || !summary.limitations.every(isString))) bad('projection.summary.limitations must be an array of strings');
  if (!(summary.published_revision === null || isCount(summary.published_revision))) bad('projection.summary.published_revision must be a nonnegative integer or null');
  if (summary.factual !== undefined) {
    const factual = summary.factual;
    if (!isObject(factual) || !isObject(factual.work) || !isObject(factual.work.checks) ||
        !isObject(factual.work.current_primary_outcomes) || !isObject(factual.statement_support) ||
        !isObject(factual.statement_support.counts) || !isObject(factual.independent_review) || !isObject(factual.scope)) {
      bad('projection.summary.factual must contain work, statement support, scope and independent review facts');
    } else {
      if (factual.revision !== projection.snapshot_revision || factual.process_complete !== summary.progress.process_complete)
        bad('projection.summary.factual must describe the same snapshot and completion state');
      for (const field of ['current_complete', 'draft', 'needs_review', 'historical_complete', 'superseded'])
        if (!isCount(factual.work.checks[field])) bad(`projection.summary.factual.work.checks.${field} must be a count`);
      for (const field of ['available', 'conditional', 'unavailable'])
        if (!isCount(factual.statement_support.counts[field])) bad(`projection.summary.factual.statement_support.counts.${field} must be a count`);
      for (const field of ['supported', 'gap', 'refuted', 'inconclusive'])
        if (!isCount(factual.work.current_primary_outcomes[field])) bad(`projection.summary.factual.work.current_primary_outcomes.${field} must be a count`);
      const effectiveOutcomes = factual.work.current_effective_outcomes;
      if (effectiveOutcomes !== undefined) {
        if (!isObject(effectiveOutcomes)) bad('projection.summary.factual.work.current_effective_outcomes must be an object');
        else for (const field of ['supported', 'gap', 'refuted', 'inconclusive'])
          if (!isCount(effectiveOutcomes[field])) bad(`projection.summary.factual.work.current_effective_outcomes.${field} must be a count`);
      }
      const groups = factual.work.obligation_groups;
      if (groups !== undefined && groups !== null) {
        if (!Array.isArray(groups)) bad('projection.summary.factual.work.obligation_groups must be an array or null');
        else {
          const seen = new Set();
          let required = 0, completed = 0;
          groups.forEach((row, index) => {
            const where = `projection.summary.factual.work.obligation_groups[${index}]`;
            if (!isObject(row)) { bad(`${where} must be an object`); return; }
            if (!ROLES.includes(row.role)) bad(`${where}.role must be one of ${ROLES.join(', ')}`);
            if (!isString(row.kind) || !/^[a-z][a-z0-9_]*$/.test(row.kind)) bad(`${where}.kind must be an examination kind`);
            const key = `${row.role}:${row.kind}`;
            if (seen.has(key)) bad(`${where} repeats role and kind ${key}`);
            seen.add(key);
            for (const field of ['required', 'completed', 'unfinished'])
              if (!isCount(row[field])) bad(`${where}.${field} must be a count`);
            if (row.required === 0) bad(`${where}.required must be positive`);
            if (row.required !== row.completed + row.unfinished) bad(`${where} counts must satisfy required = completed + unfinished`);
            required += row.required;
            completed += row.completed;
          });
          if (required !== summary.progress?.required_obligations || completed !== summary.progress?.completed_current_obligations)
            bad('projection.summary.factual.work.obligation_groups totals must match summary.progress');
        }
      }
      for (const rows of [factual.source_limits, factual.unresolved_external_sources, factual.statement_support.unresolved, factual.scope.exclusions])
        if (!Array.isArray(rows) || rows.some(row => !isObject(row) || !isString(row.label)))
          bad('projection.summary.factual lists must contain labeled rows');
      if (!REVIEWS.includes(factual.independent_review.state)) bad('projection.summary.factual independent review state is invalid');
      for (const key of ['scope', 'independent_review'])
        if (factual[key].explanation !== undefined && !isString(factual[key].explanation))
          bad(`projection.summary.factual.${key}.explanation must be text`);
      if (!Array.isArray(factual.independent_review.qualification_limitations) ||
          !factual.independent_review.qualification_limitations.every(isString))
        bad('projection.summary.factual qualification limitations must be text');
      const reviewerContext = factual.independent_review.reviewer_context;
      if (reviewerContext !== undefined) {
        if (!isObject(reviewerContext)) bad('projection.summary.factual.independent_review.reviewer_context must be an object');
        else for (const role of ['primary', 'independent']) {
          const row = reviewerContext[role];
          if (!isObject(row) || !Array.isArray(row.items) || !row.items.every(isString) ||
              row.items.length > 3 || new Set(row.items).size !== row.items.length ||
              !isCount(row.total) || row.items.length > row.total)
            bad(`projection.summary.factual.independent_review.reviewer_context.${role} must contain up to three unique identities and their total`);
        }
      }
    }
  }

  const layout = projection.layout;
  if (!LAYOUT_MODES.includes(layout.mode)) bad(`projection.layout.mode must be one of ${LAYOUT_MODES.join(', ')}`);
  if (!Array.isArray(layout.reasons) || layout.reasons.some((reason) => !isString(reason))) bad('projection.layout.reasons must be an array of strings');

  const display = input.display === undefined ? {} : input.display;
  if (!isObject(display)) bad('display must be an object');
  const refs = isObject(display) && display.refs !== undefined ? display.refs : {};
  if (!isObject(refs)) bad('display.refs must be an object');
  const fragments = new Map();
  if (isObject(refs)) {
    Object.entries(refs).forEach(([key, value]) => {
      const where = `display.refs[${JSON.stringify(key)}]`;
      if (!records.has(key)) { bad(`${where} does not match any projection record (expected COLLECTION:ID:VERSION)`); return; }
      if (!isObject(value)) { bad(`${where} must be an object`); return; }
      for (const [field, fragment] of Object.entries(value)) {
        if (!DISPLAY_KEYS.includes(field)) bad(`${where}.${field} is not a known display fragment (${DISPLAY_KEYS.join(', ')})`);
        else if (field === 'conditions_html') {
          if (!Array.isArray(fragment) || fragment.some((entry) => !isString(entry))) bad(`${where}.conditions_html must be an array of strings`);
        } else if (!isString(fragment)) bad(`${where}.${field} must be a string`);
      }
      fragments.set(key, value);
    });
  }
  const mathDiagnostics = isObject(display) && display.math_diagnostics !== undefined ? display.math_diagnostics : [];
  const mathDiagnosticSummary = isObject(display) && display.math_diagnostic_summary !== undefined ? display.math_diagnostic_summary : null;
  const sourceCaptureNotes = isObject(display) && display.source_capture_notes !== undefined ? display.source_capture_notes : [];
  if (!Array.isArray(sourceCaptureNotes)) bad('display.source_capture_notes must be an array');
  else sourceCaptureNotes.forEach((entry, index) => {
    const where = `display.source_capture_notes[${index}]`;
    if (!isObject(entry)) { bad(`${where} must be an object`); return; }
    validateRef(entry.source_ref, `${where}.source_ref`, true);
    if (entry.source_ref?.collection !== 'sources') bad(`${where}.source_ref must reference sources`);
    if (!(entry.source_path === null || isString(entry.source_path))) bad(`${where}.source_path must be text or null`);
    if (!isObject(entry.locator)) bad(`${where}.locator must be an object`);
    if (!isString(entry.description) || !entry.description.trim()) bad(`${where}.description must be nonblank text`);
    if (!Array.isArray(entry.anchor_refs) || !entry.anchor_refs.length) bad(`${where}.anchor_refs must be a nonempty array`);
    else entry.anchor_refs.forEach((ref, at) => {
      requirePinned(ref, `${where}.anchor_refs[${at}]`);
      if (ref?.collection !== 'anchors') bad(`${where}.anchor_refs[${at}] must reference anchors`);
    });
  });
  if (!Array.isArray(mathDiagnostics)) bad('display.math_diagnostics must be an array');
  else mathDiagnostics.forEach((entry, index) => {
    const where = `display.math_diagnostics[${index}]`;
    if (!isObject(entry)) { bad(`${where} must be an object`); return; }
    for (const field of ['kind','classification','reason','excerpt','collection','record_id','field_path']) if (!isString(entry[field])) bad(`${where}.${field} must be text`);
    if (!Number.isInteger(entry.record_version) || entry.record_version < 1) bad(`${where}.record_version must be positive`);
    if (!['inline','block'].includes(entry.display)) bad(`${where}.display must be inline or block`);
    if (entry.expression_index !== undefined && !isCount(entry.expression_index)) bad(`${where}.expression_index must be a count`);
  });
  if (mathDiagnosticSummary !== null && (!isObject(mathDiagnosticSummary) || !isCount(mathDiagnosticSummary.total) || !Array.isArray(mathDiagnosticSummary.messages) || !mathDiagnosticSummary.messages.every(isString))) bad('display.math_diagnostic_summary needs total and text messages');
  done();

  return {
    mathDiagnostics, mathDiagnosticSummary, sourceCaptureNotes,
    title: input.title,
    build,
    projection,
    nodeList: projection.nodes,
    connectionList: projection.connections,
    hypothesisList,
    hypotheses,
    graphConnectionList: [...projection.connections, ...hypothesisList.filter(relation => !relation.proof_connection_id)],
    graphConnections: new Map([...connections, ...[...hypotheses].filter(([, relation]) => !relation.proof_connection_id)]),
    nodes,
    connections,
    records,
    recordsByLoose,
    obligations,
    details,
    layout,
    summary,
    fragments,
  };
}

// ---------------------------------------------------------------------------
// Layout (directed graphs)
// ---------------------------------------------------------------------------

function findCycle(stuckIds, outgoing) {
  const stuck = new Set(stuckIds);
  const state = new Map();
  const stack = [];
  const visit = (id) => {
    state.set(id, 1);
    stack.push(id);
    for (const connection of outgoing.get(id)) {
      if (!stuck.has(connection.to)) continue;
      const seen = state.get(connection.to) || 0;
      if (seen === 1) return [...stack.slice(stack.indexOf(connection.to)), connection.to];
      if (seen === 0) {
        const found = visit(connection.to);
        if (found) return found;
      }
    }
    stack.pop();
    state.set(id, 2);
    return null;
  };
  for (const id of stuckIds) {
    if (!state.get(id)) {
      const found = visit(id);
      if (found) return found;
    }
  }
  return stuckIds;
}

// DFS back edges are omitted only from ranking. They retain their identity,
// direction and assessment and are drawn on separate exterior rails.
function feedbackEdges(nodes, outgoing) {
  const state = new Map(), feedback = new Set();
  for (const id of [...nodes.keys()].sort()) {
    if (state.has(id)) continue;
    const stack = [{ id, edges: [...outgoing.get(id)].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0), next: 0 }];
    state.set(id, 1);
    while (stack.length) {
      const frame = stack.at(-1);
      if (frame.next === frame.edges.length) { state.set(frame.id, 2); stack.pop(); continue; }
      const edge = frame.edges[frame.next++];
      if (state.get(edge.to) === 1) feedback.add(edge.id);
      else if (!state.has(edge.to)) {
        state.set(edge.to, 1);
        stack.push({ id: edge.to, edges: [...outgoing.get(edge.to)].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0), next: 0 });
      }
    }
  }
  return feedback;
}

// Longest-path layers place consuming results; source prerequisites move next
// to their earliest consumer. Coordinates confer no mathematical assessment.
export function layoutGraph(model) {
  const nodes = new Map(model.nodeList.map((node, order) => [node.id, { id: node.id, order, rank: 0, source: node }]));
  const incoming = new Map(model.nodeList.map((node) => [node.id, []]));
  const outgoing = new Map(model.nodeList.map((node) => [node.id, []]));
  (model.graphConnectionList || model.connectionList).forEach((connection) => { incoming.get(connection.to).push(connection); outgoing.get(connection.from).push(connection); });
  const feedback = model.layout.mode === 'cyclic' ? feedbackEdges(nodes, outgoing) : new Set();
  const rankingIncoming = new Map([...incoming].map(([id, list]) => [id, list.filter((edge) => !feedback.has(edge.id))]));
  const rankingOutgoing = new Map([...outgoing].map(([id, list]) => [id, list.filter((edge) => !feedback.has(edge.id))]));
  const remaining = new Map([...rankingIncoming].map(([id, list]) => [id, list.length]));
  const queue = model.nodeList.filter((node) => !remaining.get(node.id)).map((node) => node.id);
  let visited = 0;
  for (let index = 0; index < queue.length; index += 1) {
    const id = queue[index];
    visited += 1;
    for (const connection of rankingOutgoing.get(id)) {
      const target = nodes.get(connection.to);
      target.rank = Math.max(target.rank, nodes.get(id).rank + 1);
      remaining.set(connection.to, remaining.get(connection.to) - 1);
      if (!remaining.get(connection.to)) queue.push(connection.to);
    }
  }
  if (visited !== nodes.size) {
    const stuck = [...remaining].filter(([, count]) => count > 0).map(([id]) => id);
    const cycle = findCycle(stuck, outgoing);
    fail('layout', 'Connections form a cycle; a dag layout is impossible and no index fallback is applied.', [`cycle: ${cycle.join(' -> ')}`, `nodes blocked by the cycle: ${stuck.join(', ')}`]);
  }
  alignSourcePrerequisites(nodes, incoming, outgoing);
  const components = [];
  const assigned = new Set();
  nodes.forEach((start) => {
    if (assigned.has(start.id)) return;
    const ids = [start.id];
    assigned.add(start.id);
    for (let i = 0; i < ids.length; i += 1) {
      for (const connection of [...incoming.get(ids[i]), ...outgoing.get(ids[i])]) {
        const other = connection.from === ids[i] ? connection.to : connection.from;
        if (!assigned.has(other)) { assigned.add(other); ids.push(other); }
      }
    }
    const members = ids.map((id) => nodes.get(id)).sort((a, b) => a.order - b.order);
    const ranks = Array.from({ length: Math.max(...members.map((node) => node.rank)) + 1 }, () => []);
    members.forEach((node) => ranks[node.rank].push(node));
    ranks.forEach((rank) => rank.forEach((node, index) => { node.position = index; }));
    for (let round = 0; round < 4; round += 1) {
      for (let r = 1; r < ranks.length; r += 1) {
        const centre = (node) => {
          const parents = rankingIncoming.get(node.id).map((connection) => nodes.get(connection.from).position);
          return parents.length ? parents.reduce((sum, value) => sum + value, 0) / parents.length : node.position;
        };
        ranks[r].sort((a, b) => centre(a) - centre(b) || a.order - b.order);
        ranks[r].forEach((node, index) => { node.position = index; });
      }
    }
    const memberIds = new Set(ids);
    const returnConnections = (model.graphConnectionList || model.connectionList).filter((edge) => feedback.has(edge.id) && memberIds.has(edge.from))
      .sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    components.push({ members, ranks, returnConnections, rowCount: Math.max(...ranks.map((rank) => rank.length)) });
  });
  const longConnections = (model.graphConnectionList || model.connectionList).filter((connection) => nodes.get(connection.to).rank > nodes.get(connection.from).rank + 1);
  const headingHeight = components.length > 1 ? 32 : 0, gapX = 24, gapY = 68;
  components.forEach((component) => {
    component.width = BOX.margin * 2 + (component.ranks.length - 1) * BOX.column + BOX.w;
    component.height = headingHeight + (component.returnConnections.length ? 20 + component.returnConnections.length * 24 : 0)
      + (component.rowCount - 1) * BOX.row + BOX.h;
  });
  // Pack disconnected arguments in stable rows. Their internal ranks and routes
  // are unchanged; an inventory of isolated results no longer forms one tall strip.
  const widest = Math.max(...components.map((component) => component.width));
  const area = components.reduce((sum, component) => sum + component.width * (component.height + gapY), 0);
  const rowWidth = components.length > 1 ? Math.max(widest, Math.sqrt(area * 1.5)) : widest;
  let left = 0, top = BOX.margin, rowBottom = top, width = 0;
  components.forEach((component, componentIndex) => {
    if (left && left + component.width > rowWidth) {
      left = 0;
      top = rowBottom + gapY;
    }
    component.left = left;
    component.top = top;
    component.railTop = top + headingHeight;
    component.nodeTop = component.railTop + (component.returnConnections.length ? 20 + component.returnConnections.length * 24 : 0);
    component.ranks.forEach((rank, r) => rank.forEach((node, index) => {
      node.x = left + BOX.margin + r * BOX.column;
      node.y = component.nodeTop + index * BOX.row;
      node.width = BOX.w;
      node.height = BOX.h;
      node.component = componentIndex;
    }));
    component.bottom = component.nodeTop + (component.rowCount - 1) * BOX.row + BOX.h;
    rowBottom = Math.max(rowBottom, component.bottom);
    width = Math.max(width, left + component.width);
    left += component.width + gapX;
  });
  const gapConnections = new Map();
  // Match the previous outgoing-map traversal order so channel geometry is stable.
  for (const entries of outgoing.values()) for (const connection of entries) {
    const from = nodes.get(connection.from), to = nodes.get(connection.to);
    const key = `${from.component}:${from.rank}:${to.rank}`;
    if (!gapConnections.has(key)) gapConnections.set(key, []);
    gapConnections.get(key).push(connection);
  }
  return {
    nodes, components, incoming, outgoing, longConnections, feedback, gapConnections,
    width,
    height: rowBottom + BOX.margin,
  };
}

function roundedPath(points, radius = 8) {
  const commands = [`M ${fmt(points[0][0])} ${fmt(points[0][1])}`];
  for (let i = 1; i < points.length - 1; i += 1) {
    const [px, py] = points[i - 1], [cx, cy] = points[i], [nx, ny] = points[i + 1];
    const before = Math.hypot(cx - px, cy - py), after = Math.hypot(nx - cx, ny - cy);
    const r = Math.min(radius, before / 2, after / 2);
    if (r < 1) { commands.push(`L ${fmt(cx)} ${fmt(cy)}`); continue; }
    commands.push(`L ${fmt(cx - (cx - px) / before * r)} ${fmt(cy - (cy - py) / before * r)}`);
    commands.push(`Q ${fmt(cx)} ${fmt(cy)} ${fmt(cx + (nx - cx) / after * r)} ${fmt(cy + (ny - cy) / after * r)}`);
  }
  commands.push(`L ${fmt(points.at(-1)[0])} ${fmt(points.at(-1)[1])}`);
  return commands.join(' ');
}

function edgePoints(connection, graph) {
  const a = graph.nodes.get(connection.from), b = graph.nodes.get(connection.to);
  const outs = graph.outgoing.get(a.id), ins = graph.incoming.get(b.id);
  const port = (node, list) => round2(node.y + 13 + (list.indexOf(connection) + 1) / (list.length + 1) * (BOX.h - 26));
  const start = [a.x + BOX.w, port(a, outs)], end = [b.x, port(b, ins)];
  if (graph.feedback.has(connection.id)) {
    const component = graph.components[a.component];
    const rail = component.railTop + component.returnConnections.indexOf(connection) * 24;
    const exit = round2(start[0] + 12 + (outs.indexOf(connection) + 1) / (outs.length + 1) * 16);
    const enter = round2(end[0] - 12 - (ins.indexOf(connection) + 1) / (ins.length + 1) * 16);
    return [start, [exit, start[1]], [exit, rail], [enter, rail], [enter, end[1]], end];
  }
  const longIndex = graph.longConnections.indexOf(connection);
  if (longIndex >= 0) {
    const component = graph.components[a.component];
    const target = (start[1] + end[1]) / 2;
    const corridors = Array.from({ length: component.rowCount }, (_, row) => component.nodeTop + row * BOX.row + BOX.h + (BOX.row - BOX.h) / 2);
    const rail = corridors.reduce((best, value) => (Math.abs(value - target) < Math.abs(best - target) ? value : best));
    const exit = round2(start[0] + 18 + (outs.indexOf(connection) + 1) / (outs.length + 1) * 24);
    const enter = round2(end[0] - 18 - (ins.indexOf(connection) + 1) / (ins.length + 1) * 24);
    return [start, [exit, start[1]], [exit, rail], [enter, rail], [enter, end[1]], end];
  }
  const sameGap = sameGapConnections(graph, a, b);
  const channel = round2(start[0] + 25 + (sameGap.indexOf(connection) + 1) / (sameGap.length + 1) * (BOX.column - BOX.w - 50));
  return [start, [channel, start[1]], [channel, end[1]], end];
}

function sameGapConnections(graph, a, b) {
  return graph.gapConnections.get(`${a.component}:${a.rank}:${b.rank}`) || [];
}

function captionLines(text, limit = 25) {
  const words = String(text || '').split(/\s+/u).filter(Boolean);
  if (!words.length) return [];
  const lines = [''];
  for (const word of words) {
    const at = lines.length - 1;
    if (lines[at] && textUnits(`${lines[at]} ${word}`) > limit) lines.push(word);
    else lines[at] += (lines[at] ? ' ' : '') + word;
  }
  const clip = (line) => (textUnits(line) > limit ? `${line.slice(0, limit - 1)}…` : line);
  if (lines.length > 2) return [clip(lines[0]), `${lines[1].slice(0, limit - 1)}…`];
  return lines.map(clip);
}

// ---------------------------------------------------------------------------
// HTML fragments shared by the graph, the index and the details
// ---------------------------------------------------------------------------

function stateBadge(state, text) {
  return `<span class="proof-state-badge s-${esc(state)}"><span class="proof-state-glyph" aria-hidden="true">${esc(STATE_GLYPHS[state])}</span>${esc(text === undefined ? STATE_LABELS[state] : text)}</span>`;
}

function kindBadge(kind) {
  return `<span class="proof-kind-badge k-${esc(kind)}">${esc(KINDS[kind][0])}</span>`;
}

function reviewNote(review) {
  return `<span class="proof-review r-${esc(review)}">Independent review: ${esc(REVIEW_LABELS[review])}</span>`;
}

// Wrap MathML so long formulas scroll inside their box instead of widening it.
function prepareFragment(html) {
  return String(html).replace(/<math\b[\s\S]*?<\/math>/gi, (match) => `<span class="proof-formula${/display\s*=\s*["']block["']/i.test(match.slice(0, match.indexOf('>') + 1)) ? ' proof-formula-block' : ''}">${match}</span>`);
}

function prepareLabelFragment(html) {
  // Labels stay phrasing content even when their authored math used display delimiters.
  return prepareFragment(String(html).replace(/(<math\b[^>]*\bdisplay\s*=\s*["'])block(["'])/gi, '$1inline$2'));
}

// Navigation is derived from the frozen reader contexts, never from a newer record.
// Only owned proof evidence moves; shared and ambiguous evidence keeps its saved location.
function navigationLocations(model, nodeDetails) {
  const locations = new Map(), occurrences = new Map(), represented = new Map();
  const claims = new Map(), targets = new Map();
  const claim = (map, ref, detail) => {
    if (!ref || !Number.isInteger(ref.version)) return;
    const key = refKey(ref);
    if (!map.has(key)) map.set(key, new Set());
    map.get(key).add(detail);
  };
  const sole = values => values?.size === 1 ? values.values().next().value : null;
  for (const location of model.projection.record_locations) {
    const key = refKey(location.ref);
    if (!locations.has(key)) locations.set(key, location);
  }
  for (const record of model.records.values()) {
    const key = looseKey(record.ref);
    if (!represented.has(key)) represented.set(key, new Set());
    represented.get(key).add(refKey(record.ref));
  }
  for (const [detail, value] of model.details) {
    for (const section of value.sections) for (const ref of section.record_refs) {
      const key = refKey(ref);
      if (!occurrences.has(key)) occurrences.set(key, new Map());
      if (!occurrences.get(key).has(detail)) occurrences.get(key).set(detail, section.key);
    }
  }
  for (const node of model.nodeList) {
    const reader = model.details.get(node.detail_key)?.reader;
    if (!reader || refKey(reader.item_ref) !== refKey(node.item_ref)) continue;
    const consumerTargets = new Set();
    for (const target of reader.targets) {
      claim(targets, target.target_ref, node.detail_key);
      consumerTargets.add(refKey(target.target_ref));
    }
    for (const application of reader.applications) {
      if (!application.to_ref || !consumerTargets.has(refKey(application.to_ref))) continue;
      if (application.use_ref?.collection === 'uses') claim(claims, application.use_ref, node.detail_key);
      if (application.application_ref?.collection === 'application_details') claim(claims, application.application_ref, node.detail_key);
    }
    for (const argument of reader.arguments) {
      if (argument.argument_ref?.collection === 'arguments') claim(claims, argument.argument_ref, node.detail_key);
      for (const group of argument.groups) if (group.group_ref?.collection === 'groups') claim(claims, group.group_ref, node.detail_key);
    }
    for (const group of reader.provenance_groups || []) if (group.group_ref?.collection === 'groups') claim(claims, group.group_ref, node.detail_key);
  }
  for (const record of model.records.values()) {
    if (record.ref.collection !== 'observations') continue;
    const target = record.body.target;
    if (!isObject(target) || !isString(target.collection) || !isString(target.id)) continue;
    const pinned = Number.isInteger(target.version);
    if (!pinned && represented.get(looseKey(record.ref))?.size !== 1) continue;
    const targetKey = pinned ? refKey(target) : sole(represented.get(looseKey(target)));
    const owner = targetKey && sole(targets.get(targetKey));
    if (owner) claim(claims, record.ref, owner);
  }
  for (const [key, candidates] of claims) {
    const owner = sole(candidates), section = owner && occurrences.get(key)?.get(owner);
    const saved = locations.get(key);
    if (saved && section && owner !== saved.detail_key) {
      locations.set(key, {...saved, detail_key:owner, section_key:section});
    }
  }
  for (const [key, detail] of nodeDetails) {
    const saved = locations.get(key);
    if (!saved || detail !== saved.detail_key) locations.set(key, {...(saved || {ref:model.records.get(key).ref}), detail_key:detail, section_key:null});
  }
  return locations;
}

class Renderer {
  constructor(model, graph) {
    this.model = model;
    this.graph = graph;
    this.content = createReaderContent(model);
    this.detailIndex = new Map([...model.details.keys()].map((key, i) => [key, i + 1]));
    this.nodeDetailsByPinned = new Map(model.nodeList.map(node => [refKey(node.item_ref), node.detail_key]));
    this.tasksByObligation = new Map();
    for (const task of model.projection.worklist?.tasks || []) {
      if (!this.tasksByObligation.has(task.id)) this.tasksByObligation.set(task.id, []);
      this.tasksByObligation.get(task.id).push(task);
    }
    this.locationsByPinned = navigationLocations(model, this.nodeDetailsByPinned);
    this.locationsByLoose = new Map();
    for (const location of this.locationsByPinned.values()) {
      const loose = looseKey(location.ref);
      if (!this.locationsByLoose.has(loose)) this.locationsByLoose.set(loose, location);
    }
    this.owners = new Map();
    for (const node of model.nodeList) this.pushOwner(node.detail_key, { type: 'node', node });
    for (const connection of model.connectionList) this.pushOwner(connection.detail_key, { type: 'connection', connection });
  }

  pushOwner(key, owner) {
    if (!this.owners.has(key)) this.owners.set(key, []);
    this.owners.get(key).push(owner);
  }

  detailId(key) { return `proof-detail-${this.detailIndex.get(key)}`; }

  nodeLabel(id) { const node = this.model.nodes.get(id); return node ? node.label : id; }

  hypothesisLink(relation, text) {
    return `<a class="proof-jump" href="#${esc(this.detailId(relation.detail_key))}" data-jump-detail="${esc(relation.detail_key)}" data-reader-edge="${esc(relation.proof_connection_id || relation.id)}" data-jump-hypothesis="${esc(relation.id)}">${text}</a>`;
  }

  hypothesisContexts(key) {
    const relations = this.model.hypothesisList.filter(relation => relation.detail_key === key || (relation.proof_connection_id && this.model.connections.get(relation.proof_connection_id)?.detail_key === key));
    if (!relations.length) return '';
    return `<section class="proof-hypothesis-contexts"><h4>Recorded hypotheses and setup</h4><p class="proof-muted">These are conditions of the recorded claim, not separately examined proof applications.</p><ul class="proof-plain-list">${relations.map(relation => `<li data-hypothesis-context="${esc(relation.id)}" data-hypothesis-premise="${esc(refKey(relation.premise_ref))}" data-hypothesis-target="${esc(refKey(relation.target_ref))}" data-hypothesis-spec="${esc(refKey(relation.spec_ref))}" data-hypothesis-statement="${esc(refKey(relation.statement_ref))}" data-hypothesis-scopes="${esc(JSON.stringify(relation.scope_refs.map(refKey)))}" data-hypothesis-proof-connection="${esc(relation.proof_connection_id || '')}">${this.humanLink(relation.premise_ref)}: ${relation.kind === 'setup' ? 'declared setup' : 'hypothesis'} of ${this.humanLink(relation.target_ref)}. ${relation.scope_refs.map(ref => this.humanLink(ref, 'Recorded scope')).join(', ')}.</li>`).join('')}</ul></section>`;
  }

  jump(key, text, options = {}) {
    const attrs = [`class="proof-jump${options.className ? ` ${options.className}` : ''}"`, `href="#${esc(this.detailId(key))}"`, `data-jump-detail="${esc(key)}"`];
    if (options.section) attrs.push(`data-jump-section="${esc(options.section)}"`);
    if (options.record) attrs.push(`data-jump-record="${esc(options.record)}"`);
    return `<a ${attrs.join(' ')}>${text}</a>`;
  }

  // Result and evidence links share the same pinned navigation index.
  recordLink(ref, pinned) {
    return this.humanLink(ref);
  }

  idLink(id, collection) {
    return this.recordLink({ collection, id }, false);
  }

  readerRecord(ref) { return ref ? this.model.records.get(refKey(ref)) : null; }

  humanLabel(ref, depth = 0) {
    if (!ref || depth > 2) return 'Recorded evidence';
    if (isString(ref)) ref = {collection:'items',id:ref};
    const record = Number.isInteger(ref.version) ? this.readerRecord(ref) : this.model.recordsByLoose.get(looseKey(ref));
    if (!record) return this.content.title(ref);
    const body = record?.body || {};
    if (body.label) return body.label;
    if (ref.collection === 'groups') return `${humanize(body.kind || 'recorded')} inference${isObject(body.conclusion) ? ` for ${this.humanLabel(body.conclusion, depth + 1)}` : ''}`;
    if (ref.collection === 'uses') return `${this.humanLabel(body.from, depth + 1)} applied to ${this.humanLabel(body.to, depth + 1)}`;
    return this.content.title(record || ref);
  }

  humanLabelHtml(ref, depth = 0) {
    if (!ref || depth > 2) return 'Recorded evidence';
    if (isString(ref)) ref = {collection:'items',id:ref};
    const record = Number.isInteger(ref.version) ? this.readerRecord(ref) : this.model.recordsByLoose.get(looseKey(ref));
    if (!record) return esc(this.content.title(ref));
    const body = record?.body || {}, fragment = record && this.model.fragments.get(refKey(record.ref))?.label_html;
    if (body.label) return fragment === undefined ? esc(body.label) : prepareLabelFragment(fragment);
    if (ref.collection === 'groups') return `${esc(humanize(body.kind || 'recorded'))} inference${isObject(body.conclusion) ? ` for ${this.humanLabelHtml(body.conclusion, depth + 1)}` : ''}`;
    if (ref.collection === 'uses') return `${this.humanLabelHtml(body.from, depth + 1)} applied to ${this.humanLabelHtml(body.to, depth + 1)}`;
    return esc(this.humanLabel(ref, depth));
  }

  humanLink(ref, label) {
    if (!ref) return '<span class="proof-muted">Unrecorded context</span>';
    if (isString(ref)) ref = {collection:'items',id:ref};
    const record = Number.isInteger(ref.version) ? this.readerRecord(ref) : this.model.recordsByLoose.get(looseKey(ref));
    const text = label === undefined ? this.humanLabelHtml(ref) : esc(label);
    const location = record ? this.locationsByPinned.get(refKey(record.ref)) : Number.isInteger(ref.version) ? null : this.locationsByLoose.get(looseKey(ref));
    return location ? this.jump(location.detail_key, text, {section:this.nodeDetailsByPinned.has(refKey(location.ref)) ? null : location.section_key, record:refKey(location.ref)}) : text;
  }

  // These are selected, pinned source fields, separate from canonical record slots.
  // Every scalar retains its context so publication checks cannot accept a hidden copy.
  readerField(detailKey, context, ref, field) {
    const record = this.readerRecord(ref);
    if (!record) return '';
    const value = record.body[field];
    const fragment = (this.model.fragments.get(refKey(ref)) || {})[FRAGMENT_FIELDS[field]];
    const render = (entry, path, rendered) => {
      if (entry === null || entry === undefined || entry === '') return '';
      if (Array.isArray(entry)) return entry.map((part, index) => render(part, `${path}.${index}`, Array.isArray(rendered) ? rendered[index] : undefined)).join('');
      if (isObject(entry)) {
        if (Object.hasOwn(entry, 'text') && ['statement', 'needed_form'].includes(field)) return (entry.form === 'synopsis' ? '<p class="proof-reader-label">Saved synopsis</p>' : '') + render(entry.text, `${path}.text`, rendered);
        return `<dl class="proof-reader-values">${Object.entries(entry).map(([name, part]) => `<dt>${esc(humanize(name))}</dt><dd>${render(part, `${path}.${name}`)}</dd>`).join('')}</dl>`;
      }
      const tag = ['label', 'origin', 'lifecycle', 'kind', 'category', 'state'].includes(field) ? 'span' : 'div';
      return `<${tag} class="proof-reader-value${tag === 'div' ? ' proof-fragment' : ''}" data-reader-detail="${esc(detailKey)}" data-reader-context="${esc(context)}" data-reader-ref="${esc(refKey(ref))}" data-reader-field="${esc(path)}">${rendered !== undefined ? (field === 'label' ? prepareLabelFragment(rendered) : prepareFragment(rendered)) : esc(String(entry))}</${tag}>`;
    };
    return render(value, field, fragment);
  }

  readerAssessment(detailKey, context, assessment) {
    return `<div data-reader-detail="${esc(detailKey)}" data-reader-assessment="${esc(context)}">${this.assessmentBlock(assessment, {compact:true})}</div>`;
  }

  readerSupport(detailKey, context, explanation) {
    if (!explanation) return '';
    const link = (role, ref, label) => `<span data-reader-support-link="${role}" data-reader-support-ref="${esc(refKey(ref))}">${this.humanLink(ref, label)}</span>`;
    const application = explanation.path_refs.find(ref => ref.collection === 'uses');
    const contexts = [['source_scope', 'Supplier context'], ['active_scope', 'Active context'],
      ['blocking_scope', 'Required context'], ['group_scope', 'Inference context']].filter(([field]) => Object.hasOwn(explanation, field + '_ref'));
    return `<div class="proof-reader-notice" data-reader-detail="${esc(detailKey)}" data-reader-support="${esc(context)}" data-reader-support-code="${esc(explanation.code)}" data-reader-support-availability="${esc(explanation.availability)}">
<p class="proof-reader-label">One blocking requirement</p>
<p>${explanation.target_ref ? `${link('target', explanation.target_ref)}: ` : ''}<span data-reader-support-message>${esc(explanation.message)}</span></p>
${application ? `<p>${link('application', application, 'Inspect blocked application')}</p>` : ''}
${contexts.length ? `<p>${contexts.map(([field, label]) => explanation[field + '_ref'] ? link(field, explanation[field + '_ref'], label) : `${label}: no named scope`).join(' · ')}</p>` : ''}
</div>`;
  }

  readerSources(ref, role) {
    const body = this.readerRecord(ref)?.body || {};
    const ids = [...new Set([...(body.evidence_refs || []).map(entry => isString(entry) ? entry : entry.id), ...(body.passages || []).filter(p => isString(p) || !role || p.role === role || p.role === 'evidence').map(p => isString(p) ? p : p.anchor_id)].filter(Boolean))];
    return ids.length ? sourceDisclosure({title:role === 'proof' ? 'Proof sources and locators' : 'Sources and locators',bodyHtml:`<p class="proof-reader-sources">${ids.map((id, i) => this.humanLink({collection:'anchors', id}, `${role === 'proof' ? 'Proof source' : 'Source'}${ids.length > 1 ? ` ${i + 1}` : ''}`)).join(' · ')}</p>`}) : '';
  }

  readerNamedLink(key, context, ref) {
    const text = this.readerField(key, context, ref, 'label');
    if (!text) return this.humanLink(ref);
    const location = this.locationsByPinned.get(refKey(ref));
    return location ? this.jump(location.detail_key, text, this.nodeDetailsByPinned.has(refKey(ref)) ? {} : {section:location.section_key, record:refKey(ref)}) : text;
  }

  readerPremise(key, context, ref, options = {}) {
    const body = this.readerRecord(ref)?.body || {};
    const kind = body.kind || (ref.collection === 'parts' ? this.model.recordsByLoose.get(`items:${body.item_id}`)?.body?.kind : null);
    const definition = kind === 'definition', identity = refKey(ref);
    const repeated = this.readerSeenPremises?.has(identity);
    const folded = definition || options.fold || repeated;
    // Only an actually visible statement can stand in for a later occurrence.
    if (options.visible && !folded) this.readerSeenPremises?.add(identity);
    const content = `${this.readerField(key, context, ref, 'statement')}${this.readerSources(ref, 'statement')}<p>${this.humanLink(ref, 'Inspect premise')}</p>`;
    const marker = definition ? 'data-reader-definition' : repeated ? 'data-reader-repeated-premise' : 'data-reader-premise-details';
    return `<div class="proof-reader-premise"><h6><span class="proof-premise-role">${definition ? 'Declared setup' : 'Assumed'}</span> ${this.readerNamedLink(key, context, ref)}</h6>${folded ? `<details class="proof-reader-context" ${marker}="${esc(identity)}"><summary>${definition ? 'Definition and source' : repeated ? 'Premise already shown above' : 'Premise statement and source'}</summary>${content}</details>` : content}</div>`;
  }

  readerScopes(key, context, chain, options = {}) {
    return (chain || []).map((entry, index) => {
      const at = `${context}:scope:${index}`;
      const body = this.readerRecord(entry.scope_ref)?.body || {};
      const identity = JSON.stringify([entry.scope_ref, entry.assumption_refs]);
      const repeated = options.deduplicate && this.readerSeenScopes?.has(identity);
      if (options.seed) this.readerSeenScopes?.add(identity);
      const content = `<div class="proof-reader-scope" data-reader-scope="${esc(at)}" data-reader-ref="${esc(refKey(entry.scope_ref))}">
<p class="proof-muted">${index ? 'Inherited setup' : 'Recorded setup'} · ${this.humanLink(entry.scope_ref, 'Context evidence')}</p>
${body.conditions?.length ? `<p class="proof-reader-label">Conditions</p>${this.readerField(key, at, entry.scope_ref, 'conditions')}` : ''}
${(entry.assumption_refs || []).map((ref, ai) => this.readerPremise(key, `${at}:assumption:${ai}`, ref, {visible:options.seed && !repeated,fold:options.foldPremises})).join('')}
${body.binders?.length ? `<p class="proof-reader-label">Variables and quantifiers</p>${this.readerField(key, at, entry.scope_ref, 'binders')}` : ''}
${!entry.assumption_refs?.length && !body.binders?.length && !body.conditions?.length ? '<p class="proof-muted">No assumptions, variables or conditions recorded in this context.</p>' : ''}
${this.readerSources(entry.scope_ref)}
</div>`;
      return repeated ? `<details class="proof-reader-context" data-reader-repeated-scope="${esc(refKey(entry.scope_ref))}"><summary>Shared setup and premise details</summary>${content}</details>` : content;
    }).join('');
  }

  assessmentBlock(assessment, options = {}) {
    const display = reviewDisplay(assessment);
    const parts = [`<div class="proof-assessment s-${esc(display.color)}" data-review-status="${esc(display.status)}">`];
    parts.push(`<p class="proof-assessment-head">${stateBadge(display.color, display.label)} <strong class="proof-assessment-label">${esc(assessment.label)}</strong></p>`);
    if (display.explanation && display.explanation !== assessment.explanation) parts.push(`<p class="proof-review-explanation">${esc(display.explanation)}</p>`);
    if (assessment.explanation) parts.push(`<p class="proof-assessment-text">${esc(assessment.explanation)}</p>`);
    if (assessment.availability) parts.push(`<p class="proof-assessment-meta proof-availability">Exact target support: <strong>${esc(assessment.availability)}</strong></p>`);
    if (assessment.local_label) parts.push(`<p class="proof-assessment-meta proof-local-outcome">Recorded local work: <strong>${esc(assessment.local_label)}</strong></p>`);
    parts.push(`<p class="proof-assessment-meta">${reviewNote(assessment.independent_review)}</p>`);
    if (!options.compact) {
      if (assessment.check_refs.length) parts.push(`<p class="proof-assessment-meta">Examinations: ${assessment.check_refs.map((ref) => this.humanLink(ref)).join(', ')}</p>`);
      if (assessment.finding_refs.length) parts.push(`<p class="proof-assessment-meta">Findings: ${assessment.finding_refs.map((id) => this.idLink(id, 'findings')).join(', ')}</p>`);
      if (assessment.missing_obligation_ids.length) parts.push('<p class="proof-assessment-meta">Current examination is incomplete for this material.</p>');
    }
    parts.push('</div>');
    return parts.join('');
  }

  findingCard(key, index, ref) {
    const record = this.readerRecord(ref), body = record?.body;
    if (!body) return '<p class="proof-muted">Saved finding unavailable.</p>';
    const display = reviewDisplay({review_display:this.model.projection.finding_displays?.[ref.id]});
    const context = `finding:${index}`;
    const prose = this.readerField(key, context, ref, 'description') + this.readerField(key, context, ref, 'impact_reason');
    const foldProse = (key === 'summary' && !body.severity) || display.status === 'historical';
    const links = (body.check_refs || []).map(check => this.humanLink(check, 'Examination reasoning')).join(' · ');
    return `<section class="proof-issue-card s-${esc(display.color)}" data-issue-ref="${esc(ref.id)}" data-review-status="${esc(display.status)}">
<header class="proof-issue-head">${stateBadge(display.color, display.label)}${body.target ? `<strong>${this.humanLink(body.target)}</strong>` : ''}</header>
${display.explanation && !['severe','moderate','minor'].includes(display.status) ? `<p class="proof-issue-qualification">${esc(display.explanation)}</p>` : ''}
${foldProse ? '' : prose}
${this.readerSources(ref)}
<details class="proof-reader-context"><summary>Assessment details${foldProse ? ' and saved finding' : ''}</summary>
${foldProse ? prose : ''}<p>${this.readerField(key, context, ref, 'category')} · ${esc(humanize(body.lifecycle))}</p>
${body.resolution ? this.readerField(key, context, ref, 'resolution') : ''}
${links ? `<p>${links}</p>` : ''}<p>${this.humanLink(ref, 'Finding and supporting evidence')}</p></details>
</section>`;
  }

  // ----- summary -----------------------------------------------------------

  factualHtml() {
    const factual = this.model.summary.factual;
    if (!factual) return '<div class="proof-card"><h3>Scientific status</h3><p class="proof-muted">Read each saved assessment for its support conditions and review limits.</p></div>';
    const support = factual.statement_support, independent = factual.independent_review;
    const fact = (name, value) => `<span data-proof-fact="${name}">${esc(String(value))}</span>`;
    const effectiveOutcomes = factual.work.current_effective_outcomes;
    const outcomeCounts = effectiveOutcomes ?? factual.work.current_primary_outcomes;
    const outcomes = ['supported', 'gap', 'refuted', 'inconclusive'].map(outcome =>
      outcomeCounts[outcome] > 0 ? (effectiveOutcomes ? `${outcomeCounts[outcome]} ${outcome}` : outcome) : null).filter(Boolean);
    const outcomeLabel = effectiveOutcomes ? 'Current examination outcomes' : 'Current initial assessment outcomes';
    const outcomeEmpty = effectiveOutcomes ? 'No completed current mathematical outcome is recorded.' : 'No completed current initial mathematical outcome is recorded.';
    const findingCounts = this.model.summary.findings.current_by_review_status;
    const findingBadges = findingCounts === undefined ? [] : FINDING_STATUSES.filter(status => findingCounts[status] > 0)
      .map(status => `<span data-proof-finding-status="${status}">${stateBadge(DISPLAY[status][0], `${findingCounts[status]} ${status}`)}</span>`);
    const findingSummary = findingCounts === undefined ? '' : `<p data-proof-fact="current_findings">${findingBadges.length ? `Current findings: ${findingBadges.join(', ')}.` : 'No current local findings recorded.'}</p>
<p data-proof-fact="finding_count_basis">Examination outcomes count complete required mathematical examinations. Current findings describe separately recorded local concerns and may have different totals.</p>`;
    const unresolved = support.unresolved.map((row, index) => {
      const premise = ['assumption', 'definition'].includes(row.kind) ? ` (declared ${row.kind}; scope-dependent premise)` : '';
      return `<li>${fact(`unresolved.${index}`, `${row.label}: ${row.availability}${premise}`)}</li>`;
    });
    const sourceLimits = factual.source_limits.map((row, index) => `<li>${fact(`source_limits.${index}`, `${row.source_path || row.label}: ${row.description}`)}</li>`);
    const external = factual.unresolved_external_sources.map((row, index) => `<li>${fact(`external.${index}`, `${row.label}: ${row.availability}`)}</li>`);
    return `<div class="proof-card" data-proof-factual>
<h3>Current scientific status</h3>
<p data-proof-fact="primary_outcomes">${outcomes.length ? `${outcomeLabel}: ${outcomes.join(', ')}.` : outcomeEmpty} Completion of the examination does not establish that every statement is supported.${effectiveOutcomes ? ' Pending, stale or disputed integrations retain initial opinions.' : ''}</p>
${findingSummary}
<p data-proof-fact="statement_support">Read each result and application for its exact support conditions.</p>
${unresolved.length ? `<details><summary>Conditional or unavailable statements</summary><ul>${unresolved.join('')}</ul><p>Declared assumptions and definitions can be available as premises in an explicitly authorizing scope. Their status here does not by itself indicate a proof gap; availability must be checked at each use.</p></details>` : ''}
<p data-proof-fact="independent_review">${esc(independent.explanation ?? `Independent review: ${REVIEW_LABELS[independent.state]}.`)}</p>
${independent.qualification_limitations.length ? `<ul>${independent.qualification_limitations.map((note, index) => `<li>${fact(`qualification.${index}`, note)}</li>`).join('')}</ul>` : ''}
${sourceLimits.length ? `<h4>Recorded source limitations</h4><ul>${sourceLimits.join('')}</ul>` : ''}
${external.length ? `<h4>Unresolved external suppliers</h4><ul>${external.join('')}</ul>` : ''}
</div>`;
  }

  summaryHtml() {
    const { model } = this;
    const { summary, projection } = model;
    const progress = summary.progress;
    const findingItems = summary.findings.refs.map((id, index) => {
      const record = model.recordsByLoose.get(`findings:${id}`);
      const body = record ? record.body : null;
      return `<li data-proof-finding="${esc(id)}">${body ? this.findingCard('summary', index, record.ref) : '<p>Saved finding unavailable.</p>'}</li>`;
    });
    const limitItems = summary.source_limits.map((id, index) => {
      const record = model.recordsByLoose.get(`source_issues:${id}`);
      const body = record ? record.body : null;
      const meta = body ? [body.category, body.lifecycle].filter(isString).map((value) => `<span class="proof-pill">${esc(humanize(value))}</span>`).join(' ') : '';
      const text = body ? this.readerField('summary', `source_limit:${index}`, record.ref, 'description') : '';
      return `<li data-proof-source-limit="${esc(id)}">${this.humanLink({collection:'source_issues', id}, 'Source limitation')} ${meta} ${text}</li>`;
    });
    const scope = summary.scope;
    const exclusionItems = summary.factual ? summary.factual.scope.exclusions.map((entry, index) =>
      `<li data-proof-fact="exclusion.${index}"><strong>${esc(entry.label)}</strong>: ${esc(entry.reason)} Consequence: ${esc(entry.consequence)}</li>`) :
      scope.exclusions.map(entry => {
        if (isString(entry)) return `<li class="proof-text">${esc(entry)}</li>`;
        if (isObject(entry) && isString(entry.collection) && isString(entry.id)) return `<li>${this.humanLink(entry)}</li>`;
        const context = [entry?.target ? this.humanLink(entry.target) : '', ...(entry?.source_anchor_ids || []).map(id => this.humanLink({collection:'anchors',id}))].filter(Boolean).join('; ');
        const prose = ['label','description','reason','consequence'].filter(field => isString(entry?.[field]) && entry[field]).map(field => `${field === 'consequence' ? 'Consequence: ' : ''}${esc(entry[field])}`).join(' ');
        return `<li>${context}${context && prose ? ': ' : ''}${prose || (!context ? 'This saved exclusion has no compatible description in this view.' : '')}</li>`;
      });
    const overviewScope = summary.overview_scope;
    const overviewBoundaries = overviewScope ? `<div data-proof-overview-scope>
<h4>Original overview boundaries</h4>
${overviewScope.text ? `<p class="proof-text">${esc(overviewScope.text)}</p>` : ''}
${overviewScope.exclusions.length ? `<h4>Original overview exclusions</h4><ul class="proof-plain-list">${overviewScope.exclusions.map((entry) => `<li class="proof-text">${esc(entry)}</li>`).join('')}</ul>` : ''}
</div>` : '';
    return `<section id="proof-summary" class="proof-panel" aria-labelledby="proof-summary-heading">
<h2 id="proof-summary-heading">Audit summary</h2>
<div class="proof-summary-grid">
<div class="proof-card">
<h3>Examination status</h3>
<p class="proof-process ${progress.process_complete ? 'is-complete' : 'is-incomplete'}" data-proof-process-complete="${progress.process_complete ? 'true' : 'false'}">${progress.process_complete ? 'Registered examinations complete.' : 'Registered examinations incomplete.'} Mathematical support is stated separately.${model.build.kind === 'working' ? ' This working report does not establish completion of the promised audit scope.' : ''}</p>
</div>
${this.factualHtml()}
<div class="proof-card">
<h3>Findings</h3>
${findingItems.length ? `<ul class="proof-finding-list">${findingItems.join('')}</ul>` : '<p class="proof-muted">No findings listed.</p>'}
<h3>Source limits</h3>
${limitItems.length ? `<ul class="proof-finding-list">${limitItems.join('')}</ul>` : '<p class="proof-muted">No open source issue records listed.</p>'}
</div>
<div class="proof-card">
<h3>Scope</h3>
${summary.factual?.scope.explanation ? `<p data-proof-fact="scope_explanation">${esc(summary.factual.scope.explanation)}</p>` : ''}
<dl class="proof-kv">
<dt>Mode</dt><dd data-proof-scope-mode>${esc(scope.mode)}</dd>
<dt>${scope.mode === 'full' ? 'Explicit targets' : 'Audit targets'}</dt><dd data-proof-scope-targets>${scope.target_refs.length ? scope.target_refs.map((ref) => `<span data-proof-scope-target="${esc(looseKey(ref))}">${this.humanLink(ref, this.humanLabel(ref))}</span>`).join(', ') : `<span class="proof-muted">${projection.audit_id === null ? 'Recorded items; no audit selected' : scope.mode === 'full' ? 'No explicit targets recorded' : 'No explicit audit targets recorded'}</span>`}</dd>
<dt>Audit exclusions</dt><dd data-proof-scope-exclusions>${exclusionItems.length ? `<ul class="proof-plain-list">${exclusionItems.join('')}</ul>` : '<span class="proof-muted">none recorded</span>'}</dd>
</dl>
${overviewBoundaries}
</div>
</div>
</section>`;
  }

  // ----- graph (dag) -------------------------------------------------------

  svgHtml() {
    const { model, graph } = this;
    const badges = [];
    const edges = model.graphConnectionList.map((connection, edgeIndex) => {
      const points = edgePoints(connection, graph);
      if (model.hypotheses.has(connection.id)) {
        const description = `${this.nodeLabel(connection.from)} to ${this.nodeLabel(connection.to)}. Recorded ${connection.kind === 'setup' ? 'setup' : 'hypothesis'}. Select for the result's conditions.`;
        return `<path data-edge-id="${esc(connection.id)}" data-edge-key="${edgeIndex}" data-edge-label="${esc(description)}" data-edge-from="${esc(connection.from)}" data-edge-to="${esc(connection.to)}" data-edge-state="hypothesis" data-edge-kind="${esc(connection.kind)}" data-detail-key="${esc(connection.detail_key)}" class="proof-edge proof-hypothesis" d="${roundedPath(points)}" marker-end="url(#proof-hypothesis-arrow)"><title>${esc(description)}</title></path>`;
      }
      const state = displayState(connection.assessment);
      const d = roundedPath(points);
      const labels = [];
      if (connection.primary_use_ids.length > 1) labels.push(`${connection.primary_use_ids.length} applications`);
      const description = `${this.nodeLabel(connection.from)} to ${this.nodeLabel(connection.to)}. ${reviewDisplay(connection.assessment).label}: ${connection.assessment.label}.${labels.length ? ` ${labels.join(', ')}.` : ''}`;
      if (labels.length) badges.push({ connection, description: `${description} Select for details.`, labels, points });
      return `<path data-edge-id="${esc(connection.id)}" data-edge-key="${edgeIndex}" data-edge-label="${esc(description)}" data-edge-from="${esc(connection.from)}" data-edge-to="${esc(connection.to)}" data-edge-state="${esc(state)}" data-detail-key="${esc(connection.detail_key)}" class="proof-edge s-${esc(state)}" d="${d}" marker-end="url(#proof-arrow-${esc(state)})"><title>${esc(description)}</title></path>`;
    });
    const ordered = [...graph.nodes.values()].sort((a, b) => a.rank - b.rank || a.y - b.y || a.order - b.order);
    const nodes = ordered.map((node) => {
      const source = node.source;
      const state = displayState(source.assessment);
      const review = source.assessment.independent_review;
      const cx = node.x + BOX.w / 2;
      const caption = captionLines(source.caption);
      const labelSize = Math.max(12, Math.min(14, 150 / Math.max(1, textUnits(source.label)) / 0.61));
      const squeeze = textUnits(source.label) * labelSize * 0.61 > 154 ? ' textLength="154" lengthAdjust="spacingAndGlyphs"' : '';
      const aria = `${source.label}. ${KINDS[source.kind][0]}. ${reviewDisplay(source.assessment).label}: ${source.assessment.label}. Independent review ${REVIEW_LABELS[review]}. Press Enter for details.`;
      const tooltip = `${source.label}${source.caption ? `: ${source.caption}` : ''} (${KINDS[source.kind][0]}, ${reviewDisplay(source.assessment).label.toLowerCase()})`;
      const reviewMark = review === 'not_required' ? '' : `<g class="proof-node-review r-${esc(review)}" aria-hidden="true"><rect x="${node.x + BOX.w - 24}" y="${node.y + BOX.h - 8}" width="26" height="14" rx="7"/><text x="${node.x + BOX.w - 11}" y="${node.y + BOX.h + 2.5}" text-anchor="middle" font-size="8.5">IR</text></g>`;
      return `<g data-node-id="${esc(source.id)}" data-node-label="${esc(source.label)}" data-node-sublabel="${esc(source.caption)}" data-node-state="${esc(state)}" data-node-kind="${esc(source.kind)}" data-detail-key="${esc(source.detail_key)}" data-node-rank="${node.rank}" data-node-x="${node.x}" data-node-y="${node.y}" tabindex="0" role="button" aria-pressed="false" aria-label="${esc(aria)}" class="proof-node k-${esc(source.kind)} s-${esc(state)}">
<title>${esc(tooltip)}</title>
<rect class="proof-node-ring" x="${node.x - 3}" y="${node.y - 3}" width="${BOX.w + 6}" height="${BOX.h + 6}" rx="9"/>
<rect class="proof-node-box" x="${node.x}" y="${node.y}" width="${BOX.w}" height="${BOX.h}" rx="6"/>
<text class="proof-node-label" data-node-label="${esc(source.label)}" x="${cx}" y="${node.y + 23}" font-size="${fmt(labelSize)}" font-weight="600" text-anchor="middle"${squeeze}>${esc(source.label)}</text>
${caption.map((line, i) => `<text class="proof-node-caption" data-detail="context" x="${cx}" y="${node.y + 40 + 13 * i}" font-size="11" text-anchor="middle">${esc(line)}</text>`).join('\n')}
<g class="proof-node-state" aria-hidden="true"><circle cx="${node.x + BOX.w - 2}" cy="${node.y + 2}" r="8.5"/><text x="${node.x + BOX.w - 2}" y="${node.y + 5.5}" text-anchor="middle" font-size="10" font-weight="700">${esc(STATE_GLYPHS[state])}</text></g>
${reviewMark}
</g>`;
    });
    const badgeSvg = this.badgesHtml(badges);
    const components = graph.components.length > 1 ? graph.components.map((component) => {
      const ends = component.members.filter((node) => !graph.outgoing.get(node.id).length).map((node) => node.source.label);
      const title = component.members.length === 1 ? 'Unconnected result' :
        `Linked argument: ${(ends.length ? ends : component.members.map((node) => node.source.label)).join(', ')}`;
      const limit = Math.floor((component.width - 2 * BOX.margin) / (11 * 0.61));
      let label = title;
      if (textUnits(label) > limit) {
        while (textUnits(label) > limit - 1) label = [...label].slice(0, -1).join('');
        label += '…';
      }
      return `<g class="proof-component" aria-hidden="true"><title>${esc(title)}</title><path d="M ${component.left + 22} ${component.top + 16} H ${component.left + component.width - 22}"/><text x="${component.left + BOX.margin}" y="${component.top + 9}" font-size="11">${esc(label)}</text></g>`;
    }).join('\n') : '';
    const markers = DISPLAY_STATES.map((state) => `<marker id="proof-arrow-${state}" markerWidth="8" markerHeight="6" refX="7.2" refY="3" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 L8 3 L0 6 Z" class="proof-arrowhead s-${state}"/></marker>`).join('') + (model.hypothesisList.length ? '<marker id="proof-hypothesis-arrow" markerWidth="9" markerHeight="8" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M1 1 L8 4 L1 7" class="proof-hypothesis-arrowhead"/></marker>' : '');
    return `<svg class="proof-svg proof-audit" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${graph.width} ${graph.height}" width="${graph.width}" height="${graph.height}" role="group" aria-labelledby="proof-graph-heading" aria-describedby="proof-graph-desc">
<defs>${markers}<pattern id="proof-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0 L0 0 0 40" class="proof-grid-line" stroke-width="0.5"/></pattern></defs>
<rect class="proof-grid-fill" width="100%" height="100%" fill="url(#proof-grid)"/>
${components}
${edges.join('\n')}
${badgeSvg}
${nodes.join('\n')}
</svg>`;
  }

  badgesHtml(badges) {
    const { graph } = this;
    const occupied = [...graph.nodes.values()].map((node) => ({ x: node.x - 6, y: node.y - 6, w: BOX.w + 12, h: BOX.h + 12 }));
    if (graph.components.length > 1) graph.components.forEach((component) =>
      occupied.push({x:component.left + 22, y:component.top - 3, w:component.width - 44, h:26}));
    const intersects = (a, b) => a.x < b.x + b.w + 3 && a.x + a.w + 3 > b.x && a.y < b.y + b.h + 3 && a.y + a.h + 3 > b.y;
    return badges.map(({ connection, description, labels, points }) => {
      const w = Math.max(...labels.map((label) => textUnits(label))) * 5.7 + 12, h = labels.length * 14 + 6;
      const candidates = [];
      for (let i = 1; i < points.length; i += 1) {
        const a = points[i - 1], b = points[i], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (length < 8) continue;
        for (const fraction of [0.5, 0.25, 0.75, 0.1, 0.9]) {
          const anchor = [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction];
          for (const offset of [0, -h - 8, h + 8, -2 * h - 16, 2 * h + 16, -3 * h - 24, 3 * h + 24]) {
            const x = anchor[0], y = anchor[1] + offset;
            const rect = { x: x - w / 2, y: y - h / 2, w, h };
            if (rect.x < 8 || rect.x + w > graph.width - 8 || rect.y < 8 || rect.y + h > graph.height - 8) continue;
            candidates.push({ x, y, rect, anchor, cost: Math.abs(offset) + Math.abs(fraction - 0.5) * 18 + (b[1] === a[1] ? 0 : 3) });
          }
        }
      }
      candidates.sort((a, b) => a.cost - b.cost);
      let placed = candidates.find((candidate) => !occupied.some((entry) => intersects(candidate.rect, entry)));
      if (!placed) {
        const anchor = points[Math.floor(points.length / 2)];
        for (let y = 18 + h / 2; !placed && y < graph.height - h / 2; y += h + 7) {
          for (let x = 8 + w / 2; !placed && x < graph.width - w / 2; x += w + 8) {
            const rect = { x: x - w / 2, y: y - h / 2, w, h };
            if (!occupied.some((entry) => intersects(rect, entry))) placed = { x, y, rect, anchor };
          }
        }
      }
      if (!placed) {
        const anchor = points[Math.floor(points.length / 2)];
        const x = Math.min(graph.width - w / 2 - 8, Math.max(w / 2 + 8, anchor[0])), y = graph.height + h / 2;
        placed = { x, y, anchor, rect: { x: x - w / 2, y: y - h / 2, w, h } };
        graph.height += h + 12;
      }
      occupied.push(placed.rect);
      const { x, y, anchor } = placed;
      const leader = Math.hypot(x - anchor[0], y - anchor[1]) > 3;
      const state = displayState(connection.assessment);
      return `${leader ? `<g aria-hidden="true" class="proof-badge-decoration"><path class="proof-badge-leader" d="M ${fmt(anchor[0])} ${fmt(anchor[1])} L ${fmt(x)} ${fmt(y)}"/><circle class="proof-badge-anchor" cx="${fmt(anchor[0])}" cy="${fmt(anchor[1])}" r="2"/></g>` : ''}<g class="proof-edge-badge s-${esc(state)}" data-edge-badge="${esc(connection.id)}" data-detail-key="${esc(connection.detail_key)}" tabindex="0" role="button" aria-label="${esc(description)}"><title>${esc(description)}</title><rect x="${fmt(x - w / 2)}" y="${fmt(y - h / 2)}" width="${fmt(w)}" height="${h}" rx="4"/>${labels.map((label, i) => `<text x="${fmt(x)}" y="${fmt(y - (labels.length - 1) * 7 + i * 14 + 3)}" text-anchor="middle">${esc(label)}</text>`).join('')}</g>`;
    }).join('\n');
  }

  legendHtml() {
    const kinds = Object.entries(KINDS).map(([kind, [name]]) => `<li class="k-${kind}"><span class="proof-legend-swatch proof-legend-kind"></span>${esc(name)}</li>`).join('');
    const states = DISPLAY_STATES.map(state => `<li>${stateBadge(state)}</li>`).join('');
    return `<div class="proof-legend">
<ul class="proof-legend-list" aria-label="Item kinds">${kinds}</ul>
<ul class="proof-legend-list" aria-label="Assessment states">${states}</ul>
${this.model.hypothesisList.length ? '<p class="proof-legend-note"><svg class="proof-hypothesis-sample" width="40" height="12" viewBox="0 0 40 12" aria-hidden="true"><path d="M1 6 H36 M29 2 L36 6 L29 10"/></svg> Hypothesis / setup: neutral open arrows show recorded conditions. They carry no proof verdict.</p>' : ''}
<p class="proof-legend-note">Boxes are tinted by item kind; the ring, corner glyph and edge colour show issue severity or the scoped check status. Gray means unresolved, unassessed or unrated, not a defect grade. An <span class="proof-ir-sample">IR</span> tag marks items whose independent review is pending, complete, disputed or compromised. Edge badges mark connections with several applications. Inference contexts remain in the connection details. Keyboard: Tab or arrow keys move between items, Enter opens details, Escape returns to the graph.</p>
</div>`;
  }

  // ----- index (fallback) --------------------------------------------------

  indexHtml() {
    const { model } = this;
    const incoming = new Map(model.nodeList.map((node) => [node.id, 0]));
    const outgoing = new Map(model.nodeList.map((node) => [node.id, 0]));
    for (const connection of model.graphConnectionList) {
      incoming.set(connection.to, incoming.get(connection.to) + 1);
      outgoing.set(connection.from, outgoing.get(connection.from) + 1);
    }
    const items = model.nodeList.map((node) => {
      const state = displayState(node.assessment);
      return `<article data-proof-index-item="${esc(node.id)}" data-node-state="${esc(state)}" data-node-kind="${esc(node.kind)}" class="proof-index-card k-${esc(node.kind)} s-${esc(state)}">
<header class="proof-index-head">${kindBadge(node.kind)} <h4>${this.jump(node.detail_key, esc(node.label))}</h4> ${stateBadge(state, `${reviewDisplay(node.assessment).label}: ${node.assessment.label}`)}</header>
${node.caption ? `<p class="proof-index-caption">${esc(node.caption)}</p>` : ''}
${node.assessment.explanation ? `<p class="proof-index-text">${esc(node.assessment.explanation)}</p>` : ''}
<p class="proof-index-meta">${reviewNote(node.assessment.independent_review)} <span class="proof-muted">${incoming.get(node.id)} incoming, ${outgoing.get(node.id)} outgoing</span></p>
</article>`;
    });
    const connections = model.connectionList.map((connection) => {
      const state = displayState(connection.assessment);
      const labels = [];
      if (connection.primary_use_ids.length) labels.push(`${connection.primary_use_ids.length} application${connection.primary_use_ids.length === 1 ? '' : 's'}`);
      if (connection.groups.length) labels.push(`${connection.groups.length} hidden-claim group${connection.groups.length === 1 ? '' : 's'}`);
      return `<article data-proof-index-connection="${esc(connection.id)}" data-edge-from="${esc(connection.from)}" data-edge-to="${esc(connection.to)}" data-edge-state="${esc(state)}" class="proof-index-card s-${esc(state)}">
<header class="proof-index-head"><h4>${this.jump(connection.detail_key, `${esc(this.nodeLabel(connection.from))} <span aria-hidden="true">→</span><span class="proof-visually-hidden"> to </span> ${esc(this.nodeLabel(connection.to))}`)}</h4> ${stateBadge(state, `${reviewDisplay(connection.assessment).label}: ${connection.assessment.label}`)}</header>
${connection.assessment.explanation ? `<p class="proof-index-text">${esc(connection.assessment.explanation)}</p>` : ''}
<p class="proof-index-meta">${labels.length ? `<span class="proof-muted">${esc(labels.join(', '))}</span>` : ''} ${reviewNote(connection.assessment.independent_review)}</p>
</article>`;
    });
    return `<section id="proof-major-index" class="proof-panel" aria-labelledby="proof-index-heading">
<div class="proof-panel-head"><h2 id="proof-index-heading">Major results index</h2><p class="proof-muted">The dependency graph is presented as an index for this build.</p></div>
<div class="proof-index-reasons"><h3>Why an index</h3>${this.model.layout.reasons.length ? `<ul class="proof-reasons">${this.model.layout.reasons.map((reason) => `<li>${esc(reason)}</li>`).join('')}</ul>` : '<p class="proof-muted">No reason was recorded.</p>'}</div>
<h3>Items (${items.length})</h3>
<div class="proof-index-list">${items.join('\n')}</div>
<h3>${model.hypothesisList.length ? 'Proof connections' : 'Connections'} (${connections.length})</h3>
<div class="proof-index-list">${connections.length ? connections.join('\n') : '<p class="proof-muted">No connections.</p>'}</div>
${model.hypothesisList.length ? `<h3>Hypotheses and setup (${model.hypothesisList.length})</h3><div class="proof-index-list">${model.hypothesisList.map(relation => `<article data-proof-index-hypothesis="${esc(relation.id)}" data-edge-from="${esc(relation.from)}" data-edge-to="${esc(relation.to)}" data-edge-state="hypothesis" data-edge-kind="${esc(relation.kind)}" data-detail-key="${esc(relation.detail_key)}" class="proof-index-card proof-hypothesis"><h4>${this.hypothesisLink(relation, `${esc(this.nodeLabel(relation.from))} → ${esc(this.nodeLabel(relation.to))}`)}</h4><p>${relation.kind === 'setup' ? 'Declared setup' : 'Recorded hypothesis'}. No separate proof verdict.</p></article>`).join('')}</div>` : ''}
</section>`;
  }

  // ----- details -----------------------------------------------------------

  detailsHtml() {
    const articles = [...this.model.details.entries()].map(([key, detail]) => this.detailHtml(key, detail));
    return `<section id="proof-details" class="proof-panel" aria-labelledby="proof-details-heading">
<div class="proof-panel-head"><h2 id="proof-details-heading">Details</h2><label class="proof-check"><input id="proof-show-all" type="checkbox"> Show all details</label></div>
<p id="proof-detail-empty" class="proof-muted">Select an item or connection above, or use the search, to open its detail here.</p>
<noscript><p class="proof-reader-notice">The saved overview text is readable below. Enable JavaScript to open the supporting source passages and assessment details.</p></noscript>
${articles.join('\n')}
<div id="proof-record-templates" hidden>${[...this.model.records.values()].map((record) => `<template data-record-template="${esc(refKey(record.ref))}">${this.recordHtml(record).replace('data-record-ref=', 'data-record-body=')}</template>`).join('\n')}</div>
</section>`;
  }

  detailHtml(key, detail) {
    const owners = this.owners.get(key) || [];
    const header = owners.length ? owners.map((owner) => (owner.type === 'node' ? this.nodeHeader(owner.node, detail.reader) : this.connectionHeader(owner.connection))).join('\n') : `<div class="proof-detail-owner"><h3 class="proof-detail-heading" tabindex="-1">${key.startsWith('audit:') ? 'Whole-audit examinations' : 'Audit evidence'}</h3></div>`;
    const sections = detail.sections.map((section) => this.sectionHtml(key, section)).join('\n');
    const outgoing = owners.filter(o => o.type === 'node').flatMap(o => this.model.connectionList.filter(c => c.from === o.node.id));
    return `<article class="proof-detail" data-reader-article="${esc(key)}" data-proof-detail="${esc(key)}" id="${esc(this.detailId(key))}">
<div class="proof-detail-top"><button type="button" class="proof-back">Back to ${this.graph ? 'graph' : 'index'}</button></div>
${header}
${this.hypothesisContexts(key)}
<details class="proof-disclosure proof-evidence" data-proof-evidence><summary>Detailed proof and audit evidence</summary>
<p class="proof-muted">The sections below are a stable evidence inventory, not a claimed proof sequence. Argument context and recorded final inferences are linked above.</p>
${sections}
<p>${this.jump(key, 'Return to result overview')}</p>
</details>
${outgoing.length ? `<details class="proof-disclosure"><summary>Used by (${outgoing.length})</summary><ul class="proof-plain-list">${outgoing.map(c => this.connectionLine(c)).join('')}</ul></details>` : ''}
</article>`;
  }

  connectionLine(connection) {
    const state = displayState(connection.assessment);
    return `<li>${this.jump(connection.detail_key, `${esc(this.nodeLabel(connection.from))} to ${esc(this.nodeLabel(connection.to))}`)} ${stateBadge(state, reviewDisplay(connection.assessment).label)}</li>`;
  }

  nodeHeader(node, reader) {
    reader = reader && refKey(reader.item_ref) === refKey(node.item_ref) ? reader : null;
    return `<div class="proof-detail-owner proof-owner-node k-${esc(node.kind)}" data-proof-owner-node="${esc(node.id)}">
<p class="proof-owner-kicker">${kindBadge(node.kind)}${this.graph ? ` <button type="button" class="proof-focus-node" data-focus-node="${esc(node.id)}">Show in graph</button>` : ''}</p>
<h3 class="proof-detail-heading" tabindex="-1">${this.humanLabelHtml(node.item_ref)}</h3>
${reader ? this.readerHtml(node, reader) : `<div data-reader-overview="${esc(node.detail_key)}"><p class="proof-reader-notice">This report supplies the saved statement and evidence without a separate contextual overview.</p>${this.assessmentBlock(node.assessment, {compact:true})}<h4>Saved statement or synopsis</h4>${this.readerField(node.detail_key, 'legacy', node.item_ref, 'statement')}<p class="proof-muted">This saved text is not asserted to be the exact examined target. Supporting evidence remains available below.</p></div>`}
</div>`;
  }

  readerHtml(node, reader) {
    const key = node.detail_key;
    this.readerSeenScopes = new Set();
    this.readerSeenPremises = new Set();
    const targets = reader.targets.map((target, index) => {
      const context = `target:${index}`, body = this.readerRecord(target.target_ref)?.body || {};
      const selected = this.readerRecord(target.statement_ref)?.body?.statement;
      const different = JSON.stringify(selected) !== JSON.stringify(body.statement);
      return `<section class="proof-reader-target" data-reader-target="${index}" data-reader-exact-state="${esc(target.exact_state)}" data-reader-target-ref="${esc(refKey(target.target_ref))}" data-reader-statement-ref="${esc(refKey(target.statement_ref))}" data-reader-spec-ref="${esc(target.spec_ref ? refKey(target.spec_ref) : '')}">
<h4>${index ? 'Audited part or target: ' : ''}${this.readerField(key, context, target.target_ref, 'label')}</h4>
<p class="proof-reader-label">${target.exact_state === 'registered' ? 'Exact audited statement' : 'Saved statement or synopsis'}</p>
${readingSection({role:'statement',bodyHtml:this.readerField(key, context, target.statement_ref, target.statement_field)})}
${selected === undefined || selected === null ? '<p class="proof-reader-notice">The pinned statement examined by this assessment is unavailable in this report.</p>' : ''}
${target.exact_state !== 'registered' ? `<p class="proof-reader-notice">A registered exact target is unavailable${target.exact_state === 'draft' ? '; the target specification is still a draft' : ''}.</p>` : ''}
${this.readerSources(target.spec_ref, 'statement') || this.readerSources(target.statement_ref, 'statement')}
${different ? `<details class="proof-reader-context"><summary>Current saved synopsis</summary>${this.readerField(key, `${context}:synopsis`, target.target_ref, 'statement')}</details>` : ''}
</section>`;
    }).join('');
    const strategy = this.readerRecord(reader.strategy_ref)?.body?.proof_idea;
    const strategyHtml = strategy ? `<section class="proof-reader-strategy proof-reading-section proof-logic-section"><h4>Proof idea</h4>${this.readerField(key, 'strategy', reader.strategy_ref, 'proof_idea')}${this.readerSources(reader.strategy_ref, 'proof')}<p class="proof-muted">Saved explanation; it supplies no additional proof support.</p></section>` : '';
    const findings = reader.finding_refs.map((ref, index) => this.findingCard(key, index, ref)).join('');
    const sourceLimits = reader.source_limit_refs.map((ref, index) => `<div class="proof-reader-issue"><p class="proof-reader-label">Source limitation${this.readerRecord(ref)?.body?.category ? ` · ${this.readerField(key, `source_limit:${index}`, ref, 'category')}` : ''}</p>${this.readerField(key, `source_limit:${index}`, ref, ref.collection === 'sources' ? 'limitation' : 'description')}<p>${this.humanLink(ref, 'Source limitation evidence')}</p></div>`).join('');
    const setup = reader.targets.map((target, index) => target.scope_chain.length ? `<section class="proof-reader-setup"><h5>Hypotheses and setup for ${this.humanLink(target.target_ref)}</h5>${this.readerScopes(key, `target:${index}`, target.scope_chain, {deduplicate:true,seed:true,foldPremises:true})}</section>` : '').join('');
    const applications = reader.applications.map((app, index) => ({app, index}));
    const associated = new Set();
    const routes = reader.arguments.map((argument, index) => {
      const body = this.readerRecord(argument.argument_ref)?.body || {};
      const rows = applications.filter(({app}) => app.argument_ref && refKey(app.argument_ref) === refKey(argument.argument_ref));
      rows.forEach(({index:appIndex}) => associated.add(appIndex));
      return this.readerArgument(key, reader, argument, index, rows, body);
    }).join('');
    const remaining = applications.filter(({index}) => !associated.has(index));
    const primaryTarget = reader.targets.findIndex(target => refKey(target.target_ref) === refKey(node.item_ref)
      && JSON.stringify(target.assessment) === JSON.stringify(node.assessment));
    return `<div class="proof-reader-overview" data-reader-overview="${esc(key)}">
${targets}
<section class="proof-reader-audit"><h4>Review</h4>${primaryTarget >= 0 ? this.readerAssessment(key, `target:${primaryTarget}`, node.assessment) + this.readerSupport(key, `target:${primaryTarget}`, reader.targets[primaryTarget].support_explanation) : this.assessmentBlock(node.assessment, {compact:true})}
${node.assessment.label === 'stale' && node.assessment.explanation === 'stale' ? '<p class="proof-muted proof-stale-hint">This status summary does not identify which change made the examination stale. The earlier opinion does not establish a completed current examination.</p>' : ''}
${reader.targets.map((target, index) => index === primaryTarget ? '' : `<div class="proof-reader-target-assessment"><p class="proof-reader-label">${this.humanLink(target.target_ref)}: target assessment</p>${this.readerAssessment(key, `target:${index}`, target.assessment)}${this.readerSupport(key, `target:${index}`, target.support_explanation)}</div>`).join('')}
${findings || sourceLimits ? `<h5>Material issues and limitations</h5>${findings}${sourceLimits}` : ''}</section>
${strategyHtml}
<section class="proof-reader-dependencies"><h4>Prerequisites</h4><p class="proof-muted">Recorded inputs and their applicable contexts; this list does not establish joint sufficiency.</p>
${setup}
${routes}
${reader.provenance_groups?.length ? `<details class="proof-reader-context"><summary>Recorded inference groups without an argument</summary><p class="proof-muted">These preserve recorded joint or case context. They do not establish a verified argument.</p>${reader.provenance_groups.map((group,index) => this.readerGroup(key, `provenance_group:${index}`, group)).join('')}</details>` : ''}
${remaining.length ? `<section class="proof-reader-route"><h5>Connections without a recorded argument association</h5>${this.readerApplications(key, remaining, reader.item_ref)}</section>` : ''}
${!reader.arguments.length && !applications.length ? '<p class="proof-muted">No supplier applications or proof routes were recorded.</p>' : ''}
</section></div>`;
  }

  readerGroup(key, context, group) {
    return `<section class="proof-reader-group"><h6>${this.readerField(key, context, group.group_ref, 'kind')} inference</h6>${this.readerField(key, context, group.group_ref, 'rationale')}${this.readerScopes(key, context, group.scope_chain)}${group.case_scopes.map((cs, ci) => `<section class="proof-reader-case"><h6>Case ${ci + 1} · ${this.humanLink(cs.scope_ref, 'Case context')}</h6>${this.readerScopes(key, `${context}:case:${ci}`, cs.scope_chain)}</section>`).join('')}${group.discharged_scope_refs.length ? `<p>Discharged local contexts: ${group.discharged_scope_refs.map(ref => this.humanLink(ref, 'Context')).join(', ')}</p>` : ''}<p>${this.humanLink(group.group_ref, 'Inference evidence')}</p></section>`;
  }

  readerArgument(key, reader, argument, index, rows, body) {
    const context = `argument:${index}`;
    const relation = {target:'Argument for an opening target', linked_intermediate:'Intermediate argument connected to an opening target', subsidiary:'Owned subsidiary material; no recorded inference chain connects it to an opening target', unassociated:'Argument association unavailable'}[argument.relation];
    const title = `${this.readerField(key, context, argument.argument_ref, 'label')} <span class="proof-muted">(${this.readerField(key, context, argument.argument_ref, 'origin')})</span>`;
    const contents = `<p class="proof-muted">${esc(relation)} · Target: ${this.humanLink(argument.target_ref)}${argument.relation === 'linked_intermediate' && argument.reaches_target_refs.length ? `. Recorded route reaches: ${argument.reaches_target_refs.map(ref => this.humanLink(ref)).join(', ')}` : ''}</p>
${this.readerScopes(key, context, argument.scope_chain, {deduplicate:true,seed:body.lifecycle !== 'retired' && ['target','linked_intermediate'].includes(argument.relation)})}
${this.readerApplications(key, rows.filter(({app}) => app.from_ref.collection !== 'items' || this.readerRecord(app.from_ref)?.body?.owner_id !== reader.item_ref.id), reader.item_ref)}
<details class="proof-reader-context"><summary>Argument structure and local proof contexts</summary><p class="proof-muted">Stable inventory of recorded inferences, not a reconstructed proof sequence.</p>
${body.final_group_id ? `<p>Recorded final inference: ${this.humanLink({collection:'groups',id:body.final_group_id})}</p>` : '<p class="proof-muted">No final inference is registered for this argument.</p>'}
${argument.groups.map((group, gi) => this.readerGroup(key, `${context}:group:${gi}`, group)).join('')}
${this.readerApplications(key, rows.filter(({app}) => app.from_ref.collection === 'items' && this.readerRecord(app.from_ref)?.body?.owner_id === reader.item_ref.id), reader.item_ref)}
<p>${this.humanLink(argument.argument_ref, 'Argument evidence')}</p>${this.readerSources(argument.argument_ref)}
</details>`;
    const attrs = `data-reader-route="${index}" data-reader-route-ref="${esc(refKey(argument.argument_ref))}" data-reader-route-relation="${esc(argument.relation)}" data-reader-route-target="${esc(refKey(argument.target_ref))}"`;
    return body.lifecycle === 'retired' || argument.relation === 'subsidiary' ? `<details class="proof-reader-route proof-reader-context" ${attrs}><summary>${body.lifecycle === 'retired' ? 'Historical route: ' : 'Subsidiary argument: '}${title}</summary>${contents}</details>` : `<section class="proof-reader-route" ${attrs}><h5>${title}</h5>${contents}</section>`;
  }

  readerApplications(key, rows, targetRef) {
    const groups = new Map();
    for (const row of rows) {
      const id = row.app.group_ref ? refKey(row.app.group_ref) : '';
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(row);
    }
    return [...groups.values()].map(members => {
      const group = members[0].app.group_ref;
      const kind = this.readerRecord(group)?.body?.kind;
      const label = kind === 'joint' ? 'All inputs in this recorded group' : kind === 'cases' ? 'Case analysis' : 'Recorded inference context';
      return `${group ? `<p class="proof-reader-group-label">${this.humanLink(group, label)}</p>` : ''}<div class="proof-reader-inputs">${members.map(({app,index}) => this.readerApplication(key, app, index, targetRef)).join('')}</div>`;
    }).join('');
  }

  readerApplication(key, app, index, targetRef) {
    const context = `application:${index}`;
    const refined = app.refined_use_refs.length > 0;
    const display = reviewDisplay(app.assessment);
    const recipient = `<p class="proof-reader-label">Used for: ${this.readerNamedLink(key, `${context}:to`, app.to_ref)}</p>`;
    const sameTarget = targetRef && refKey(app.to_ref) === refKey(targetRef);
    const kind = this.readerRecord(app.from_ref)?.body?.kind;
    const role = kind === 'assumption' ? 'Assumed input' : kind === 'definition' ? 'Declared setup' : 'Supporting input';
    const content = `<div class="proof-reader-application" data-reader-application="${index}" data-reader-relation="${esc(app.relation)}" data-reader-from="${esc(refKey(app.from_ref))}" data-reader-to="${esc(refKey(app.to_ref))}" data-reader-argument="${esc(app.argument_ref ? refKey(app.argument_ref) : '')}" data-reader-group="${esc(app.group_ref ? refKey(app.group_ref) : '')}">
<h6><span class="proof-premise-role">${role}</span> ${this.readerNamedLink(key, `${context}:from`, app.from_ref)}</h6>
${sameTarget ? '' : recipient}
${!app.application_ref ? '<p class="proof-muted">Recorded summary connection; this is not an additional checked implication.</p>' : ''}
${this.readerField(key, context, app.use_ref, 'reason')}
${['regime','uncertainty'].map(field => this.readerRecord(app.use_ref)?.body?.[field] ? `<p class="proof-reader-label">${field === 'regime' ? 'Restriction' : 'Uncertainty'}</p>${this.readerField(key, context, app.use_ref, field)}` : '').join('')}
${app.application_ref ? `${this.readerRecord(app.application_ref)?.body?.needed_form ? `<details class="proof-reader-context"><summary>Exact required form and conditions</summary>${this.readerField(key, context, app.application_ref, 'needed_form')}</details>` : ''}` : ''}
${this.readerScopes(key, context, app.scope_chain, {deduplicate:true})}
<p class="proof-application-status">${stateBadge(display.color, display.label)}${app.assessment.availability ? ` <span>Support: ${esc(app.assessment.availability)}</span>` : ''}</p>
${this.readerSupport(key, context, app.support_explanation)}
${refined ? `<p>Explained by ${app.refined_use_refs.map(ref => this.humanLink(ref, 'detailed application')).join(', ')}. The summary is retained as context.</p>` : ''}
${app.summary_use_refs.length ? `<p>Refines ${app.summary_use_refs.map(ref => this.humanLink(ref, 'recorded summary')).join(', ')}.</p>` : ''}
<details class="proof-reader-context"><summary>Application assessment and evidence</summary>
${sameTarget ? recipient : ''}${this.readerAssessment(key, context, app.assessment)}
<p>${this.humanLink(app.application_ref || app.use_ref, 'Inspect exact application and checks')}</p>${this.readerSources(app.use_ref)}</details>
</div>`;
    return refined ? `<details class="proof-reader-context"><summary>Summary connection represented by detailed applications</summary>${content}</details>` : content;
  }

  connectionHeader(connection) {
    const key = connection.detail_key, apps = new Map((connection.applications || []).map(app => [app.use_id, app]));
    const ids = [...new Set([...connection.primary_use_ids, ...apps.keys()])];
    const uses = ids.map((id, index) => {
      const record = this.model.recordsByLoose.get(`uses:${id}`), app = apps.get(id);
      const context = `${this.owners.get(key).length > 1 ? `connection:${connection.id}:` : ''}application:${index}`;
      const body = record?.body || {};
      const from = body.from && this.model.recordsByLoose.get(looseKey(body.from));
      const to = body.to && this.model.recordsByLoose.get(looseKey(body.to));
      const application = [...this.model.recordsByLoose.values()].find(row => row.ref.collection === 'application_details' && row.body.use_id === id) || (body.group_id || body.needed_form ? record : null);
      return `<section class="proof-reader-application"${app ? ` data-application-id="${esc(id)}"` : ''}>
<h4>Supplier: ${from ? this.readerNamedLink(key, `${context}:from`, from.ref) : esc(this.nodeLabel(connection.from))}</h4>
<p class="proof-reader-label">Recipient: ${to ? this.readerNamedLink(key, `${context}:to`, to.ref) : esc(this.nodeLabel(connection.to))} · ${this.humanLink(record?.ref || {collection:'uses',id}, 'Application evidence')}</p>
${!application ? '<p class="proof-muted">Recorded summary connection; no exact application is registered here.</p>' : ''}
${record ? ['reason','regime','uncertainty'].filter(field => body[field]).map(field => `<p class="proof-reader-label">${field === 'reason' ? 'Recorded contribution' : field === 'regime' ? 'Restriction' : 'Uncertainty'}</p>${this.readerField(key, context, record.ref, field)}`).join('') : '<p class="proof-muted">Contribution text is unavailable in this projection.</p>'}
${application ? `${application.body.needed_form ? `<p class="proof-reader-label">Required form</p>${this.readerField(key, context, application.ref, 'needed_form')}` : ''}` : ''}
${app ? this.assessmentBlock(app.assessment, {compact:true}) : ''}
${app ? this.readerSupport(key, context, app.support_explanation) : ''}
${app?.scope_id ? `<p>Applicable context: ${this.humanLink({collection:'scopes',id:app.scope_id}, 'Scope, assumptions and restrictions')}</p>` : ''}
${record ? this.readerSources(record.ref) : ''}</section>`;
    }).join('');
    const groups = connection.groups.map(group => `<section class="proof-reader-group"><h5>${group.group_id ? this.humanLink({collection:'groups',id:group.group_id}, `${humanize(group.inference_kind || 'recorded')} inference`) : 'Summary context'}${group.argument_id ? ` in ${this.humanLink({collection:'arguments',id:group.argument_id})}` : ''}</h5>${this.assessmentBlock(group.assessment, {compact:true})}</section>`).join('');
    return `<div class="proof-detail-owner proof-owner-connection" data-proof-owner-connection="${esc(connection.id)}" data-reader-overview="${esc(key)}">
<p class="proof-owner-kicker"><span class="proof-pill">Recorded connection</span></p>
<h3 class="proof-detail-heading" tabindex="-1">${this.jump(this.model.nodes.get(connection.from).detail_key, this.humanLabelHtml(this.model.nodes.get(connection.from).item_ref))} <span aria-hidden="true">→</span><span class="proof-visually-hidden"> to </span> ${this.jump(this.model.nodes.get(connection.to).detail_key, this.humanLabelHtml(this.model.nodes.get(connection.to).item_ref))}</h3>
${this.assessmentBlock(connection.assessment, {compact:true})}
<h4>Recorded contributions and restrictions</h4>${uses || '<p class="proof-muted">No contribution text is available in this projection.</p>'}
${groups ? `<details class="proof-reader-context"><summary>Inference contexts</summary>${groups}</details>` : ''}
</div>`;
  }

  sectionHtml(detailKey, section) {
    const records = section.record_refs.map((ref) => `<div class="proof-record-slot" data-record-ref="${esc(refKey(ref))}" tabindex="-1"><span class="proof-muted">${esc(this.content.title(ref))}</span></div>`);
    const obligations = section.obligation_ids.map((id) => this.obligationHtml(this.model.obligations.get(id)));
    const empty = !records.length && !obligations.length ? '<p class="proof-muted">Nothing recorded in this section.</p>' : '';
    return `<section class="proof-reading-section proof-section proof-section-${esc(section.kind)}" data-proof-section="${esc(section.key)}" data-proof-section-kind="${esc(section.kind)}" tabindex="-1">
<h4 class="proof-section-title">${esc({statement:'Paper statements',premises:'Assumptions and context',applications:'Applications',derivations:'Intermediate arguments',composition:'Combined argument',coverage:'Examined source passages',findings:'Findings and proposed repairs',sources:'Source passages',review:'Review assessments',limitations:'Source limitations'}[section.kind] || section.title)}</h4>
${section.note ? `<p class="proof-section-note">${esc(section.note)}</p>` : ''}
${records.join('\n')}
${obligations.join('\n')}
${empty}
</section>`;
  }

  obligationHtml(obligation) {
    const state = displayState(obligation.assessment);
    return `<div class="proof-obligation s-${esc(state)}" data-obligation-id="${esc(obligation.id)}" tabindex="-1">
<p class="proof-record-head"><strong>${obligation.role === 'primary' ? 'Initial assessment' : obligation.role === 'independent' ? 'Independent review requirement' : 'Combined assessment'}: ${this.humanLink(obligation.target)}</strong></p>
${obligation.role === 'primary' ? this.assessmentBlock(obligation.assessment) : this.roleWorkHtml(obligation)}
</div>`;
  }

  roleWorkHtml(obligation) {
    const candidates = this.tasksByObligation.get(obligation.id) || [];
    const candidate = candidates.length === 1 ? candidates[0] : null;
    const task = candidate && candidate.role === obligation.role && candidate.kind === obligation.kind
      && candidate.target?.collection === obligation.target.collection && candidate.target?.id === obligation.target.id
      ? candidate : null;
    const role = obligation.role === 'independent' ? 'Independent examination' : 'Comparison';
    const complete = task?.state === 'satisfied' && task.freshness === 'current';
    const status = !task || (task.state === 'satisfied' && (!isString(task.freshness) || !task.freshness.trim()))
      ? 'Completion status unavailable.' : complete ? `${role} completed.` : `${role} incomplete for the current material.`;
    // Coordinator outcomes describe the comparison requirement, not mathematical support.
    const facts = task ? [obligation.role === 'independent' && task.outcome && `Saved outcome: ${humanize(task.outcome)}.`,
      task.freshness && `Freshness: ${humanize(task.freshness)}.`,
      task.requires_independent_context && 'The saved review has compromised independence; a fresh independent context is still required.']
      .filter(Boolean).join(' ') : '';
    const refs = new Map();
    for (const ref of [...obligation.check_refs, ...(task?.judgment_refs || []), ...(task?.draft_refs || [])])
      if (ref && this.model.records.has(refKey(ref))) refs.set(refKey(ref), ref);
    return `<div class="proof-reader-notice" data-role-work="${esc(obligation.role)}"><p>${esc(status)}${facts ? ' ' + esc(facts) : ''}</p>${refs.size ? `<p>Saved evidence: ${[...refs.values()].map(ref => this.humanLink(ref)).join(', ')}</p>` : ''}</div>`;
  }

  scientificValue(value, sourceRef, path, fragment, slice) {
    if (value === null || value === undefined || value === '') return '';
    if (Array.isArray(value)) return '<ul class="proof-value-list">' + value.map((entry, index) => '<li>' + this.scientificValue(entry, sourceRef, [...path, index], Array.isArray(fragment) ? fragment[index] : undefined) + '</li>').join('') + '</ul>';
    if (isObject(value)) {
      if (isString(value.collection) && isString(value.id)) return this.humanLink(value);
      if (Object.hasOwn(value, 'text') && Object.hasOwn(value, 'form')) return (value.form === 'synopsis' ? '<p class="proof-reader-label">Saved synopsis</p>' : '') + this.scientificValue(value.text, sourceRef, [...path, 'text'], fragment, slice);
      return '<dl class="proof-reader-values">' + Object.entries(value).map(([name, entry]) => '<dt>' + esc(humanize(name)) + '</dt><dd>' + this.scientificValue(entry, sourceRef, [...path, name]) + '</dd>').join('') + '</dl>';
    }
    const attrs = ' data-scientific-ref="' + esc(refKey(sourceRef)) + '" data-scientific-path="' + esc(JSON.stringify(path)) + '"' + (slice ? ' data-scientific-start="' + slice.start + '" data-scientific-end="' + slice.end + '"' : '');
    const tag = fragment === undefined ? 'span' : 'div';
    const html = fragment === undefined ? esc(String(value)) : path[0] === 'label' ? prepareLabelFragment(fragment) : prepareFragment(fragment);
    return '<' + tag + ' class="proof-text' + (fragment === undefined ? '' : ' proof-fragment') + '"' + attrs + '>' + html + '</' + tag + '>';
  }

  recordHtml(record) {
    const selected = this.content.record(record);
    const rows = selected.fields.map(field => {
      const sourceRef = field.sourceRef || record.ref;
      const fragments = this.model.fragments.get(refKey(sourceRef)) || {};
      const fragment = field.slice ? undefined : fragments[FRAGMENT_FIELDS[field.path[0]]];
      return '<dt>' + esc(field.label) + '</dt><dd>' + this.scientificValue(field.value, sourceRef, field.path, fragment, field.slice) + '</dd>';
    });
    return '<div class="proof-record proof-record-' + esc(record.ref.collection) + '" data-record-ref="' + esc(refKey(record.ref)) + '" tabindex="-1"><p class="proof-record-title"><strong>' + esc(selected.title) + '</strong></p>' + (selected.notices.length ? selected.notices.map(note => '<p class="proof-reader-notice">' + esc(note) + '</p>').join('') : '') + (rows.length ? '<dl class="proof-record-fields">' + rows.join('') + '</dl>' : '') + '</div>';
  }

  // Scientific consequences of saved work facts, without scheduling instructions.
  reviewLimits() {
    const tasks = this.model.projection.worklist?.tasks || [];
    const proofKinds = ['derivation', 'application', 'composition', 'case_coverage', 'scope_discharge', 'external_source'];
    return tasks.filter(task => task.required && task.state !== 'satisfied').map(task => {
      const role = task.role === 'independent' ? 'Independent assessment' : task.role === 'coordinator' ? 'Combined assessment' : 'Initial assessment';
      const statement = ['items', 'parts'].includes(task.target.collection);
      let consequence;
      if (task.outcome) consequence = task.freshness === 'current'
        ? role + ': ' + task.outcome + '. Examination remains incomplete for the current material.'
        : 'Earlier ' + role.toLowerCase() + ': ' + task.outcome + '. It does not establish a completed current examination.';
      else if (proofKinds.includes(task.kind)) consequence = 'No completed current ' + role.toLowerCase() + ' is recorded for this material.';
      else if (task.kind === 'source_fidelity' && statement) consequence = 'Source comparison is incomplete for this statement.';
      else if (task.kind === 'reconciliation') consequence = 'The recorded assessments have not been fully reconciled.';
      else consequence = 'A review requirement remains unresolved; this record alone does not identify unexamined mathematics.';
      if (task.dependency_support && task.dependency_support !== 'available') consequence += ' Premise support: ' + task.dependency_support + '.';
      return {task, consequence};
    });
  }

  savedLimitations() {
    const records = [...this.model.records.values()], refs = [...records.map(record => record.ref), ...this.model.summary.scope.target_refs];
    return (this.model.summary.limitations || []).map((note, index) => {
      // These exact strings are generated by assessment.py. Unknown or mixed
      // notes remain faithful, including any internal-looking mathematical literal.
      for (const ref of refs) {
        const key = looseKey(ref), label = this.humanLabel(ref);
        if (note === 'register establishment for ' + key + ': no exact registered proof route or local group')
          return {index, note: label + ': no exact establishing argument is registered.'};
        if (note === 'audit target ' + key + ' is an intermediate result')
          return {index, note: label + ': the saved examination scope identifies a subsidiary result.'};
        if (note === 'required target ' + key + ' is not live at revision ' + this.model.projection.snapshot_revision)
          return {index, note: label + ': the required statement is unavailable in the current saved material.'};
      }
      for (const record of records.filter(record => record.ref.collection === 'arguments')) {
        const id = record.ref.id, key = looseKey(record.ref), label = this.humanLabel(record.ref);
        if (note === 'proof boundary for ' + key + ' remains unresolved' || note === 'proof boundary for ' + id + ': complete current source-boundary review required')
          return {index, note: label + ': the examined boundary of the written proof remains unresolved.'};
        if (note === 'located proof passage for ' + key + ' changed')
          return {index, note: label + ': a located proof passage changed, so its earlier examination is not current.'};
        if (note === 'written proof for ' + key + ' has no located source passages')
          return {index, note: label + ': the written proof has no located source passages.'};
        for (const anchor of records.filter(record => record.ref.collection === 'anchors'))
          if (note === 'written proof for ' + key + ' has unavailable source passage ' + anchor.ref.id)
            return {index, note: label + ': the source passage ' + this.humanLabel(anchor.ref) + ' is unavailable.'};
        const missingSource = 'written proof for ' + key + ' has unavailable source passage ';
        if (note.startsWith(missingSource) && ID_PATTERN.test(note.slice(missingSource.length)))
          return {index, note: label + ': a supporting source passage is unavailable.'};
      }
      for (const ref of refs) {
        const prefix = 'proof coverage for ' + looseKey(ref) + ': anchor ', suffix = ' is missing';
        if (note.startsWith(prefix) && note.endsWith(suffix) && ID_PATTERN.test(note.slice(prefix.length,-suffix.length)))
          return {index, note:this.humanLabel(ref) + ': a supporting source passage is missing.'};
      }
      // Coverage diagnostics have a generated numeric span suffix. Replace the
      // whole diagnostic with its source-aware consequence, never edit prose.
      for (const ref of refs) for (const anchor of records.filter(record => record.ref.collection === 'anchors')) {
        const prefix = 'proof coverage for ' + looseKey(ref) + ', anchor ' + anchor.ref.id + ': uncovered or unchecked spans ';
        if (note.startsWith(prefix) && /^\[\d+, \d+\)(?:, \[\d+, \d+\))*$/.test(note.slice(prefix.length)))
          return {index, note: this.humanLabel(ref) + ': ' + this.humanLabel(anchor.ref) + ' contains proof material without a completed current substantive examination.'};
      }
      return {index, note};
    });
  }

  reviewLimitsHtml() {
    const limits = this.reviewLimits(), notes = this.savedLimitations();
    if (!limits.length && !notes.length) return '';
    return '<details class="proof-reader-context" open data-reader-review-limits><summary>Current examination limits</summary><ul>' + limits.map(({task,consequence}) => {
      const location = task.location;
      const link = location ? this.jump(location.detail_key, this.humanLabelHtml(location.ref), {section:location.section_key,record:refKey(location.ref)}) : this.humanLink(task.target);
      return '<li data-proof-review-limit="' + esc(task.id) + '" data-proof-review-kind="' + esc(task.kind || '') + '" data-proof-review-target="' + esc(looseKey(task.target)) + '"><strong>' + link + '</strong>: ' + esc(consequence) + '</li>';
    }).join('') + notes.map(({index,note}) => '<li data-proof-limitation data-proof-limitation-index="' + index + '">' + esc(note) + '</li>').join('') + '</ul></details>';
  }

  searchEntries() {
    const seen = new Set();
    return this.model.projection.record_locations.flatMap(saved => {
      const location = this.locationsByPinned.get(refKey(saved.ref));
      const key = refKey(location.ref), record = this.model.records.get(key);
      const detail = location.detail_key, section = location.section_key;
      const identity = JSON.stringify([key,detail,section]);
      if (!record || seen.has(identity)) return [];
      seen.add(identity);
      const owners = this.owners.get(detail) || [];
      const owner = owners.map(row => row.type === 'node' ? row.node.label : this.nodeLabel(row.connection.from) + ' applied to ' + this.nodeLabel(row.connection.to)).join('; ') || 'Paper evidence';
      const text = this.content.text(record);
      if (!text) return [];
      return [{key, aliases:[key, record.ref.id], label:this.content.title(record), detail, section, owner, text,
        isDirectResult:this.nodeDetailsByPinned.get(key) === detail}];
    });
  }

  sourceReviewLinks() {
    const links = [];
    for (const [key, location] of this.locationsByPinned) {
      const ref = location.ref;
      if (ref.collection !== 'source_reviews' || !Number.isInteger(ref.version) || !this.model.records.has(key)) continue;
      const section = this.model.details.get(location.detail_key)?.sections.find(row => row.key === location.section_key);
      if (!section?.record_refs.some(pin => refKey(pin) === key)) continue;
      const owners = this.owners.get(location.detail_key) || [];
      const owner = owners.length === 1 ? owners[0] : null;
      const label = owner?.type === 'node' ? owner.node.label : owner?.type === 'connection'
        ? `${this.nodeLabel(owner.connection.from)} applied to ${this.nodeLabel(owner.connection.to)}` : null;
      links.push(this.humanLink(ref, label ? `Source-review note for ${label}` : 'Source-review note'));
    }
    return links;
  }

  sourceEvidenceHtml() {
    const notes = this.model.sourceCaptureNotes, links = this.sourceReviewLinks();
    if (!notes.length && !links.length) return '';
    const captures = notes.length ? `<h4>Captured source text</h4><p>These notes describe captured text; source comparisons and mathematical assessments are reported separately.</p><ul>${notes.map((note, index) => {
      const locator = Object.entries(note.locator).map(([key, value]) => `${humanize(key)}: ${isString(value) ? value : JSON.stringify(value)}`).join(', ') || 'Saved source locator';
      return `<li data-source-capture-note="${index}" data-source-ref="${esc(JSON.stringify(note.source_ref))}" data-source-path="${esc(JSON.stringify(note.source_path))}" data-source-locator="${esc(JSON.stringify(note.locator))}" data-source-anchor-refs="${esc(JSON.stringify(note.anchor_refs))}"><span data-source-capture-description>${esc(note.description)}</span> <span class="proof-muted" data-source-capture-locator>${esc((note.source_path ? `${note.source_path}: ` : '') + locator)}</span></li>`;
    }).join('')}</ul>` : '';
    return `<details class="proof-build-disclosure" data-source-evidence><summary>Source evidence</summary>${captures}${links.length ? `<h4>Saved source-review notes</h4><ul>${links.map(link => `<li>${link}</li>`).join('')}</ul>` : ''}</details>`;
  }

  readerReportState() {
    const summary = this.model.summary;
    const limits = [...(summary.factual?.source_limits || []).map(row => `${row.source_path || row.label}: ${row.description}`), ...(summary.factual?.independent_review?.qualification_limitations || [])];
    const independent = summary.factual?.independent_review;
    const nodes = this.model.nodeList.length, connections = this.model.connectionList.length;
    const mapState = this.model.hypothesisList.length ? `${nodes} results, ${connections} proof connections and ${this.model.hypothesisList.length} hypothesis/setup relationships are shown in the recorded map.` : !nodes ? 'No results have been recorded in this report.' : !connections
      ? `${nodes} results are recorded, but no connections between them are recorded. This does not establish that the results are independent.`
      : `${nodes} results and ${connections} connections are shown in the recorded map.`;
    return `<section class="proof-report-state" data-reader-report-state><p><strong>${this.model.build.kind === 'release' ? 'Release report' : 'Working report'}</strong> · ${summary.progress.process_complete ? 'Registered examinations complete.' : 'Registered examinations incomplete.'} Mathematical support is stated separately for each result and application.${this.model.build.kind === 'working' ? ' This working report does not establish completion of the promised audit scope.' : ''}</p><p class="proof-muted">${mapState} Assessments reflect LLM mathematical understanding, not formal proof verification.</p>${independent ? `<p data-reader-review-level>${esc(independent.explanation ?? `Independent review: ${REVIEW_LABELS[independent.state]}.`)}</p>` : ''}${limits.length ? `<ul>${[...new Set(limits)].map(note => `<li>${esc(note)}</li>`).join('')}</ul>` : ''}${this.reviewLimitsHtml()}</section>`;
  }

  page(fontStyle) {
    const { model } = this;
    const searchEntries = this.searchEntries();
    const excerptCandidates = model.projection.records
      .filter(record => record.ref.collection === 'anchors' && typeof record.body.excerpt === 'string')
      .flatMap(record => [record.body.excerpt, record.body.excerpt.replace(/\s+/gu, ' ').trim()]);
    const requestedItems = new Set(model.summary.scope.target_refs.filter((ref) => ref.collection === 'items').map((ref) => ref.id));
    const requested = model.nodeList.filter(node => requestedItems.has(node.item_ref?.id)).map(node => node.id);
    const beforeGraph = `<div id="proof-main" class="proof-reader proof-audit">${this.readerReportState()}${mathDisplayNotes(model.mathDiagnosticSummary)}<details class="proof-build-disclosure"><summary>Scientific findings, scope and review limits</summary>${this.summaryHtml()}</details>${this.graph && model.layout.reasons.length ? `<ul class="proof-reasons">${model.layout.reasons.map((reason) => `<li>${esc(reason)}</li>`).join('')}</ul>` : ''}</div>
${this.graph ? viewControls({traceHtml:`<p class="proof-trace-note">Tracing follows recorded ${model.hypothesisList.length ? 'proof applications and hypothesis/setup relationships' : 'connections'}, including alternative routes. It identifies supporting or potentially affected results; it does not establish a complete or verified proof route.</p>`}) : ''}
<h2 id="proof-graph-heading" class="proof-visually-hidden">Dependency graph</h2><p id="proof-graph-desc" class="proof-visually-hidden">Major results and their recorded uses${model.hypothesisList.length ? ' and hypotheses/setup' : ''}. Proof connection colors describe issue severity and checked status; logical support and review limits are stated separately.</p>`;
    const afterGraph = `<div class="proof-reader proof-audit">${this.graph ? this.legendHtml() : this.indexHtml()}
${scientificSearchPanel()}
${this.detailsHtml()}
${this.sourceEvidenceHtml()}
<footer class="proof-footer">
<p>Archify 3.0.1 viewer (MIT); JetBrains Mono under the SIL Open Font License. Audit evidence and assessments are drawn from the saved paper records.</p>
</footer></div>`;
    const data = `
<script id="proof-projection" type="application/json">${jsonForScript(model.projection)}</script>
<script id="proof-render-input" type="application/json">${jsonForScript({ title: model.title, build: model.build })}</script>
${readerSearchData(searchEntries, { excerptCandidates })}
`;
    // The common page assembler removes this template placeholder in index mode.
    // It has no identity-bearing elements and is never presented as a graph.
    const svg = this.graph ? this.svgHtml() : '<svg class="proof-index-placeholder" viewBox="0 0 100 100" aria-hidden="true" xmlns="http://www.w3.org/2000/svg"></svg>';
    const targets = [
      ...model.nodeList.map(node => ({key:node.detail_key,articleId:this.detailId(node.detail_key),nodeId:node.id})),
      ...model.connectionList.map(edge => ({key:edge.detail_key,articleId:this.detailId(edge.detail_key),edgeId:edge.id})),
      ...model.hypothesisList.filter(edge => !edge.proof_connection_id).map(edge => ({key:`hyp:${edge.id}`,articleId:this.detailId(edge.detail_key),edgeId:edge.id,hypothesisId:edge.id})),
      ...[...model.details.keys()].filter(key => !this.owners.has(key)).map(key => ({key,articleId:this.detailId(key)})),
    ];
    return archifyPage({ templatePath: TEMPLATE_PATH, title: model.title, svg, beforeGraph, afterGraph,
      resultsHtml:auditResults(model.nodeList, model.connectionList, requested, !!this.graph, key => this.detailId(key)),
      runtime: readerRuntime({targets,graphAvailable:!!this.graph}), data, fontStyle, index: !this.graph });
  }
}

// ---------------------------------------------------------------------------
// Fonts (vendored archify template)
// ---------------------------------------------------------------------------

export function loadFontStyle(templatePath = TEMPLATE_PATH) {
  let template;
  try {
    template = readFileSync(templatePath, 'utf8');
  } catch (error) {
    fail('assets', `Cannot read vendored template ${templatePath}: ${error.message}`);
  }
  const matches = [...template.matchAll(/<style id="archify-fonts">[\s\S]*?<\/style>/g)];
  if (matches.length !== 1) fail('assets', 'vendored template changed: expected exactly one <style id="archify-fonts"> block');
  const block = matches[0][0];
  if (!block.includes('@font-face')) fail('assets', 'vendored template changed: font block has no @font-face rule');
  const urls = [...block.matchAll(/url\(\s*["']?([^"')]{0,40})/g)].map((match) => match[1]);
  if (!urls.length || urls.some((url) => !url.startsWith('data:font/woff2;base64,'))) fail('assets', 'vendored template changed: font block references a non-data URL');
  if (/<\/?script/i.test(block)) fail('assets', 'vendored template changed: font block contains script markup');
  return block;
}

// ---------------------------------------------------------------------------
// Verification of the emitted artifact
// ---------------------------------------------------------------------------

function parsePathVertices(d) {
  const vertices = [];
  for (const match of String(d).matchAll(/([MLQHV])\s*([-0-9.\s]+)/g)) {
    const numbers = match[2].trim().split(/\s+/).map(Number);
    if (match[1] === 'M' || match[1] === 'L') vertices.push({ x: numbers[0], y: numbers[1], straight: match[1] === 'L' });
    else if (match[1] === 'Q') vertices.push({ x: numbers[2], y: numbers[3], straight: false });
    else return null;
  }
  return vertices;
}

const classList = (element) => String(element.attrs.class || '').split(/\s+/).filter(Boolean);

export function geometryReceipt(model, scan) {
  const checks = ['finite_node_geometry', 'node_clipping', 'node_overlaps', 'finite_route_geometry', 'edge_endpoints_on_boxes', 'routes_through_unrelated_nodes'];
  if (model.layout.mode === 'index') return { status: 'not_applicable', checks: [], diagnostics: [] };
  if (model.layout.mode === 'cyclic') checks.push('route_clipping');
  const diagnostics = [];
  const svg = scan.elements.find((element) => element.tag === 'svg' && classList(element).includes('proof-svg'));
  if (!svg) return { status: 'fail', checks, diagnostics: ['no svg.proof-svg element was emitted'] };
  const viewBox = String(svg.attrs.viewbox || '').split(/\s+/).map(Number);
  const [, , width, height] = viewBox;
  if (viewBox.length !== 4 || !viewBox.every(Number.isFinite)) diagnostics.push('svg viewBox is not four finite numbers');
  const boxes = new Map();
  for (const element of descendants(svg)) {
    if (!hasAttr(element, 'data-node-id')) continue;
    const id = element.attrs['data-node-id'];
    const rect = element.children.find((child) => child.tag === 'rect' && classList(child).includes('proof-node-box'));
    if (!rect) { diagnostics.push(`node ${id} has no proof-node-box rect`); continue; }
    const box = { x: Number(rect.attrs.x), y: Number(rect.attrs.y), w: Number(rect.attrs.width), h: Number(rect.attrs.height) };
    if (![box.x, box.y, box.w, box.h].every(Number.isFinite) || box.w <= 0 || box.h <= 0) { diagnostics.push(`node ${id} has non-finite or empty geometry`); continue; }
    if (box.x < 0 || box.y < 0 || box.x + box.w > width || box.y + box.h > height) diagnostics.push(`node ${id} extends beyond the viewBox`);
    boxes.set(id, box);
  }
  const ids = [...boxes.keys()];
  for (let i = 0; i < ids.length; i += 1) {
    for (let j = i + 1; j < ids.length; j += 1) {
      const a = boxes.get(ids[i]), b = boxes.get(ids[j]);
      if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) diagnostics.push(`node boxes ${ids[i]} and ${ids[j]} overlap`);
    }
  }
  const eps = 0.011;
  for (const element of descendants(svg)) {
    if (!(element.tag === 'path' && hasAttr(element, 'data-edge-id'))) continue;
    const id = element.attrs['data-edge-id'];
    const vertices = parsePathVertices(element.attrs.d);
    if (!vertices || vertices.length < 2 || vertices.some((vertex) => !Number.isFinite(vertex.x) || !Number.isFinite(vertex.y))) { diagnostics.push(`edge ${id} has a non-finite or unparseable route`); continue; }
    if (vertices.some((vertex) => vertex.x < 0 || vertex.y < 0 || vertex.x > width || vertex.y > height)) diagnostics.push(`edge ${id} extends beyond the viewBox`);
    const from = boxes.get(element.attrs['data-edge-from']), to = boxes.get(element.attrs['data-edge-to']);
    if (!from || !to) { diagnostics.push(`edge ${id} refers to a node without a box`); continue; }
    const first = vertices[0], last = vertices[vertices.length - 1];
    if (Math.abs(first.x - (from.x + from.w)) > eps || first.y < from.y - eps || first.y > from.y + from.h + eps) diagnostics.push(`edge ${id} does not start on the right edge of node ${element.attrs['data-edge-from']}`);
    if (Math.abs(last.x - to.x) > eps || last.y < to.y - eps || last.y > to.y + to.h + eps) diagnostics.push(`edge ${id} does not end on the left edge of node ${element.attrs['data-edge-to']}`);
    for (let i = 1; i < vertices.length; i += 1) {
      if (!vertices[i].straight) continue;
      const x1 = vertices[i - 1].x, y1 = vertices[i - 1].y, x2 = vertices[i].x, y2 = vertices[i].y;
      for (const [nodeId, box] of boxes) {
        if (nodeId === element.attrs['data-edge-from'] || nodeId === element.attrs['data-edge-to']) continue;
        const horizontal = Math.abs(y1 - y2) < eps && y1 > box.y && y1 < box.y + box.h && Math.max(x1, x2) > box.x && Math.min(x1, x2) < box.x + box.w;
        const vertical = Math.abs(x1 - x2) < eps && x1 > box.x && x1 < box.x + box.w && Math.max(y1, y2) > box.y && Math.min(y1, y2) < box.y + box.h;
        if (horizontal || vertical) diagnostics.push(`edge ${id} crosses unrelated node ${nodeId}`);
      }
    }
  }
  return { status: diagnostics.length ? 'fail' : 'pass', checks, diagnostics };
}

export function representationReceipt(model, scan) {
  const diagnostics = [];
  const checks = [];
  const check = (name, condition, message) => { checks.push(name); if (!condition) diagnostics.push(message); };
  const { projection } = model;
  const all = scan.elements;
  const byAttr = (name) => all.filter((element) => hasAttr(element, name));

  const projectionScripts = all.filter((element) => element.tag === 'script' && element.attrs.id === 'proof-projection');
  let embedded = null;
  try { embedded = projectionScripts.length === 1 ? JSON.parse(projectionScripts[0].text) : null; } catch { embedded = null; }
  check('projection_script', projectionScripts.length === 1 && projectionScripts[0].attrs.type === 'application/json' && embedded !== null && JSON.stringify(embedded) === JSON.stringify(projection) && !/[<>&]/.test(projectionScripts[0].text), 'script#proof-projection is missing, duplicated, or does not round-trip the projection verbatim');
  const inputScripts = all.filter((element) => element.tag === 'script' && element.attrs.id === 'proof-render-input');
  let renderInput = null;
  try { renderInput = inputScripts.length === 1 ? JSON.parse(inputScripts[0].text) : null; } catch { renderInput = null; }
  check('render_input_script', inputScripts.length === 1 && inputScripts[0].attrs.type === 'application/json' && renderInput !== null && JSON.stringify(renderInput) === JSON.stringify({ title: model.title, build: model.build }) && !/[<>&]/.test(inputScripts[0].text), 'script#proof-render-input is missing, duplicated, or does not hold {title, build}');
  const nativeControls = ['btn-theme', 'btn-present', 'btn-export', 'btn-node-finder', 'btn-overview-map', 'btn-route-probe', 'btn-reach-upstream', 'btn-reach-downstream', 'focus-chip'];
  check('archify_shell', model.layout.mode === 'index'
    ? all.filter((element) => element.attrs.id === 'proof-index-theme').length === 1 && !all.some((element) => classList(element).includes('diagram-container'))
    : nativeControls.every((id) => all.filter((element) => element.attrs.id === id).length === 1)
    && all.some((element) => element.tag === 'script' && element.text?.includes('Archify.focus =') && element.text.includes('Archify.view =')),
  'the bundled Archify viewer shell or runtime is missing');

  const nodeIds = model.nodeList.map((node) => node.id);
  const connectionIds = model.graphConnectionList.map((connection) => connection.id);
  const nodeElements = byAttr('data-node-id');
  const edgeElements = byAttr('data-edge-id');
  const insideSvg = (element) => { for (let parent = element.parent; parent; parent = parent.parent) if (parent.tag === 'svg') return true; return false; };
  if (model.layout.mode !== 'index') {
    check('dag_nodes', sameMultiset(nodeElements.map((element) => element.attrs['data-node-id']), nodeIds)
      && nodeElements.every((element) => element.tag === 'g' && insideSvg(element) && element.attrs.tabindex === '0' && element.attrs.role === 'button'
        && element.attrs['data-node-state'] === displayState(model.nodes.get(element.attrs['data-node-id']).assessment)
        && element.attrs['data-node-kind'] === model.nodes.get(element.attrs['data-node-id']).kind),
    'svg node groups do not match the projection nodes exactly once with state, kind, tabindex and role');
    check('dag_edges', sameMultiset(edgeElements.map((element) => element.attrs['data-edge-id']), connectionIds)
      && edgeElements.every((element) => element.tag === 'path' && insideSvg(element)
        && element.attrs['data-edge-from'] === model.graphConnections.get(element.attrs['data-edge-id']).from
        && element.attrs['data-edge-to'] === model.graphConnections.get(element.attrs['data-edge-id']).to
        && element.attrs['data-edge-state'] === (model.hypotheses.has(element.attrs['data-edge-id']) ? 'hypothesis' : displayState(model.graphConnections.get(element.attrs['data-edge-id']).assessment))),
    'svg edge paths do not match the projection connections exactly once with from, to and state');
    check('no_index_articles', !byAttr('data-proof-index-item').length && !byAttr('data-proof-index-connection').length && !all.some((element) => element.attrs.id === 'proof-major-index'), 'diagram mode must not emit index articles');
  } else {
    check('no_graph_elements', !nodeElements.length && !edgeElements.length, 'index mode must not emit data-node-id or data-edge-id elements');
    const sections = all.filter((element) => element.tag === 'section' && element.attrs.id === 'proof-major-index');
    const section = sections[0];
    const within = section ? [...descendants(section)] : [];
    const itemArticles = byAttr('data-proof-index-item');
    const connectionArticles = byAttr('data-proof-index-connection');
    check('index_section', sections.length === 1, 'section#proof-major-index must appear exactly once');
    check('index_items', sameMultiset(itemArticles.map((element) => element.attrs['data-proof-index-item']), nodeIds)
      && itemArticles.every((element) => element.tag === 'article' && within.includes(element) && element.attrs['data-node-state'] === displayState(model.nodes.get(element.attrs['data-proof-index-item']).assessment)),
    'index item articles do not match the projection nodes exactly once with state');
    check('index_connections', sameMultiset(connectionArticles.map((element) => element.attrs['data-proof-index-connection']), model.connectionList.map(edge => edge.id))
      && connectionArticles.every((element) => element.tag === 'article' && within.includes(element)
        && element.attrs['data-edge-from'] === model.connections.get(element.attrs['data-proof-index-connection']).from
        && element.attrs['data-edge-to'] === model.connections.get(element.attrs['data-proof-index-connection']).to
        && element.attrs['data-edge-state'] === displayState(model.connections.get(element.attrs['data-proof-index-connection']).assessment)),
    'index connection articles do not match the projection connections exactly once with from, to and state');
    const hypotheses = byAttr('data-proof-index-hypothesis');
    check('index_hypotheses', sameMultiset(hypotheses.map(element => element.attrs['data-proof-index-hypothesis']), model.hypothesisList.map(edge => edge.id))
      && hypotheses.every(element => {
        const relation = model.hypotheses.get(element.attrs['data-proof-index-hypothesis']);
        return element.tag === 'article' && within.includes(element) && element.attrs['data-edge-from'] === relation.from && element.attrs['data-edge-to'] === relation.to && element.attrs['data-edge-state'] === 'hypothesis';
      }), 'index hypotheses differ from the recorded target conditions');
    const sectionText = section ? textOf(scan, section) : '';
    check('index_reasons', model.layout.reasons.every((reason) => sectionText.includes(reason)), 'index section does not show every layout reason');
  }

  const detailElements = byAttr('data-proof-detail');
  const detailKeys = [...model.details.keys()];
  check('detail_elements', sameMultiset(detailElements.map((element) => element.attrs['data-proof-detail']), detailKeys), 'data-proof-detail elements do not match the detail keys exactly once');
  let sectionsOk = true, recordsOk = true, obligationsOk = true;
  const recordElementsSeen = new Set(), obligationElementsSeen = new Set();
  for (const element of detailElements) {
    const detail = model.details.get(element.attrs['data-proof-detail']);
    if (!detail) { sectionsOk = false; continue; }
    const sectionElements = [...descendants(element)].filter((child) => hasAttr(child, 'data-proof-section'));
    const expected = detail.sections.map((section) => section.key);
    if (JSON.stringify(sectionElements.map((child) => child.attrs['data-proof-section'])) !== JSON.stringify(expected)) { sectionsOk = false; diagnostics.push(`detail ${element.attrs['data-proof-detail']} sections are ${JSON.stringify(sectionElements.map((child) => child.attrs['data-proof-section']))}, expected ${JSON.stringify(expected)}`); continue; }
    sectionElements.forEach((sectionElement, index) => {
      const section = detail.sections[index];
      const inner = [...descendants(sectionElement)];
      const records = inner.filter((child) => hasAttr(child, 'data-record-ref'));
      const obligations = inner.filter((child) => hasAttr(child, 'data-obligation-id'));
      records.forEach((child) => recordElementsSeen.add(child));
      obligations.forEach((child) => obligationElementsSeen.add(child));
      if (JSON.stringify(records.map((child) => child.attrs['data-record-ref'])) !== JSON.stringify(section.record_refs.map(refKey))) { recordsOk = false; diagnostics.push(`section ${section.key} of detail ${element.attrs['data-proof-detail']} does not list its record refs in order`); }
      if (!sameMultiset(obligations.map((child) => child.attrs['data-obligation-id']), section.obligation_ids)) { obligationsOk = false; diagnostics.push(`section ${section.key} of detail ${element.attrs['data-proof-detail']} does not list its obligation ids exactly once`); }
    });
  }
  check('detail_sections', sectionsOk, 'detail sections are missing or out of order');
  check('section_record_refs', recordsOk && byAttr('data-record-ref').every((element) => recordElementsSeen.has(element)), 'record ref elements do not match section record_refs, or appear outside sections');
  check('section_obligation_ids', obligationsOk && byAttr('data-obligation-id').every((element) => obligationElementsSeen.has(element)), 'obligation elements do not match section obligation_ids, or appear outside sections');
  const templates = byAttr('data-record-template');
  const canonicalRenderer = new Renderer(model, null);
  const scientificLeaves = (value, path, sourceRef, fragment, slice) => {
    if (value === null || value === undefined || value === '') return [];
    if (Array.isArray(value)) return value.flatMap((entry, index) => scientificLeaves(entry, [...path,index], sourceRef, Array.isArray(fragment) ? fragment[index] : undefined));
    if (isObject(value)) {
      if (isString(value.collection) && isString(value.id)) return [];
      if (Object.hasOwn(value,'text') && Object.hasOwn(value,'form')) return scientificLeaves(value.text,[...path,'text'],sourceRef,fragment,slice);
      return Object.entries(value).flatMap(([key, entry]) => scientificLeaves(entry,[...path,key],sourceRef));
    }
    return [{value,path,sourceRef,fragment,slice}];
  };
  const scientificIdentity = row => JSON.stringify([refKey(row.sourceRef),row.path,row.slice?.start ?? null,row.slice?.end ?? null]);
  const fieldMatches = (element, field) => {
    const source = model.records.get(refKey(field.sourceRef));
    let original = source?.body;
    for (const key of field.path) original = original?.[key];
    if (field.slice && isString(original)) original = [...original].slice(field.slice.start,field.slice.end).join('');
    if (original !== field.value) return false;
    return field.fragment === undefined ? textOf(scan,element) === String(original)
      : scan.html.slice(element.openEnd,element.closeStart) === (field.path[0] === 'label' ? prepareLabelFragment(field.fragment) : prepareFragment(field.fragment));
  };
  check('scientific_record_templates', sameMultiset(templates.map((element) => element.attrs['data-record-template']), [...model.records.keys()])
    && templates.every(element => {
      const record = model.records.get(element.attrs['data-record-template']);
      if (element.tag !== 'template' || !record) return false;
      const expected = canonicalRenderer.content.record(record).fields.flatMap(field => {
        const sourceRef = field.sourceRef || record.ref;
        const fragment = field.slice ? undefined : (model.fragments.get(refKey(sourceRef)) || {})[FRAGMENT_FIELDS[field.path[0]]];
        return scientificLeaves(field.value,field.path,sourceRef,fragment,field.slice);
      });
      const marked = [...descendants(element)].filter(child => hasAttr(child,'data-scientific-ref'));
      const identity = child => {
        try { return JSON.stringify([child.attrs['data-scientific-ref'],JSON.parse(child.attrs['data-scientific-path']),
          hasAttr(child,'data-scientific-start') ? Number(child.attrs['data-scientific-start']) : null,
          hasAttr(child,'data-scientific-end') ? Number(child.attrs['data-scientific-end']) : null]); }
        catch { return null; }
      };
      if (!sameMultiset(marked.map(identity),expected.map(scientificIdentity))) {
        diagnostics.push(`scientific field paths differ in ${refKey(record.ref)}`); return false;
      }
      const pending = [...expected];
      return marked.every(child => {
        const at = pending.findIndex(field => scientificIdentity(field) === identity(child));
        if (at < 0) return false;
        const field = pending.splice(at,1)[0], matches = fieldMatches(child,field);
        if (!matches) diagnostics.push(`scientific field differs in ${refKey(record.ref)}: ${JSON.stringify(field.path)}`);
        return matches;
      });
    }), 'selected scientific statements, conditions, reasoning or mathematics are absent or changed in their pinned evidence destination');
  const expectedHypothesisContexts = [];
  const expectedOverviews = [...model.details.entries()].flatMap(([key, detail]) => {
    const html = canonicalRenderer.detailHtml(key, detail), parsed = scanHtml(html);
    expectedHypothesisContexts.push(...parsed.elements.filter(element => classList(element).includes('proof-hypothesis-contexts')).map(element => html.slice(element.start, element.closeEnd)));
    return parsed.elements.filter(element => hasAttr(element, 'data-reader-overview')).map(element => html.slice(element.start, element.closeEnd));
  });
  check('hypothesis_context_content', sameMultiset(all.filter(element => classList(element).includes('proof-hypothesis-contexts')).map(element => scan.html.slice(element.start, element.closeEnd)), expectedHypothesisContexts),
    'visible hypothesis descriptions or links differ from their saved context');
  const shownOverviews = byAttr('data-reader-overview');
  check('contextual_reader_overviews', sameMultiset(shownOverviews.map(element => scan.html.slice(element.start, element.closeEnd)), expectedOverviews)
    && shownOverviews.every(element => {
      if (classList(element).includes('proof-reader-overview')) {
        const node = model.nodes.get(element.parent?.attrs['data-proof-owner-node']);
        const reader = model.details.get(element.attrs['data-reader-overview'])?.reader;
        if (!node || node.detail_key !== element.attrs['data-reader-overview'] || !reader || refKey(node.item_ref) !== refKey(reader.item_ref)) return false;
      }
      for (let parent = element.parent; parent; parent = parent.parent) {
      if (parent.tag === 'template' || hasAttr(parent, 'hidden') || hasAttr(parent, 'data-proof-evidence')) return false;
    } return true; }), 'opening statements, strategy, contextual dependencies or material issues differ from their pinned records');
  const reportState = byAttr('data-reader-report-state');
  const sourceEvidence = byAttr('data-source-evidence'), expectedEvidence = canonicalRenderer.sourceEvidenceHtml();
  check('visible_report_state', reportState.length === 1 && scan.html.slice(reportState[0].start, reportState[0].closeEnd) === canonicalRenderer.readerReportState()
    && (expectedEvidence ? sourceEvidence.length === 1 && scan.html.slice(sourceEvidence[0].start, sourceEvidence[0].closeEnd) === expectedEvidence : sourceEvidence.length === 0),
    'the report state, limitations or source evidence differ from the saved snapshot');
  const assessmentMatches = (element, assessment) => {
    const display = reviewDisplay(assessment);
    if (!element || !classList(element).includes(`s-${display.color}`) || element.attrs['data-review-status'] !== display.status) return false;
    const children = [...descendants(element)];
    const field = (name) => children.find((child) => classList(child).includes(name));
    const label = field('proof-assessment-label'), explanation = field('proof-assessment-text');
    const glyph = field('proof-state-glyph'), badge = field('proof-state-badge');
    if (!label || textOf(scan, label) !== assessment.label || !badge || !classList(badge).includes(`s-${display.color}`)
        || !glyph || textOf(scan, glyph) !== STATE_GLYPHS[display.color] || textOf(scan, badge) !== STATE_GLYPHS[display.color] + display.label) return false;
    if (assessment.explanation && (!explanation || textOf(scan, explanation) !== assessment.explanation)) return false;
    if (assessment.availability && !textOf(scan, field('proof-availability') || element).includes(`Exact target support: ${assessment.availability}`)) return false;
    return true;
  };
  const ownerAssessment = (detailKey, type, id) => {
    const element = detailElements.find((entry) => entry.attrs['data-proof-detail'] === detailKey);
    const owners = element ? [...descendants(element)].filter(child => child.attrs[`data-proof-owner-${type}`] === id) : [];
    return owners.length === 1 && [...descendants(owners[0])].find((child) => classList(child).includes('proof-assessment'));
  };
  check('visible_assessments', model.nodeList.every((node) => assessmentMatches(ownerAssessment(node.detail_key, 'node', node.id), node.assessment))
    && model.connectionList.every((connection) => assessmentMatches(ownerAssessment(connection.detail_key, 'connection', connection.id), connection.assessment))
    && byAttr('data-obligation-id').every((element) => {
      const obligation = model.obligations.get(element.attrs['data-obligation-id']);
      if (obligation.role === 'primary') return assessmentMatches([...descendants(element)].find((child) => classList(child).includes('proof-assessment')), obligation.assessment);
      const work = [...descendants(element)].filter(child => hasAttr(child, 'data-role-work'));
      return work.length === 1 && scan.html.slice(work[0].start, work[0].closeEnd) === canonicalRenderer.roleWorkHtml(obligation);
    }),
  'visible assessment colors, glyphs, labels or support wording disagree with the canonical assessment');
  const applicationAssessments = new Map(model.connectionList.flatMap((connection) => (connection.applications || []).map((app) => [app.use_id, app.assessment])));
  check('visible_applications', byAttr('data-application-id').every((element) => {
    const assessment = applicationAssessments.get(element.attrs['data-application-id']);
    return assessment && assessmentMatches([...descendants(element)].find((child) => classList(child).includes('proof-assessment')), assessment);
  }), 'visible exact-application outcomes disagree with the recorded assessments');
  check('visible_graph_states', nodeElements.every((element) => {
    const node = model.nodes.get(element.attrs['data-node-id']);
    const children = [...descendants(element)];
    const label = children.find((child) => child.tag === 'text' && classList(child).includes('proof-node-label'));
    const state = children.find((child) => classList(child).includes('proof-node-state'));
    return node && classList(element).includes(`s-${displayState(node.assessment)}`) && label && textOf(scan, label) === node.label
      && state && textOf(scan, state) === STATE_GLYPHS[displayState(node.assessment)];
  }) && edgeElements.every((element) => {
    if (model.hypotheses.has(element.attrs['data-edge-id'])) return classList(element).includes('proof-hypothesis')
      && !classList(element).some(name => name.startsWith('s-')) && element.attrs['marker-end'] === 'url(#proof-hypothesis-arrow)';
    const connection = model.connections.get(element.attrs['data-edge-id']);
    return connection && classList(element).includes(`s-${displayState(connection.assessment)}`)
      && element.attrs['marker-end'] === `url(#proof-arrow-${displayState(connection.assessment)})`;
  }), 'visible node or edge colors, glyphs or labels disagree with the saved graph');
  check('assessment_styles', all.some((element) => element.tag === 'style' && element.text?.includes(SCIENTIFIC_READER_CSS)),
    'the assessment display stylesheet was changed');
  const summaryElement = all.find((element) => element.attrs.id === 'proof-summary');
  const expectedSummary = scanHtml(canonicalRenderer.summaryHtml()).root.children[0];
  const summaryScan = scanHtml(canonicalRenderer.summaryHtml());
  check('visible_scope', summaryElement && textOf(scan, summaryElement) === textOf(summaryScan, expectedSummary),
    'the visible audit scope, exclusions or completion text differs from the saved summary');

  check('reader_administration_removed', !byAttr('data-proof-count').length
    && !all.some(element => element.attrs.id === 'proof-work-panel' || classList(element).includes('proof-technical') || classList(element).includes('proof-build')),
    'administrative counters, revision details or the coordinator work queue entered the scientific reader');
  const processElements = byAttr('data-proof-process-complete');
  check('process_complete', processElements.length === 1 && processElements[0].attrs['data-proof-process-complete'] === String(model.summary.progress.process_complete), 'data-proof-process-complete must appear exactly once with the summary value');
  check('summary_findings', sameMultiset(byAttr('data-proof-finding').map((element) => element.attrs['data-proof-finding']), model.summary.findings.refs), 'data-proof-finding elements do not match summary.findings.refs exactly once');
  check('summary_issue_cards', byAttr('data-proof-finding').every(element => {
    const id = element.attrs['data-proof-finding'], index = model.summary.findings.refs.indexOf(id);
    const record = model.recordsByLoose.get(`findings:${id}`);
    const card = [...descendants(element)].find(child => child.attrs['data-issue-ref'] === id);
    return !record || card && scan.html.slice(card.start, card.closeEnd) === canonicalRenderer.findingCard('summary', index, record.ref);
  }), 'issue card severity, mathematical explanation or evidence differs from the saved finding');
  check('summary_source_limits', sameMultiset(byAttr('data-proof-source-limit').map((element) => element.attrs['data-proof-source-limit']), model.summary.source_limits), 'data-proof-source-limit elements do not match summary.source_limits exactly once');
  check('summary_limitations', sameMultiset(byAttr('data-proof-limitation').map((element) => textOf(scan, element)), canonicalRenderer.savedLimitations().map(row => row.note)), 'scientific or unresolved mixed review qualifications were omitted or changed');
  const reviewLimits = canonicalRenderer.reviewLimits();
  check('current_examination_limits', sameMultiset(byAttr('data-proof-review-limit').map(element => element.attrs['data-proof-review-limit']), reviewLimits.map(row => row.task.id))
    && byAttr('data-proof-review-limit').every(element => textOf(scan,element).endsWith(reviewLimits.find(row => row.task.id === element.attrs['data-proof-review-limit'])?.consequence)),
    'unfinished, partial or stale saved opinions lost their current-examination limitation');
  const searchData = all.filter(element => element.attrs.id === 'proof-reader-search');
  let searchOk = false;
  try { searchOk = searchData.length === 1 && JSON.stringify(decodeReaderSearchData(JSON.parse(searchData[0].text))) === JSON.stringify(canonicalRenderer.searchEntries()); } catch { /* invalid data fails below */ }
  check('scientific_search_content', searchOk, 'search differs from the selected scientific evidence or its destinations');
  const searchInputs = all.filter((element) => element.tag === 'input' && element.attrs.id === 'proof-search');
  check('search_input', searchInputs.length === 1, 'input#proof-search must appear exactly once');

  const external = (value) => /^(?:https?:)?\/\//i.test(String(value).trim());
  const externalRequests = all.filter((element) => (hasAttr(element, 'src') && external(element.attrs.src)) || (element.tag === 'link' && hasAttr(element, 'href')) || (element.tag === 'iframe') || (element.tag === 'object') || (element.tag === 'embed') || (element.tag === 'use' && hasAttr(element, 'href') && external(element.attrs.href)));
  const styleUrls = all.filter((element) => element.tag === 'style').flatMap((element) => [...element.text.matchAll(/url\(\s*["']?([^"')]+)/g)].map((match) => match[1].trim()));
  const inlineStyleUrls = all.filter((element) => hasAttr(element, 'style')).flatMap((element) => [...element.attrs.style.matchAll(/url\(\s*["']?([^"')]+)/g)].map((match) => match[1].trim()));
  const badUrls = [...styleUrls, ...inlineStyleUrls].filter((url) => !(url.startsWith('data:') || url.startsWith('#')));
  check('no_external_requests', !externalRequests.length && !badUrls.length, `the page would request external resources: ${[...externalRequests.map((element) => `<${element.tag}>`), ...badUrls].slice(0, 5).join(', ')}`);

  return { status: diagnostics.length ? 'fail' : 'pass', checks, diagnostics };
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------

export function renderProjection(inputBytes, options = {}) {
  const input = parseInput(inputBytes);
  const model = validateInput(input);
  const graph = model.layout.mode !== 'index' ? layoutGraph(model) : null;
  const fontStyle = options.fontStyle === undefined ? loadFontStyle() : options.fontStyle;
  const renderer = new Renderer(model, graph);
  const html = renderer.page(fontStyle);
  const scan = scanHtml(html);
  const geometry = geometryReceipt(model, scan);
  if (geometry.status === 'fail') fail('verify', 'Geometry verification of the rendered graph failed.', geometry.diagnostics);
  const representation = representationReceipt(model, scan);
  if (representation.status === 'fail') fail('verify', 'Representation verification of the rendered page failed.', representation.diagnostics);
  const bytes = Buffer.from(html, 'utf8');
  const receipt = {
    input_sha256: sha256(inputBytes),
    artifact_sha256: sha256(bytes),
    layout_mode: model.layout.mode,
    nodes: model.nodeList.length,
    connections: model.connectionList.length,
    geometry: { status: geometry.status, checks: geometry.checks, diagnostics: geometry.diagnostics },
    representation: { status: representation.status, checks: representation.checks },
  };
  return { html, bytes, receipt, model };
}

export function main(argv) {
  if (argv.length !== 2) {
    process.stderr.write(JSON.stringify({ ok: false, stage: 'usage', error: 'usage: node render_projection.mjs INPUT.json OUTPUT.html', diagnostics: [] }) + '\n');
    return 2;
  }
  const inputPath = path.resolve(argv[0]);
  const outputPath = path.resolve(argv[1]);
  let stage = 'read';
  const temporary = `${outputPath}.${process.pid}.tmp`;
  let wroteTemporary = false;
  try {
    let inputBytes;
    try {
      inputBytes = readFileSync(inputPath);
    } catch (error) {
      fail('read', `Cannot read input ${inputPath}: ${error.message}`);
    }
    stage = 'render';
    const { bytes, receipt } = renderProjection(inputBytes);
    stage = 'write';
    if (existsSync(temporary)) fail('write', `Temporary file ${temporary} already exists.`);
    writeFileSync(temporary, bytes, { flag: 'wx' });
    wroteTemporary = true;
    renameSync(temporary, outputPath);
    wroteTemporary = false;
    process.stdout.write(JSON.stringify(receipt) + '\n');
    return 0;
  } catch (error) {
    const isRenderError = error instanceof RenderError;
    process.stderr.write(JSON.stringify({ ok: false, stage: isRenderError ? error.stage : stage, error: isRenderError ? error.message : `Unexpected failure: ${error && error.stack ? error.stack : String(error)}`, diagnostics: isRenderError ? error.diagnostics : [] }) + '\n');
    return 1;
  } finally {
    if (wroteTemporary) {
      try { unlinkSync(temporary); } catch { /* nothing left to clean */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Page assets (inline CSS and runtime script)
// ---------------------------------------------------------------------------

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}
