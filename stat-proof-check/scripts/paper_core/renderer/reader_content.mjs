// Scientific content selected from the frozen record bodies. This adapter is
// shared by evidence and search; it neither edits nor interprets authored prose.
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonempty = value => value !== null && value !== undefined && value !== ''
  && (!Array.isArray(value) || value.length > 0);
const refKey = ref => `${ref.collection}:${ref.id}:${ref.version}`;
const looseKey = ref => `${ref.collection}:${ref.id}`;
const typedRef = value => object(value) && typeof value.collection === 'string'
  && typeof value.id === 'string' && Object.keys(value).every(key => ['collection', 'id', 'version'].includes(key));
const words = value => String(value).replaceAll('_', ' ');
const ref = (collection, id, version) => typeof id === 'string'
  ? {collection, id, ...(Number.isInteger(version) ? {version} : {})} : id;

// Only compatible scientific fields are used for an unrecognized older shape.
// Its original full body remains in the frozen artifact, never in a raw dump.
const COMPATIBLE_FIELDS = {
  label:'Label', title:'Title', caption:'Context', statement:'Saved statement',
  needed_form:'Required mathematical form', proof_idea:'Recorded proof explanation',
  reasoning:'Assessment reasoning', reason:'Recorded contribution', rationale:'Rationale',
  conditions:'Conditions', binders:'Variables and quantifiers', substitutions:'Substitutions',
  uncertainty:'Uncertainty', regime:'Restriction', description:'Description',
  impact_reason:'Effect on the claim', resolution:'Recorded resolution', note:'Scientific note',
  coverage_note:'Review coverage and limitations', exposure_note:'Review exposure explanation',
  limitations:'Limitations', limitation:'Source limitation', omissions:'Material omitted',
  next_action:'Recorded limitation or proposed clarification', excerpt:'Source passage',
  added_conditions:'Proposed added conditions', outcome:'Assessment outcome', scope:'Stated scope',
};

export function createReaderContent(input) {
  const projection = input?.projection || input || {};
  const rows = projection.records instanceof Map ? [...projection.records.values()] : projection.records || [];
  const records = new Map(), latest = new Map();
  for (const row of rows) {
    if (!row?.ref || !object(row.body)) continue;
    records.set(refKey(row.ref), row);
    const key = looseKey(row.ref), previous = latest.get(key);
    if (!previous || previous.ref.version < row.ref.version) latest.set(key, row);
  }
  function resolve(value) {
    if (object(value) && object(value.body) && value.ref) return value;
    if (!typedRef(value)) return null;
    // A missing pinned version must never silently resolve to a newer body.
    return Number.isInteger(value.version) ? records.get(refKey(value)) || null : latest.get(looseKey(value)) || null;
  }
  const tasks = projection.worklist?.tasks || [];
  const taskRows = new Map();
  for (const task of tasks) for (const pin of [...(task.judgment_refs || []), ...(task.draft_refs || [])]) {
    const key = refKey(pin);
    if (!taskRows.has(key)) taskRows.set(key, []);
    taskRows.get(key).push(task);
  }
  for (const entry of Object.values(projection.constituents || {})) for (const pin of entry.check_refs || []) {
    const key = refKey(pin);
    if (!taskRows.has(key)) taskRows.set(key, []);
    taskRows.get(key).push(entry);
  }
  const independentPins = new Set();
  const assessmentContext = value => {
    if (!object(value)) return;
    if (['complete','disputed'].includes(value.independent_review))
      for (const pin of value.check_refs || []) independentPins.add(refKey(pin));
  };
  for (const entry of [...(projection.nodes || []), ...(projection.obligations || [])]) assessmentContext(entry.assessment);
  for (const connection of projection.connections || []) {
    assessmentContext(connection.assessment);
    for (const entry of [...(connection.groups || []), ...(connection.applications || [])]) assessmentContext(entry.assessment);
  }
  for (const detail of Object.values(projection.details || {})) {
    for (const entry of [...(detail.reader?.targets || []), ...(detail.reader?.applications || [])]) assessmentContext(entry.assessment);
  }
  const superseded = new Set();
  for (const row of rows) if (typedRef(row.body?.supersedes)) superseded.add(refKey(row.body.supersedes));
  const cache = new Map();

  function title(value, seen = new Set()) {
    const row = resolve(value);
    if (!row) return 'Referenced material unavailable';
    const key = refKey(row.ref), b = row.body, c = row.ref.collection;
    if (seen.has(key)) return 'Related mathematical context';
    const next = new Set(seen).add(key), named = target => title(target, next);
    const byId = (collection, id, version) => named(ref(collection, id, version));
    if (c === 'items' || c === 'parts' || c === 'arguments') return b.label || 'Recorded mathematical material';
    if (c === 'papers') return b.title || 'Paper';
    if (c === 'sources') return b.path || b.title || 'Source';
    if (c === 'anchors') {
      const loc = b.locator || {}, parts = [byId('sources', b.source_id, b.source_version)];
      if (loc.label) parts.push(loc.label);
      if (loc.page != null) parts.push(`page ${loc.page}`);
      if (loc.start_line != null) parts.push(loc.end_line != null && loc.end_line !== loc.start_line
        ? `lines ${loc.start_line} to ${loc.end_line}` : `line ${loc.start_line}`);
      return parts.join(', ');
    }
    if (c === 'uses') return `${named(b.from)} to ${named(b.to)}`;
    if (c === 'application_details') return `Application: ${byId('uses', b.use_id)}`;
    if (c === 'target_specs') return `Exact target: ${named(b.target)}`;
    if (c === 'groups') return `${b.kind === 'cases' ? 'Case' : 'Joint'} inference for ${named(b.conclusion)}`;
    if (c === 'scopes') return b.argument_id ? `Context for ${byId('arguments', b.argument_id)}` : 'Assumptions and mathematical context';
    if (c === 'checks') return `${b.role === 'primary' ? 'Initial assessment' : independentLabel(row)}: ${named(b.target)}`;
    if (c === 'findings') return `Finding: ${named(b.target)}`;
    if (c === 'repairs') return `Proposed repair: ${byId('findings', b.finding_id)}`;
    if (c === 'coverage') return `Proof passage: ${byId('arguments', b.argument_id)}`;
    if (c === 'proof_boundaries') return `Examined proof boundary: ${named(b.target)}`;
    if (c === 'connection_refinements') return `Detailed applications for ${byId('uses', b.summary_use_id)}`;
    if (c === 'observations') return `Source comparison: ${named(b.target)}`;
    if (c === 'source_issues') return `Source issue: ${byId('sources', b.source_id)}`;
    if (c === 'source_reviews') return 'Source review and evidence rationale';
    if (c === 'reconciliations') return `Combined assessment: ${named(b.target)}`;
    if (c === 'responses') return responseLabel(row);
    if (c === 'qualifications') return 'Review qualification and limitations';
    if (c === 'reuse_decisions') return `Assessment reuse: ${named(b.check_ref)}`;
    if (c === 'audits') return 'Examination scope and exclusions';
    if (c === 'overview_selections') return b.title || 'Paper overview and scope';
    if (c === 'identity_maps') return 'Interpretation of returned review material';
    return b.label || b.title || 'Saved scientific material';
  }
  function responseLabel(row) {
    const b = row.body, qualification = resolve(ref('qualifications', b.qualification_id));
    if (b.exposure === 'compromised') return 'Review with compromised independence';
    if (qualification && !qualification.body.qualified) return 'Review without independent qualification';
    if (b.qualification_id && !qualification) return 'Review with unavailable qualification context';
    const audit = resolve(ref('audits', b.audit_id));
    if (!qualification && audit && audit.body.protocol_version !== 'coherent-proof-audit/1') return 'Review with unestablished qualification';
    if (b.exposure === 'route_provided') return 'Review with supplied argument context';
    return 'Independent review response';
  }
  function independentLabel(row) {
    const response = resolve(ref('responses', row.body.response_id));
    if (!response) return 'Additional assessment (independence unestablished)';
    const label = responseLabel(response);
    if (label === 'Independent review response') return 'Independent assessment';
    if (label === 'Review with supplied argument context' && independentPins.has(refKey(row.ref)))
      return 'Independent assessment with supplied argument context';
    return 'Additional assessment';
  }

  function record(value) {
    const row = resolve(value);
    if (!row) return {title:'Referenced material unavailable', fields:[], notices:['The referenced saved material is unavailable in this frozen view.']};
    const key = refKey(row.ref);
    if (cache.has(key)) return cache.get(key);
    const b = row.body, c = row.ref.collection, fields = [], notices = [];
    function add(name, label, value, path = [name], extra = {}) {
      if (arguments.length < 3) value = b[name];
      if (nonempty(value)) fields.push({path, label, value, ...extra});
    }
    const ids = (name, collection, label) => add(name, label, Array.isArray(b[name]) ? b[name].map(id => ref(collection, id)) : undefined);
    const id = (name, collection, label, version) => add(name, label, ref(collection, b[name], version));
    const take = mapping => { for (const [name, label] of Object.entries(mapping)) add(name, label); };
    const evidence = () => ids('evidence_refs', 'anchors', 'Supporting source passages');
    const statementLabel = fallback => b.origin === 'proposed_repair' ? 'Proposed repaired statement'
      : b.origin === 'reconstruction' ? 'Reconstructed statement'
        : b.statement?.form === 'synopsis' ? 'Synopsis of the paper statement' : fallback;
    const span = (anchorRef, start, end, label) => {
      const anchor = resolve(anchorRef);
      if (!anchor || typeof anchor.body.excerpt !== 'string') {
        notices.push('The source passage for this recorded proof span is unavailable.'); return;
      }
      const points = [...anchor.body.excerpt];
      if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start || end > points.length) {
        notices.push('The exact saved proof span cannot be displayed from the available passage; its source context remains linked.'); return;
      }
      add('excerpt', label, points.slice(start, end).join(''), ['excerpt'], {sourceRef:anchor.ref, slice:{start,end}});
    };
    const sourcePassages = () => (b.passages || []).forEach((passage, index) => {
      if (typeof passage === 'string') add('passages','Supporting source passage',ref('anchors',passage),['passages',index]);
      else if (object(passage)) add('passages', `${words(passage.role || 'evidence')} source passage`, ref('anchors', passage.anchor_id), ['passages', index, 'anchor_id']);
    });
    switch (c) {
      case 'papers':
        take({scope:'Stated paper scope', exclusions:'Paper exclusions'}); ids('main_items','items','Main results'); break;
      case 'sources':
        take({media_type:'Source format', limitation:'Source access or evidence limitation'}); break;
      case 'anchors':
        id('source_id','sources','Source',b.source_version); take({locator:'Passage location',excerpt:'Source passage',limitation:'Passage limitation'}); break;
      case 'items':
        take({kind:'Mathematical role',label:'Result label',caption:'Context',statement:statementLabel('Statement from the paper'),proof_idea:'Recorded proof explanation',uncertainty:'Uncertainty',origin:'Statement origin'});
        id('owner_id','items','Owning result'); id('scope_id','scopes','Applicable assumptions and context'); sourcePassages(); break;
      case 'parts':
        take({label:'Proof part label',statement:statementLabel('Statement of the proof part'),origin:'Statement origin'});
        id('item_id','items','Owning result'); id('scope_id','scopes','Applicable assumptions and context'); sourcePassages(); break;
      case 'scopes':
        take({assumptions:'Named assumptions',binders:'Variables and quantifiers',conditions:'Conditions'});
        id('parent_id','scopes','Inherited mathematical context'); id('argument_id','arguments','Argument context'); evidence(); break;
      case 'arguments':
        take({label:'Argument label',target:'Claim addressed',origin:'Argument origin',lifecycle:'Argument status'});
        id('scope_id','scopes','Assumptions and context'); id('final_group_id','groups','Recorded final inference'); evidence(); break;
      case 'groups':
        take({conclusion:'Conclusion',kind:'Joint or case inference',rationale:'Inference rationale'});
        id('argument_id','arguments','Argument context'); id('scope_id','scopes','Assumptions and context');
        ids('case_scope_ids','scopes','Case contexts'); ids('discharges','scopes','Discharged local assumptions'); evidence(); break;
      case 'uses':
        take({from:'Supplier',to:'Recipient',type:'Contribution type',reason:'How the supplier is used',regime:'Restriction',uncertainty:'Uncertainty',needed_form:'Required mathematical form',substitutions:'Substitutions'});
        id('group_id','groups','Inference context'); evidence(); break;
      case 'application_details':
        id('use_id','uses','Supplier application'); id('group_id','groups','Joint or case inference context'); id('scope_id','scopes','Applicable assumptions and context');
        take({needed_form:'Required mathematical form',substitutions:'Substitutions',state:'Application status'}); break;
      case 'target_specs': {
        take({target:'Claim addressed',state:'Exact target status'});
        if (b.statement_ref) {
          const exact = resolve(b.statement_ref);
          if (exact?.body.statement) add('statement','Pinned statement examined',exact.body.statement,['statement'],{sourceRef:exact.ref});
          else notices.push('The pinned statement for this examination is unavailable; a newer synopsis does not replace the examined claim.');
        } else add('statement','Exact statement selected for examination');
        id('scope_id','scopes','Applicable assumptions and context'); add('fidelity_ref','Statement source comparison'); evidence(); break;
      }
      case 'overview_selections':
        take({scope:'Overview scope',unresolved:'Unresolved source or interpretation limitations'});
        ids('main_item_ids','items','Main results'); ids('source_ids','sources','Sources'); break;
      case 'connection_refinements':
        id('summary_use_id','uses','Summary connection'); id('argument_id','arguments','Detailed argument'); ids('use_ids','uses','Detailed applications');
        take({state:'Connection interpretation status',note:'Connection refinement rationale'}); break;
      case 'proof_boundaries':
        take({target:'Claim addressed',anchor_refs:'Proof source passages',source_review_ref:'Source boundary review',state:'Proof boundary status'});
        ids('argument_ids','arguments','Arguments within the boundary');
        notices.push(b.state === 'complete' ? 'This boundary identifies the supplied proof material. It does not by itself establish mathematical support.' : 'The boundary of the supplied proof material remains unresolved.'); break;
      case 'coverage':
        id('argument_id','arguments','Argument context'); id('anchor_id','anchors','Passage location');
        take({classification:'Recorded coverage meaning',claim_refs:'Claims associated with this span',note:'Coverage explanation'}); ids('check_ids','checks','Assessments linked to this span');
        span(ref('anchors',b.anchor_id),b.start_offset,b.end_offset,b.classification === 'structural' ? 'Structural passage' : 'Examined passage');
        notices.push(b.classification === 'structural'
          ? 'This span is structural source material; displaying it does not mean its mathematics was examined.'
          : 'This substantive span is associated with the linked claims and examinations; their outcomes determine its support.'); break;
      case 'observations':
        take({target:'Material compared',result:'Source comparison outcome',note:'Source comparison explanation'}); evidence(); break;
      case 'source_issues':
        id('source_id','sources','Affected source'); id('anchor_id','anchors','Affected passage');
        take({category:'Source issue type',lifecycle:'Issue status',description:'Source issue',resolution:'Recorded resolution'}); break;
      case 'source_reviews':
        take({source_refs:'Reviewed sources',anchor_refs:'Reviewed passages',purpose:'Source review purpose',decision:'Source review outcome',rationale:'Source review rationale'});
        (b.proof_spans || []).forEach((entry,index) => {
          add('proof_spans','Argument within the reviewed boundary',entry.argument_ref,['proof_spans',index,'argument_ref']);
          add('proof_spans','Boundary passage location',entry.anchor_ref,['proof_spans',index,'anchor_ref']);
          span(entry.anchor_ref,entry.start_offset,entry.end_offset,'Reviewed proof boundary passage');
        }); break;
      case 'audits':
        take({mode:'Examination scope',targets:'Material in scope'});
        (b.exclusions || []).forEach((entry,index) => {
          for (const [name,label] of Object.entries({target:'Excluded material',reason:'Reason for exclusion',consequence:'Consequence for the report'}))
            add('exclusions',label,entry[name],['exclusions',index,name]);
          add('exclusions','Excluded source passages',(entry.source_anchor_ids || []).map(id => ref('anchors',id)),['exclusions',index,'source_anchor_ids']);
        });
        if (typeof b.independent_required === 'boolean') notices.push(b.independent_required ? 'Independent review is required for the eligible material in this scope.' : 'Independent review is not required by this examination scope.');
        id('qualification_id','qualifications','Review qualification and limitations'); break;
      case 'checks': {
        take({target:'Material examined',kind:'Examination type',state:'Examination completeness',outcome:'Assessment outcome',reasoning:'Assessment reasoning',conditions:'Conditions on the assessment',extent:'Extent examined',omissions:'Material omitted from examination',next_action:'Recorded limitation or proposed clarification'}); evidence();
        const related = taskRows.get(key) || [], freshness = new Set(related.map(task => task.freshness));
        if (superseded.has(key) || latest.get(looseKey(row.ref))?.ref.version !== row.ref.version || freshness.has('historical'))
          notices.push('Earlier assessment retained for context; it does not establish the current conclusion.');
        else if (freshness.has('needs_review')) notices.push('The saved assessment requires current review; its outcome does not establish examination of all current material.');
        else if (!freshness.has('current')) notices.push('Saved assessment; the result assessment states the current review status.');
        if (b.state !== 'complete') notices.push('This assessment is incomplete; a saved opinion does not establish a complete examination.');
        if (b.extent === 'partial') notices.push('This examination is partial; the omitted material remains outside this assessment.');
        if (b.role === 'independent') {
          id('response_id','responses','Review coverage and independence context');
          const response = resolve(ref('responses',b.response_id));
          if (response && responseLabel(response) === 'Review with supplied argument context')
            notices.push('This review received supplied argument context; its recorded review level and exposure explanation describe the resulting confidence.');
          else if (response && responseLabel(response) !== 'Independent review response') notices.push(responseLabel(response) + ': this assessment does not establish a qualified independent examination.');
          else if (!response) notices.push('The qualification and exposure context for this additional assessment is unavailable.');
        }
        add('supersedes','Earlier assessment replaced'); break;
      }
      case 'findings':
        take({target:'Affected material',category:'Finding type',severity:'Research severity',lifecycle:'Finding status',description:'Finding',impact_reason:'Effect on the claim',resolution:'Recorded resolution',check_refs:'Supporting assessments'});
        ids('affected_uses','uses','Affected applications'); evidence(); break;
      case 'repairs':
        id('finding_id','findings','Finding addressed'); id('argument_id','arguments','Proposed supplemental argument');
        take({kind:'Proposal type',description:'Proposed repair',supported_form:'Proposed supported restricted form',added_conditions:'Proposed added conditions'}); evidence();
        notices.push('This is a repair proposal. Its presence does not establish that the original claim has been repaired.'); break;
      case 'qualifications':
        take({qualified:'Independent-review qualification',limitations:'Qualification limitations'});
        if (!b.qualified) notices.push('This review does not have the recorded qualification required for independent review.'); break;
      case 'responses':
        take({covered_targets:'Material addressed by the response',coverage_note:'Review coverage and limitations recorded at submission',exposure:'Review exposure level',exposure_note:'Consequential exposure explanation',state:'Review integration status'});
        id('qualification_id','qualifications','Review qualification and limitations');
        if (Array.isArray(b.pending_judgments)) {
          if (b.pending_judgments.length) notices.push('Some returned concerns are not yet linked to the examined material and are not included in the assessment.');
          else if (b.state === 'accepted') notices.push('All returned judgments are linked to the examined material.');
        }
        if (responseLabel(row) === 'Review with supplied argument context') notices.push('This response received supplied argument context; its exposure explanation and the combined assessment preserve how that context affects the review.');
        else if (responseLabel(row) !== 'Independent review response') notices.push(responseLabel(row) + '; the recorded exposure and qualification limit the confidence supplied by this review.'); break;
      case 'reconciliations':
        take({target:'Material examined',decision:'Combined assessment outcome',rationale:'Combined assessment rationale',primary_checks:'Initial assessments combined',independent_checks:'Additional assessments combined',successor_checks:'Successor assessments'}); evidence();
        (b.response_dispositions || []).forEach((entry,index) => {
          add('response_dispositions','Response considered',entry.response_ref,['response_dispositions',index,'response_ref']);
          add('response_dispositions','Reason for disposition of returned judgments',entry.rationale,['response_dispositions',index,'rationale']);
        });
        if (superseded.has(key) || latest.get(looseKey(row.ref))?.ref.version !== row.ref.version) notices.push('Earlier combined assessment retained for context.');
        add('supersedes','Earlier combined assessment replaced'); break;
      case 'reuse_decisions':
        take({check_ref:'Assessment considered',decision:'Assessment reuse outcome',rationale:'Consequential assessment reuse rationale'});
        id('source_review_id','source_reviews','Source context review'); evidence(); break;
      case 'identity_maps':
        id('response_id','responses','Returned review material');
        (b.entries || []).forEach((entry,index) => {
          add('entries','Affected mathematical material',entry.new_refs,['entries',index,'new_refs']);
          add('entries','Interpretation rationale',entry.rationale,['entries',index,'rationale']);
        }); add('note','Interpretation note'); break;
      default:
        take(COMPATIBLE_FIELDS);
        notices.push('This older record shape has a limited scientific display. Compatible saved scientific fields are shown; the full source record remains in the frozen artifact.');
    }
    const result = {title:title(row), fields, notices};
    cache.set(key,result); return result;
  }

  function valueText(value, seen = new Set()) {
    if (value == null) return '';
    if (typedRef(value)) {
      const row = resolve(value);
      if (!row) return 'Referenced material unavailable';
      const key = refKey(row.ref);
      if (seen.has(key)) return title(row);
      const next = new Set(seen).add(key), b = row.body;
      // References contribute their name and direct scientific context. Walking
      // every connected assessment would turn each hit into the whole report.
      const context = [b.statement, row.ref.collection === 'anchors' ? b.excerpt : null];
      if (row.ref.collection === 'scopes') context.push(b.assumptions, b.binders, b.conditions);
      return [title(row), ...context.map(entry => valueText(entry,next))].join(' ');
    }
    if (Array.isArray(value)) return value.map(entry => valueText(entry,seen)).join(' ');
    if (object(value)) return Object.values(value).map(entry => valueText(entry,seen)).join(' ');
    return String(value);
  }
  function text(value) {
    const row = resolve(value), selected = record(value), seen = new Set(row ? [refKey(row.ref)] : []);
    return [selected.title, ...selected.fields.map(field => valueText(field.value,seen)), ...selected.notices].filter(nonempty).join(' ');
  }
  return {record,title,text,resolve};
}
