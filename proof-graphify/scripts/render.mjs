// Proof-specific adapter for the vendored Archify viewer. See THIRD_PARTY_NOTICES.md.
// Input is the validated, MathML-enriched dataset produced by proof_overview.py.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { esc, textUnits } from './paper_core/renderer/assets/archify/utils.mjs';
import { KINDS as kinds, BOX as box, archifyPage, resultsNavigation, viewControls, scientificSearchPanel, readerRuntime, readerSearchData, readingSection, sourceDisclosure, mathDisplayNotes } from './paper_core/renderer/scientific_reader.mjs';
import { scanHtml, textOf, decodeEntities } from './paper_core/renderer/html_scan.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const useTypes = { dependency: 'Dependency', definition: 'Definition', proof_argument: 'Proof argument' };
// Intermediate kinds are never nodes: the major-only palette above keeps
// rejecting them as items, and they validate as owner-tagged details only.
const detailKinds = { equation: 'Equation', claim: 'Claim', derivation: 'Derivation' };

function jsonForScript(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
}

function safeHref(value) {
  if (typeof value !== 'string' || /[\u0000-\u0020]/u.test(value)) return '';
  return /^(?:https?:\/\/|file:\/\/\/|#)/i.test(value) ? value : '';
}

function formulaHtml(markup) {
  return String(markup).replace(/<math\b[\s\S]*?<\/math>/g, (math) => `<span class="proof-formula${/\bdisplay="block"/.test(math) ? ' proof-formula-block' : ''}">${math}</span>`);
}

function preparedDataset(input) {
  if (!input || input.schema_version !== 3) throw new Error('Prepared input requires schema_version 3.');
  if (!Array.isArray(input.items) || !Array.isArray(input.uses) || !input.items.length) {
    throw new Error('Prepared input needs nonempty items and a uses array.');
  }
  if (!Array.isArray(input.details) || !Array.isArray(input.detail_uses)) {
    throw new Error('Prepared input needs details and detail_uses arrays, empty when no intermediate steps are recorded.');
  }
  const ids = new Set();
  for (const item of input.items) {
    if (!item || !/^[a-zA-Z][a-zA-Z0-9_.:-]*$/.test(item.id || '') || ids.has(item.id)) {
      throw new Error('Each item needs a unique safe identifier.');
    }
    if (!Object.hasOwn(kinds, item.kind) || !item.label || typeof item.statement_html !== 'string') {
      throw new Error(`Item ${item.id} needs kind, label, and prepared statement_html.`);
    }
    ids.add(item.id);
  }
  const useIds = new Set();
  const uses = input.uses.map((use, index) => {
    if (!use || !ids.has(use.from) || !ids.has(use.to) || !use.reason) {
      throw new Error(`Dependency ${index + 1} needs valid endpoints and a reason.`);
    }
    const id = use.id || `use-${index + 1}`;
    if (!/^[a-zA-Z][a-zA-Z0-9_.:-]*$/.test(id) || useIds.has(id)) throw new Error('Dependency identifiers must be safe and unique.');
    useIds.add(id);
    const type = use.type || 'dependency';
    if (!Object.hasOwn(useTypes, type)) throw new Error(`Dependency ${id} has an unsupported type.`);
    if (use.regime !== undefined && (typeof use.regime !== 'string' || !use.regime.trim())) throw new Error(`Dependency ${id} needs a nonempty regime.`);
    return { ...use, id, type };
  });
  const detailIds = new Set();
  const details = input.details.map((detail) => {
    if (!detail || !/^[a-zA-Z][a-zA-Z0-9_.:-]*$/.test(detail.id || '') || ids.has(detail.id) || detailIds.has(detail.id)) {
      throw new Error('Each detail needs a unique safe identifier distinct from every item.');
    }
    if (!Object.hasOwn(detailKinds, detail.kind) || !detail.label || typeof detail.statement_html !== 'string') {
      throw new Error(`Detail ${detail.id} needs an intermediate kind (equation, claim, or derivation), label, and prepared statement_html.`);
    }
    if (!ids.has(detail.owner)) throw new Error(`Detail ${detail.id} needs an owner naming an existing major item.`);
    detailIds.add(detail.id);
    return detail;
  });
  details.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const endpoints = new Set([...ids, ...detailIds]);
  const detailUses = input.detail_uses.map((use, index) => {
    // An intermediate row may reference itself: the edge stays an annotation
    // in its owner's panel and never enters the graph. The major-major check
    // below keeps every major-major reference in the visible graph.
    if (!use || !endpoints.has(use.from) || !endpoints.has(use.to) || !use.reason) {
      throw new Error(`Detail use ${index + 1} needs endpoints among items and details, and a reason.`);
    }
    if (ids.has(use.from) && ids.has(use.to)) {
      throw new Error(`Detail use ${use.id || index + 1} joins two major items; record it as an ordinary use.`);
    }
    const id = use.id || `detail-use-${index + 1}`;
    if (!/^[a-zA-Z][a-zA-Z0-9_.:-]*$/.test(id) || useIds.has(id)) throw new Error('Detail use identifiers must be safe and distinct from graph use identifiers.');
    useIds.add(id);
    const type = use.type || 'dependency';
    if (!Object.hasOwn(useTypes, type)) throw new Error(`Detail use ${id} has an unsupported type.`);
    if (use.regime !== undefined && (typeof use.regime !== 'string' || !use.regime.trim())) throw new Error(`Detail use ${id} needs a nonempty regime.`);
    return { ...use, id, type };
  });
  const groupKinds = new Map();
  for (const use of [...uses, ...detailUses]) {
    if (use.group === undefined || use.group === null) continue;
    if (typeof use.group.id !== 'string' || !use.group.id.trim() || !['joint', 'cases'].includes(use.group.kind)) {
      throw new Error(`Use ${use.id} needs a group with a name and kind joint or cases.`);
    }
    const prior = groupKinds.get(use.group.id);
    if (prior !== undefined && prior !== use.group.kind) {
      throw new Error(`Group ${use.group.id} mixes ${prior} and ${use.group.kind}; one group id keeps one consistent kind.`);
    }
    groupKinds.set(use.group.id, use.group.kind);
  }
  if (input.main_items !== undefined && (!Array.isArray(input.main_items) || !input.main_items.length || new Set(input.main_items).size !== input.main_items.length || input.main_items.some((id) => !ids.has(id)))) throw new Error('main_items must contain distinct existing item identifiers.');
  if (input.graph_mode !== undefined && !['dag', 'cyclic', 'index'].includes(input.graph_mode)) throw new Error('graph_mode must be dag, cyclic or index.');
  if (input.math_diagnostics !== undefined && (!Array.isArray(input.math_diagnostics) || input.math_diagnostics.some((entry) => !entry || typeof entry.id !== 'string' || typeof entry.field !== 'string' || typeof entry.reason !== 'string' || typeof entry.excerpt !== 'string'))) throw new Error('math_diagnostics entries need id, field, excerpt, and reason strings.');
  return { ...input, uses, details, detail_uses: detailUses };
}

// Detail rows ride along with both graph shapes so panels can render them
// without touching layout: detailsByOwner is id-sorted, detailUses untouched.
function detailIndex(data) {
  const details = new Map((data.details || []).map((row) => [row.id, row]));
  const detailsByOwner = new Map(data.items.map((item) => [item.id, []]));
  for (const row of details.values()) detailsByOwner.get(row.owner).push(row);
  const groupLabels = new Map();
  for (const use of [...data.uses, ...(data.detail_uses || [])]) {
    if (use.group && !groupLabels.has(use.group.id)) {
      groupLabels.set(use.group.id, `${use.group.kind === 'joint' ? 'Joint inputs' : 'Alternative cases'} ${groupLabels.size + 1}`);
    }
  }
  return { details, detailsByOwner, detailUses: data.detail_uses || [], groupLabels };
}

function indexGraph(data) {
  const nodes = new Map(data.items.map((item) => [item.id, item]));
  const incoming = new Map(data.items.map((item) => [item.id, []]));
  const outgoing = new Map(data.items.map((item) => [item.id, []]));
  data.uses.forEach((use) => { incoming.get(use.to).push(use); outgoing.get(use.from).push(use); });
  return { nodes, incoming, outgoing, ...detailIndex(data) };
}

// Strongly connected groups determine layout ranks only. All authored nodes
// and directed uses remain separate; no edge is removed or reversed.
function stronglyConnected(nodes, incoming, outgoing) {
  const seen = new Set(), finished = [];
  for (const start of nodes.keys()) {
    if (seen.has(start)) continue;
    seen.add(start);
    const stack = [{ id: start, index: 0 }];
    while (stack.length) {
      const frame = stack.at(-1), uses = outgoing.get(frame.id);
      if (frame.index >= uses.length) { finished.push(frame.id); stack.pop(); continue; }
      const target = uses[frame.index++].to;
      if (!seen.has(target)) { seen.add(target); stack.push({ id: target, index: 0 }); }
    }
  }
  const assigned = new Set(), groups = [];
  for (const start of finished.reverse()) {
    if (assigned.has(start)) continue;
    const members = [start]; assigned.add(start);
    for (let index = 0; index < members.length; index += 1) {
      for (const use of incoming.get(members[index])) {
        if (!assigned.has(use.from)) { assigned.add(use.from); members.push(use.from); }
      }
    }
    members.sort((a, b) => nodes.get(a).order - nodes.get(b).order);
    groups.push({ members, rank: 0, incoming: 0, outgoing: [] });
  }
  return groups;
}

// DAGs retain their existing longest-path layers and stable barycentres.
// Cyclic groups expand into stable columns with exterior lanes for return uses.
function layoutGraph(data) {
  const nodes = new Map(data.items.map((item, order) => [item.id, { ...item, order, rank: 0 }]));
  const incoming = new Map(data.items.map((item) => [item.id, []]));
  const outgoing = new Map(data.items.map((item) => [item.id, []]));
  data.uses.forEach((use) => { incoming.get(use.to).push(use); outgoing.get(use.from).push(use); });
  const groups = stronglyConnected(nodes, incoming, outgoing), groupOf = new Map();
  groups.forEach((group) => group.members.forEach((id) => groupOf.set(id, group)));
  for (const use of data.uses) {
    const from = groupOf.get(use.from), to = groupOf.get(use.to);
    if (from !== to) { from.outgoing.push(to); to.incoming += 1; }
  }
  const queue = groups.filter((group) => !group.incoming);
  for (let index = 0; index < queue.length; index += 1) {
    const group = queue[index];
    group.members.forEach((id, offset) => { nodes.get(id).rank = group.rank + offset; });
    for (const target of group.outgoing) {
      target.rank = Math.max(target.rank, group.rank + group.members.length);
      target.incoming -= 1;
      if (!target.incoming) queue.push(target);
    }
  }
  const cycles = groups.filter((group) => group.members.length > 1 || outgoing.get(group.members[0]).some((use) => use.to === group.members[0])).map((group) => {
    const members = new Set(group.members);
    return { item_ids: group.members, item_labels: group.members.map((id) => nodes.get(id).label),
      use_ids: data.uses.filter((use) => members.has(use.from) && members.has(use.to)).map((use) => use.id) };
  }).sort((a, b) => nodes.get(a.item_ids[0]).order - nodes.get(b.item_ids[0]).order);
  // Disconnected groups occupy separate regions. Within a group,
  // integral rows leave shared clear corridors for skipped-layer connections.
  const components = [], assigned = new Set();
  nodes.forEach((start) => {
    if (assigned.has(start.id)) return;
    const ids = [start.id]; assigned.add(start.id);
    for (let i = 0; i < ids.length; i += 1) {
      for (const use of [...incoming.get(ids[i]), ...outgoing.get(ids[i])]) {
        const other = use.from === ids[i] ? use.to : use.from;
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
          const parents = incoming.get(node.id).map((use) => nodes.get(use.from).position);
          return parents.length ? parents.reduce((sum, value) => sum + value, 0) / parents.length : node.position;
        };
        ranks[r].sort((a, b) => centre(a) - centre(b) || a.order - b.order);
        ranks[r].forEach((node, index) => { node.position = index; });
      }
    }
    const memberIds = new Set(ids);
    const returns = data.uses.filter((use) => memberIds.has(use.from) && nodes.get(use.to).rank <= nodes.get(use.from).rank);
    components.push({ members, ranks, returns, rowCount: Math.max(...ranks.map((rank) => rank.length)) });
  });
  const longUses = data.uses.filter((use) => nodes.get(use.to).rank > nodes.get(use.from).rank + 1);
  const headingHeight = components.length > 1 ? 32 : 0, gapX = 24, gapY = 68;
  components.forEach((component) => {
    component.width = box.margin * 2 + (component.ranks.length - 1) * box.column + box.w;
    component.height = headingHeight + (component.returns.length ? 24 + component.returns.length * 10 : 0)
      + (component.rowCount - 1) * box.row + box.h;
  });
  // Pack whole groups in stable rows, preserving their internal ranks and routes.
  const widest = Math.max(...components.map((component) => component.width));
  const area = components.reduce((sum, component) => sum + component.width * (component.height + gapY), 0);
  const rowWidth = components.length > 1 ? Math.max(widest, Math.sqrt(area * 1.5)) : widest;
  let left = 0, top = box.margin, rowBottom = top, width = 0;
  components.forEach((component, componentIndex) => {
    if (left && left + component.width > rowWidth) {
      left = 0;
      top = rowBottom + gapY;
    }
    component.left = left;
    component.top = top;
    component.laneTop = top + headingHeight;
    component.nodeTop = component.laneTop + (component.returns.length ? 24 + component.returns.length * 10 : 0);
    component.ranks.forEach((rank, r) => rank.forEach((node, index) => {
      node.x = left + box.margin + r * box.column;
      node.y = component.nodeTop + index * box.row;
      node.width = box.w; node.height = box.h; node.component = componentIndex;
    }));
    component.bottom = component.nodeTop + (component.rowCount - 1) * box.row + box.h;
    rowBottom = Math.max(rowBottom, component.bottom);
    width = Math.max(width, left + component.width);
    left += component.width + gapX;
  });
  const adjacentGapUses = new Map();
  // Retain the outgoing-map order used by the original per-route scan.
  for (const uses of outgoing.values()) for (const use of uses) {
    const from = nodes.get(use.from), to = nodes.get(use.to);
    if (to.rank !== from.rank + 1) continue;
    const key = `${from.component}:${from.rank}:${to.rank}`;
    if (!adjacentGapUses.has(key)) adjacentGapUses.set(key, []);
    adjacentGapUses.get(key).push(use);
  }
  return {
    nodes, components, incoming, outgoing, longUses, adjacentGapUses, cycles, ...detailIndex(data),
    width,
    height: rowBottom + box.margin,
  };
}

function roundedPath(points, radius = 8) {
  const commands = [`M ${points[0][0]} ${points[0][1]}`];
  for (let i = 1; i < points.length - 1; i += 1) {
    const [px, py] = points[i - 1], [cx, cy] = points[i], [nx, ny] = points[i + 1];
    const before = Math.hypot(cx - px, cy - py), after = Math.hypot(nx - cx, ny - cy);
    const r = Math.min(radius, before / 2, after / 2);
    if (r < 1) { commands.push(`L ${cx} ${cy}`); continue; }
    commands.push(`L ${cx - (cx - px) / before * r} ${cy - (cy - py) / before * r}`);
    commands.push(`Q ${cx} ${cy} ${cx + (nx - cx) / after * r} ${cy + (ny - cy) / after * r}`);
  }
  commands.push(`L ${points.at(-1).join(' ')}`);
  return commands.join(' ');
}

function edgePoints(use, graph) {
  const a = graph.nodes.get(use.from), b = graph.nodes.get(use.to);
  const outs = graph.outgoing.get(a.id), ins = graph.incoming.get(b.id);
  const port = (node, records) => node.y + 13 + (records.indexOf(use) + 1) / (records.length + 1) * (box.h - 26);
  const start = [a.x + box.w, port(a, outs)], end = [b.x, port(b, ins)];
  if (b.rank <= a.rank) {
    const component = graph.components[a.component], lane = component.returns.indexOf(use);
    const rail = component.laneTop + 10 + lane * 10;
    const exit = start[0] + 12 + (outs.indexOf(use) + 1) / (outs.length + 1) * 12;
    const enter = end[0] - 12 - (ins.indexOf(use) + 1) / (ins.length + 1) * 12;
    return [start, [exit, start[1]], [exit, rail], [enter, rail], [enter, end[1]], end];
  }
  const longIndex = graph.longUses.indexOf(use);
  if (longIndex >= 0) {
    const component = graph.components[a.component];
    const target = (start[1] + end[1]) / 2;
    const corridors = Array.from({ length: component.rowCount }, (_, row) => component.nodeTop + row * box.row + box.h + (box.row - box.h) / 2);
    const rail = corridors.reduce((best, value) => Math.abs(value - target) < Math.abs(best - target) ? value : best);
    const exit = start[0] + 18 + (outs.indexOf(use) + 1) / (outs.length + 1) * 24;
    const enter = end[0] - 18 - (ins.indexOf(use) + 1) / (ins.length + 1) * 24;
    return [start, [exit, start[1]], [exit, rail], [enter, rail], [enter, end[1]], end];
  }
  const sameGap = graph.adjacentGapUses.get(`${a.component}:${a.rank}:${b.rank}`);
  const channel = start[0] + 25 + (sameGap.indexOf(use) + 1) / (sameGap.length + 1) * (box.column - box.w - 50);
  return [start, [channel, start[1]], [channel, end[1]], end];
}

function captionLines(text, limit = 25) {
  const words = String(text || '').split(/\s+/u).filter(Boolean);
  const lines = [''];
  for (const word of words) {
    const at = lines.length - 1;
    if (lines[at] && textUnits(`${lines[at]} ${word}`) > limit) lines.push(word);
    else lines[at] += (lines[at] ? ' ' : '') + word;
  }
  if (lines.length > 2) return [lines[0], `${lines[1].slice(0, limit - 1)}…`];
  return lines;
}

function renderQualifiers(qualifiers, graph) {
  const occupied = [...graph.nodes.values()].map((node) => ({ x: node.x - 6, y: node.y - 6, w: box.w + 12, h: box.h + 12 }));
  if (graph.components.length > 1) graph.components.forEach((component) =>
    occupied.push({ x: component.left + 22, y: component.top - 3, w: component.width - 44, h: 26 }));
  const intersects = (a, b) => a.x < b.x + b.w + 3 && a.x + a.w + 3 > b.x && a.y < b.y + b.h + 3 && a.y + a.h + 3 > b.y;
  return qualifiers.map(({ use, description, labels, points }) => {
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
      // Dense annotations can use the free margin with a visible leader. No
      // relationship is silently omitted or replaced with a shortcut.
      const anchor = points[Math.floor(points.length / 2)];
      for (let y = 18 + h / 2; !placed && y < graph.height - h / 2; y += h + 7) {
        for (let x = 8 + w / 2; !placed && x < graph.width - w / 2; x += w + 8) {
          const rect = { x: x - w / 2, y: y - h / 2, w, h };
          if (!occupied.some((entry) => intersects(rect, entry))) placed = { x, y, rect, anchor };
        }
      }
    }
    if (!placed) {
      const anchor = points[Math.floor(points.length / 2)], x = Math.min(graph.width - w / 2 - 8, Math.max(w / 2 + 8, anchor[0])), y = graph.height + h / 2;
      placed = { x, y, anchor, rect: { x: x - w / 2, y: y - h / 2, w, h } };
      graph.height += h + 12;
    }
    occupied.push(placed.rect);
    const { x, y, anchor } = placed, leader = Math.hypot(x - anchor[0], y - anchor[1]) > 3;
    return `${leader ? `<g aria-hidden="true" class="proof-badge-decoration"><path class="proof-badge-leader" d="M ${anchor[0]} ${anchor[1]} L ${x} ${y}"/><circle class="proof-badge-anchor" cx="${anchor[0]}" cy="${anchor[1]}" r="2"/></g>` : ''}<g class="proof-edge-badge" data-proof-use="${esc(use.id)}" tabindex="0" role="button" aria-label="${esc(description)}"><title>${esc(description)}</title><rect x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="4"/>${labels.map((label, i) => `<text x="${x}" y="${y - (labels.length - 1) * 7 + i * 14 + 3}" text-anchor="middle">${esc(label)}</text>`).join('')}</g>`;
  }).join('');
}

function renderSvg(data, graph) {
  const qualifiers = [];
  const cycleUses = new Set(graph.cycles.flatMap((group) => group.use_ids));
  const cycleItems = new Set(graph.cycles.flatMap((group) => group.item_ids));
  const edges = data.uses.map((use, index) => {
    const points = edgePoints(use, graph);
    const issued = Boolean(use.issue);
    const group = use.group || null;
    // R3 badge fallback: grouped uses keep their own paths and disclose the
    // group with a badge; the forked single-arrowhead connector spike is
    // deferred. Every use id therefore appears exactly once in the SVG.
    const qualification = `${useTypes[use.type]}${use.regime ? `; only in regime: ${use.regime}` : ''}${group ? `; ${graph.groupLabels.get(group.id)}` : ''}${cycleUses.has(use.id) ? '; part of a recorded cycle' : ''}`;
    const description = `${graph.nodes.get(use.from).label} to ${graph.nodes.get(use.to).label}. ${qualification}: ${use.reason}${issued ? ` Issue: ${use.issue}` : ''}`;
    if (use.type !== 'dependency' || use.regime || group) {
      const labels = [use.type !== 'dependency' ? useTypes[use.type] : '', use.regime ? `If: ${use.regime}` : '', group ? graph.groupLabels.get(group.id) : ''].filter(Boolean).map((label) => textUnits(label) > 17 ? `${label.slice(0, 15)}…` : label);
      qualifiers.push({ use, description, labels, points });
    }
    return `<path data-edge-from="${esc(use.from)}" data-edge-to="${esc(use.to)}" data-edge-key="${index}" data-edge-id="${esc(use.id)}" data-use-type="${esc(use.type)}"${use.regime ? ` data-use-regime="${esc(use.regime)}"` : ''} data-edge-label="${esc(`${qualification}: ${use.reason}`)}" data-composition-points="${points.map((point) => point.join(',')).join(';')}" class="proof-edge a-default${issued ? ' proof-uncertain' : ''}${use.type === 'proof_argument' ? ' proof-argument-edge' : ''}" d="${roundedPath(points)}" stroke-width="1.6" marker-end="url(#proof-arrow)"><title>${esc(description)}</title></path>`;
  }).join('\n');
  const nodes = [...graph.nodes.values()].map((node) => {
    const caption = captionLines(node.caption), cx = node.x + box.w / 2;
    const labelSize = Math.max(12, Math.min(14, 150 / Math.max(1, textUnits(node.label)) / 0.61));
    const aria = `${node.label}. ${node.caption || kinds[node.kind][0]}. Select for statement and connections.`;
    return `<g id="node-${esc(node.id)}" data-node-id="${esc(node.id)}" data-node-kind="${esc(node.kind)}" data-node-label="${esc(node.label)}" data-node-sublabel="${esc(node.caption || '')}" data-node-context="${esc(node.source_display || '')}" tabindex="0" role="button" aria-pressed="false" aria-label="${esc(aria)}">
      <title>${esc(`${node.label}: ${node.caption || ''}`)}</title>
      <rect x="${node.x}" y="${node.y}" width="${box.w}" height="${box.h}" rx="6" class="c-mask"/>
      <rect x="${node.x}" y="${node.y}" width="${box.w}" height="${box.h}" rx="6" class="proof-node c-${esc(node.kind)}" stroke-width="1.5"/>
      <text data-node-label="" x="${cx}" y="${node.y + 23}" class="t-primary" font-size="${labelSize}" font-weight="600" text-anchor="middle"${textUnits(node.label) * labelSize * 0.61 > 154 ? ' textLength="154" lengthAdjust="spacingAndGlyphs"' : ''}>${esc(node.label)}</text>
      ${caption.map((line, i) => `<text data-detail="context" x="${cx}" y="${node.y + 41 + 13 * i}" class="t-muted" font-size="11" text-anchor="middle">${esc(line)}</text>`).join('')}
    </g>`;
  }).join('\n');
  const qualifierSvg = renderQualifiers(qualifiers, graph);
  return `<svg viewBox="0 0 ${graph.width} ${graph.height}" role="img" class="proof-svg" aria-labelledby="archify-diagram-title archify-diagram-description" data-preset="classic" data-quality-profile="standard">
    <title id="archify-diagram-title">${esc(data.title)}</title><desc id="archify-diagram-description">Selected main results, important prerequisites, and their recorded connections. This overview does not certify the proof.</desc>
    <defs><marker id="proof-arrow" markerWidth="8" markerHeight="6" refX="7.2" refY="3" orient="auto"><path d="M0 0 L8 3 L0 6 Z" class="proof-arrowhead"/></marker><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0 L0 0 0 40" class="c-grid" stroke-width="0.5"/></pattern></defs>
    <rect width="100%" height="100%" fill="url(#grid)"/>
    ${graph.components.length > 1 ? graph.components.map((component) => {
      const terminal = component.members.filter((node) => !graph.outgoing.get(node.id).length);
      const ends = (terminal.length ? terminal : component.members.filter((node) => cycleItems.has(node.id))).map((node) => node.label);
      const title = component.members.length === 1 && !component.returns.length ? 'Unconnected result' : `Linked argument: ${ends.join(', ')}`;
      const limit = Math.floor((component.width - 2 * box.margin) / (12 * 0.61));
      let label = title;
      if (textUnits(label) > limit) {
        while (textUnits(label) > limit - 1) label = [...label].slice(0, -1).join('');
        label += '…';
      }
      return `<g class="proof-component" aria-hidden="true"><title>${esc(title)}</title><path d="M ${component.left + 22} ${component.top + 16} H ${component.left + component.width - 22}"/><text x="${component.left + box.margin}" y="${component.top + 9}">${esc(label)}</text></g>`;
    }).join('') : ''}${edges}${qualifierSvg}${nodes}
  </svg>`;
}

// These checks inspect the planned boxes and orthogonal route segments only.
// They do not claim text, badge, browser, or perceptual layout validation.
function geometryReceipt(data, graph) {
  const diagnostics = [], nodes = [...graph.nodes.values()];
  const messages = {
    'geometry/nonfinite-node': 'A displayed item has invalid coordinates or dimensions.',
    'geometry/node-clipping': 'A displayed item extends beyond the SVG viewBox.',
    'geometry/node-overlap': 'Two displayed item boxes overlap.',
    'geometry/nonfinite-route': 'A recorded use has a nonfinite route coordinate.',
    'geometry/route-clipping': 'A recorded use extends beyond the SVG viewBox.',
    'geometry/route-not-orthogonal': 'A recorded use has an unexpected diagonal route segment.',
    'geometry/route-endpoint': 'A recorded use does not join its recorded source and target boxes.',
    'geometry/route-through-node': 'A recorded use crosses an unrelated item box.',
  };
  const issue = (code, subject, evidence) => diagnostics.push({ code, severity: 'error', message: messages[code], subject, evidence, supportedFixes: [] });
  for (const node of nodes) {
    if (![node.x, node.y, node.width, node.height].every(Number.isFinite) || node.width <= 0 || node.height <= 0) {
      issue('geometry/nonfinite-node', { item: node.id }, {});
    } else if (node.x < 0 || node.y < 0 || node.x + node.width > graph.width || node.y + node.height > graph.height) {
      issue('geometry/node-clipping', { item: node.id }, { x: node.x, y: node.y, width: node.width, height: node.height, viewBox: [graph.width, graph.height] });
    }
  }
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i], b = nodes[j];
      if (a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y) {
        issue('geometry/node-overlap', { items: [a.id, b.id] }, {});
      }
    }
  }
  for (const use of data.uses) {
    const points = edgePoints(use, graph);
    const source = graph.nodes.get(use.from), target = graph.nodes.get(use.to);
    const start = points[0], end = points.at(-1);
    if (start[0] !== source.x + source.width || start[1] <= source.y || start[1] >= source.y + source.height
        || end[0] !== target.x || end[1] <= target.y || end[1] >= target.y + target.height) {
      issue('geometry/route-endpoint', { use: use.id }, { start, end });
    }
    for (let i = 1; i < points.length; i += 1) {
      const [x1, y1] = points[i - 1], [x2, y2] = points[i];
      if (![x1, y1, x2, y2].every(Number.isFinite)) {
        issue('geometry/nonfinite-route', { use: use.id, segment: i - 1 }, {});
        continue;
      }
      if (x1 < 0 || x1 > graph.width || x2 < 0 || x2 > graph.width || y1 < 0 || y1 > graph.height || y2 < 0 || y2 > graph.height) {
        issue('geometry/route-clipping', { use: use.id, segment: i - 1 }, { from: points[i - 1], to: points[i] });
      }
      if (x1 !== x2 && y1 !== y2) issue('geometry/route-not-orthogonal', { use: use.id, segment: i - 1 }, {});
      for (const node of nodes) {
        if (node.id === use.from || node.id === use.to) continue;
        const horizontal = y1 === y2 && y1 > node.y && y1 < node.y + node.height && Math.max(x1, x2) > node.x && Math.min(x1, x2) < node.x + node.width;
        const vertical = x1 === x2 && x1 > node.x && x1 < node.x + node.width && Math.max(y1, y2) > node.y && Math.min(y1, y2) < node.y + node.height;
        if (horizontal || vertical) issue('geometry/route-through-node', { use: use.id, item: node.id, segment: i - 1 }, { from: points[i - 1], to: points[i] });
      }
    }
  }
  const checks = ['finite_node_geometry', 'node_overlaps', 'node_clipping', 'finite_route_geometry', 'route_clipping', 'orthogonal_routes', 'recorded_route_endpoints', 'routes_through_unrelated_nodes'];
  return { status: diagnostics.length ? 'fail' : 'pass', checks, diagnostics, limits: 'Computed node boxes and orthogonal route segments only; text, badge placement, rounded corners, browser behavior, and perceptual review are not checked.' };
}

function representationReceipt(data, html, graphMode) {
  const attributes = (tag) => Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map((match) => [match[1], match[2]]));
  const nodes = [], uses = [];
  // Inspect the emitted drawing or index, not JSON, templates, or claimed counts.
  const indexElement = graphMode === 'index' ? scanHtml(html).elements.find(element => element.tag === 'details' && element.attrs.id === 'proof-full-index') : null;
  const representation = graphMode !== 'index' ? html.match(/<svg\b[\s\S]*?<\/svg>/)?.[0] || '' : indexElement ? html.slice(indexElement.start,indexElement.closeEnd) : '';
  for (const match of representation.matchAll(graphMode !== 'index' ? /<(?:g|path)\b[^>]*>/g : /<article\b[^>]*>/g)) {
    const attrs = attributes(match[0]);
    if (graphMode !== 'index') {
      if (Object.hasOwn(attrs, 'data-node-id')) nodes.push(attrs['data-node-id']);
      if (Object.hasOwn(attrs, 'data-edge-id')) uses.push({ id: attrs['data-edge-id'], from: attrs['data-edge-from'], to: attrs['data-edge-to'] });
    } else {
      if (Object.hasOwn(attrs, 'data-proof-index-item')) nodes.push(attrs['data-proof-index-item']);
      if (Object.hasOwn(attrs, 'data-proof-index-use')) uses.push({ id: attrs['data-proof-index-use'], from: attrs['data-proof-from'], to: attrs['data-proof-to'] });
    }
  }
  // Detail rows and detail edges live inside their owner's static index
  // article; the interactive panel duplicates them inside inert templates.
  const stripped = html.replace(/<template\b[\s\S]*?<\/template>/g, '');
  const articles = {};
  for (const match of stripped.matchAll(/<article\b[^>]*id="proof-index-item-[^"]*"[\s\S]*?<\/article>/g)) {
    articles[attributes(match[0].match(/<article\b[^>]*>/)[0])['data-proof-index-item']] = match[0];
  }
  const details = [], detailUses = [];
  for (const match of stripped.matchAll(/<[a-z]+\b[^>]*>/g)) {
    const attrs = attributes(match[0]);
    if (Object.hasOwn(attrs, 'data-proof-detail')) details.push(attrs['data-proof-detail']);
    if (Object.hasOwn(attrs, 'data-proof-detail-use')) detailUses.push({ id: attrs['data-proof-detail-use'], from: attrs['data-proof-from'], to: attrs['data-proof-to'] });
  }
  const detailRows = new Map((data.details || []).map((row) => [row.id, row]));
  // Mirror of the rendering rule: an edge is annotated at its detail "from"
  // endpoint, or at its detail "to" endpoint when only that end is a detail.
  const detailUseOwner = (use) => (detailRows.has(use.from) ? detailRows.get(use.from) : detailRows.get(use.to) || {}).owner;
  const contained = (rows, marker, ownerOf) => rows.every((row) => (articles[ownerOf(row)] || '').includes(`${marker}="${row.id}"`));
  const expectedNodes = data.items.map(({ id }) => id).sort();
  const expectedDetails = (data.details || []).map(({ id }) => id).sort();
  const normalizedUses = (records) => records.map(({ id, from, to }) => ({ id, from, to })).sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  const status = JSON.stringify(nodes.sort()) === JSON.stringify(expectedNodes)
    && JSON.stringify(normalizedUses(uses)) === JSON.stringify(normalizedUses(data.uses))
    && JSON.stringify(details.slice().sort()) === JSON.stringify(expectedDetails)
    && JSON.stringify(normalizedUses(detailUses)) === JSON.stringify(normalizedUses(data.detail_uses || []))
    && contained(data.details || [], 'data-proof-detail', (row) => row.owner)
    && contained(data.detail_uses || [], 'data-proof-detail-use', detailUseOwner)
    ? 'pass' : 'fail';
  return { status, expected_items: data.items.length, rendered_items: nodes.length, expected_uses: data.uses.length, rendered_uses: uses.length, expected_details: expectedDetails.length, rendered_details: details.length, expected_detail_uses: (data.detail_uses || []).length, rendered_detail_uses: detailUses.length, representation: graphMode !== 'index' ? 'svg' : 'index', item_ids: nodes, uses: normalizedUses(uses), detail_ids: details, detail_uses: normalizedUses(detailUses) };
}

function sourceHtml(record) {
  const label = record.source_display || 'Source location not supplied';
  const href = safeHref(record.source_href);
  return `<p class="proof-source">${href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : esc(label)}</p>`;
}

function passagesHtml(record) {
  const passages = Array.isArray(record.source_passages) && record.source_passages.length
    ? record.source_passages
    : record.source_excerpt ? [{ source_display: record.source_display, source_excerpt: record.source_excerpt }] : [];
  if (!passages.length) return '';
  return `<div class="proof-passages">${passages.map((passage,index) => {
    const verification = typeof passage.verification === 'string' ? { status: passage.verification } : passage.verification || {};
    const status = verification.status === 'unverified' ? 'Source location is not fully verified.' : verification.status && verification.status !== 'checked' ? `Source location: ${String(verification.status).replaceAll('_', ' ')}.` : '';
    const authoredRole = passage.role ? String(passage.role).replaceAll('_', ' ') : 'Source';
    const role = authoredRole[0].toUpperCase() + authoredRole.slice(1);
    const extractionNote = passage.source_media_type === 'application/pdf' && passage.source_excerpt
      ? '<p class="proof-hint">Approximate text extracted from the PDF. Check the original page for formulas and layout.</p>' : '';
    const key = `${record.from && record.to ? 'use' : record.owner ? 'detail' : 'item'}:${record.id}:source:${index}`;
    return sourceDisclosure({title:`${role} passage${passage.source_display ? `: ${passage.source_display}` : ''}`,attrs:{'data-reader-search-key':key},bodyHtml:`${sourceHtml(passage)}${status ? `<p class="proof-hint">${esc(status)}</p>` : ''}${verification.note ? `<p class="proof-hint">${esc(verification.note)}</p>` : ''}${extractionNote}${passage.source_excerpt ? `<pre class="proof-excerpt">${esc(passage.source_excerpt)}</pre>` : '<p class="proof-hint">No source excerpt is available for this locator.</p>'}`});
  }).join('')}</div>`;
}

// Fidelity badges report source-comparison bookkeeping, never mathematical
// correctness: one neutral muted style, no sentiment colors.
function fidelityBadgeHtml(fidelity) {
  const state = fidelity || 'unreviewed';
  const labels = {
    unreviewed: 'Not yet compared with the source',
    matched: 'Compared with the source',
    needs_attention: 'Reviewed; source question unresolved',
    stale: 'Changed since the last comparison',
  };
  return `<span class="proof-fidelity" data-proof-fidelity="${esc(state)}">${esc(labels[state] || state)}</span>`;
}

function reviewLineHtml(row) {
  return `<p class="proof-review">${fidelityBadgeHtml(row.fidelity)}</p>${comparisonNoteHtml(row, false)}`;
}

function comparisonNoteHtml(row, evidence = false) {
  if (!row.comparison_note || evidence !== (row.fidelity === 'matched')) return '';
  const stale = row.fidelity === 'stale';
  return `<div class="proof-hint proof-comparison-note"><strong>${stale ? 'Earlier source comparison note' : 'Source comparison note'}</strong>${stale ? '<p>The source or argument context has changed since this comparison; the note does not establish agreement with the current version.</p>' : ''}<div class="proof-idea">${formulaHtml(row.comparison_note_html || esc(row.comparison_note))}</div></div>`;
}

function groupBadgeHtml(group, graph) {
  return `<span class="proof-group">${esc(graph.groupLabels.get(group.id))}</span>`;
}

function issueHtml(row) {
  return row.issue ? `<div class="proof-uncertainty">Open issue: ${formulaHtml(row.issue_html || esc(row.issue))}</div>` : '';
}

function relationHtml(use, graph, incoming) {
  const other = graph.nodes.get(incoming ? use.from : use.to);
  const setup = incoming && (other.kind === 'assumption' ? 'Assumed' : other.kind === 'definition' || use.type === 'definition' ? 'Declared setup' : '');
  return `<li class="proof-prerequisite-row" data-proof-relation-use="${esc(use.id)}"><button type="button" data-proof-focus="${esc(other.id)}">${esc(other.label)}</button>${setup ? ` <span class="proof-use-type">${setup}</span>` : ''} ${qualificationHtml(use, graph)}<div class="proof-contribution">${formulaHtml(use.reason_html || esc(use.reason))}</div>${issueHtml(use)}${fidelityBadgeHtml(use.fidelity)}${comparisonNoteHtml(use)} <button type="button" data-reader-open="use:${esc(use.id)}">Exact connection</button></li>`;
}

function prerequisitesHtml(incoming, graph) {
  const setup = [], results = [], other = [];
  for (const use of incoming) {
    const source = graph.nodes.get(use.from);
    if (use.type === 'definition' || ['assumption', 'definition'].includes(source.kind)) setup.push(use);
    else if (use.type === 'proof_argument' || ['lemma', 'proposition', 'theorem', 'corollary', 'external_result'].includes(source.kind)) results.push(use);
    else other.push(use);
  }
  const rows = (title, uses) => uses.length ? `<h5>${title}</h5><ul class="proof-prerequisite-list">${uses.map((use) => relationHtml(use, graph, true)).join('')}</ul>` : '';
  return incoming.length ? `${rows('Hypotheses and setup', setup)}${rows('Results and other inputs used', results)}${rows('Other recorded inputs', other)}<p class="proof-hint">These are recorded inputs to the argument. Their joint sufficiency has not been verified by this overview.</p>` : '<p>No prerequisite use is recorded in this overview.</p>';
}

function connectionEvidenceHtml(use, graph) {
  const label = `${graph.nodes.get(use.from).label} → ${graph.nodes.get(use.to).label}`;
  const regimeHtml = use.regime
    ? `<p class="proof-regime">Only in regime: ${formulaHtml(use.regime_html || esc(use.regime))}</p>`
    : '';
  return sourceDisclosure({
    title: `${label} (${useTypes[use.type]})`,
    attrs: {'data-proof-evidence-use': use.id},
    bodyHtml: `${regimeHtml}${comparisonNoteHtml(use, true)}${sourceHtml(use)}${passagesHtml(use)}`,
  });
}

function proofIdeaHtml(node) {
  return node.proof_idea ? `<div class="proof-idea">${formulaHtml(node.proof_idea_html || esc(node.proof_idea))}</div>` : '';
}

function qualificationHtml(use, graph) {
  return `<span class="proof-use-type">${esc(useTypes[use.type])}</span>${use.regime ? `<span class="proof-regime">Only in regime: ${formulaHtml(use.regime_html || esc(use.regime))}</span>` : ''}${use.group ? groupBadgeHtml(use.group, graph) : ''}`;
}

// A detail edge is annotated under its detail endpoint's sub-section: the
// "from" row when it is intermediate, otherwise the "to" row. Validation
// guarantees at least one intermediate endpoint, so each edge lands in
// exactly one owner's panel.
function detailAnchor(use, graph) {
  return graph.details.has(use.from) ? use.from : use.to;
}

function detailUseHtml(use, graph) {
  const label = (id) => (graph.nodes.get(id) || graph.details.get(id) || {}).label || id;
  return `<div class="proof-detail-use" data-proof-detail-use="${esc(use.id)}" data-proof-from="${esc(use.from)}" data-proof-to="${esc(use.to)}">${qualificationHtml(use, graph)} ${esc(label(use.from))} → ${esc(label(use.to))}<div>${formulaHtml(use.reason_html || esc(use.reason))}</div>${issueHtml(use)}${reviewLineHtml(use)}${comparisonNoteHtml(use, true)}${use.source_display ? `<small>${esc(use.source_display)}</small>` : ''}${passagesHtml(use)}<p class="proof-hint">This use refines the recorded argument at an intermediate step; it is not part of the overview graph.</p></div>`;
}

function detailSectionHtml(detail, graph) {
  const annotations = graph.detailUses.filter((use) => detailAnchor(use, graph) === detail.id);
  return `<section class="proof-detail" data-proof-detail="${esc(detail.id)}" data-reader-search-key="detail:${esc(detail.id)}"><h5><span class="proof-detail-kind">${esc(detailKinds[detail.kind])}</span> ${esc(detail.label)}${detail.caption ? `: ${esc(detail.caption)}` : ''}</h5><div class="proof-statement">${formulaHtml(detail.statement_html)}</div>${detail.proof_idea ? readingSection({role:'logic',title:'Proof idea',bodyHtml:proofIdeaHtml(detail)}) : ''}${issueHtml(detail)}${reviewLineHtml(detail)}${comparisonNoteHtml(detail, true)}${passagesHtml(detail)}${annotations.map((use) => detailUseHtml(use, graph)).join('')}</section>`;
}

function fullItemHtml(node, graph, { hover = false } = {}) {
  const incoming = graph.incoming.get(node.id), outgoing = graph.outgoing.get(node.id);
  if (hover) return `<strong>${esc(node.label)}</strong><p class="proof-hover-caption">${esc(node.caption || kinds[node.kind][0])}</p>${sourceHtml(node)}<p class="proof-hint">Click or press Enter for the statement and connections.</p>`;
  const details = graph.detailsByOwner.get(node.id) || [];
  const connections = [...new Map([...incoming, ...outgoing].map((use) => [use.id, use])).values()];
  return `
    ${readingSection({role:'statement',title:node.statement_form === 'synopsis' ? 'Statement synopsis' : 'Statement',attrs:{'data-reader-search-key':`item:${node.id}:statement`},bodyHtml:`<div class="proof-statement">${formulaHtml(node.statement_html)}</div>`})}
      ${readingSection({role:'source-comparison',title:'Source comparison',bodyHtml:`${reviewLineHtml(node)}${issueHtml(node)}`})}
      <div data-reader-search-key="item:${esc(node.id)}:logic">${node.proof_idea ? readingSection({role:'logic',title:'Proof idea',bodyHtml:`${proofIdeaHtml(node)}<p class="proof-hint">This explanation supplies no additional proof support.</p>`}) : ''}
      ${readingSection({role:'prerequisites',title:`Prerequisites (${incoming.length})`,bodyHtml:prerequisitesHtml(incoming, graph)})}</div>
      ${sourceDisclosure({title:`Used by (${outgoing.length})`,attrs:{'data-reader-search-key':`item:${node.id}:outgoing`},bodyHtml:outgoing.length ? `<ul class="proof-prerequisite-list">${outgoing.map((use) => relationHtml(use, graph, false)).join('')}</ul>` : '<p>No downstream use is recorded in this overview.</p>'})}
      ${sourceDisclosure({attrs:{'data-reader-search-key':`item:${node.id}:sources`},bodyHtml:`${comparisonNoteHtml(node, true)}${sourceHtml(node)}${Array.isArray(node.aliases) && node.aliases.length ? `<p class="proof-hint">Also identified as: ${node.aliases.map((alias) => esc(alias)).join(', ')}</p>` : ''}${passagesHtml(node)}${connections.length ? `<h5>Connection evidence</h5>${connections.map((use) => connectionEvidenceHtml(use, graph)).join('')}` : ''}`})}
      ${details.length ? `<div class="proof-details"><h4>Intermediate steps (${details.length})</h4>${details.map((detail) => detailSectionHtml(detail, graph)).join('')}</div>` : ''}
      `.trim();
}

function fullUseHtml(use, graph) {
  return `<h4>${esc(graph.nodes.get(use.from).label)} → ${esc(graph.nodes.get(use.to).label)}</h4>${qualificationHtml(use, graph)}${readingSection({role:'logic',title:'How this input contributes',attrs:{'data-reader-search-key':`use:${use.id}:logic`},bodyHtml:`<div class="proof-idea">${formulaHtml(use.reason_html || esc(use.reason))}</div>`})}${issueHtml(use)}${reviewLineHtml(use)}${sourceDisclosure({attrs:{'data-reader-search-key':`use:${use.id}:sources`},bodyHtml:`${comparisonNoteHtml(use, true)}${sourceHtml(use)}${passagesHtml(use)}`})}`;
}

function fullIndexHtml(data, graph, open = false) {
  const detailCount = (data.details || []).length;
  const detailSummary = detailCount ? `, ${detailCount} intermediate steps and ${data.detail_uses.length} detail uses under their owners` : '';
  return `<details class="proof-index" id="proof-full-index"${open ? ' open' : ''}><summary>Selected statements and connections (${data.items.length} statements, ${data.uses.length} connections${detailSummary})</summary>${data.items.map((node) => `<article id="proof-index-item-${esc(node.id)}" data-proof-index-item="${esc(node.id)}" tabindex="-1"><h3>${esc(node.label)}${node.caption ? `: ${esc(node.caption)}` : ''}</h3>${fullItemHtml(node, graph)}</article>`).join('')}<h3>Connections</h3>${data.uses.map((use) => `<article id="proof-index-use-${esc(use.id)}" data-proof-index-use="${esc(use.id)}" tabindex="-1" data-proof-from="${esc(use.from)}" data-proof-to="${esc(use.to)}">${fullUseHtml(use, graph)}</article>`).join('')}</details>`;
}

function recordsHtml(data, graphMode) {
  const records = { schema_version: data.schema_version, graph_mode: graphMode, ...(data.graph_cycles !== undefined ? { graph_cycles: data.graph_cycles } : {}), items: data.items, uses: data.uses, details: data.details, detail_uses: data.detail_uses, build_context: data.build_context || { mathematical_assessment: 'not_performed' } };
  return `<script id="proof-overview-records" type="application/json">${jsonForScript(records)}</script>`;
}

function buildContextHtml(data) {
  const context = data.build_context;
  if (!context) return '';
  const sourceStatus = {
    historical_changed: 'The manuscript files have changed. This overview explains an earlier captured version.',
    historical_unavailable: 'Some original manuscript files are unavailable. This overview uses the captured source.',
    unregistered: 'No manuscript source is captured. The statements and source locations still need source comparison.',
  }[context.source_status] || '';
  const state = context.source_comparison;
  const comparisonStatus = typeof state === 'string' ? state : state?.status;
  const limits = [];
  if (state?.unreviewed) limits.push('Some selected statements or connections have not yet been compared with the source.');
  if (state?.stale) limits.push('Some source comparisons need updating after changes to the source or argument context.');
  if (state?.needs_attention) limits.push('Some source questions remain unresolved; affected statements or connections are marked.');
  const comparison = limits.join(' ') || {
    complete: 'The selected statements and connections have been compared with the source.',
    incomplete: 'Source comparison remains incomplete; read the affected statements and connections for its limits.',
  }[comparisonStatus] || '';
  const rows = [...(data.items || []), ...(data.details || []), ...(data.uses || []), ...(data.detail_uses || [])];
  const issueNote = rows.some((row) => typeof row.issue === 'string' && row.issue.trim()) ? 'Open questions are shown beside the affected statements or connections.' : '';
  return [sourceStatus, comparison, issueNote].some(Boolean)
    ? `<p class="proof-hint">${[sourceStatus, comparison, issueNote].filter(Boolean).map(esc).join(' ')}</p>` : '';
}

function readerWarnings(data) {
  const replacements = data.reader_warning_overrides || {};
  return (data.warnings || []).map((warning) => Object.hasOwn(replacements, warning) ? replacements[warning] : warning).filter(Boolean);
}

function scopeHtml(scope, prepared) {
  if (prepared) {
    const lead = prepared.lead_html ? `<p class="proof-scope-lead">${formulaHtml(prepared.lead_html)}</p>` : '';
    const details = prepared.details_html ? `<details class="proof-scope"><summary>Scope details and reading limits</summary><p>${formulaHtml(prepared.details_html)}</p></details>` : '';
    return lead + details;
  }
  // Bound presentation of older, unbroken scope essays without rewriting the
  // stored scope. The complete original remains available in one disclosure.
  const original = String(scope || '').trim();
  const [lead, ...rest] = original.split(/\n\s*\n/);
  const words = [...lead.matchAll(/\S+/gu)];
  const abbreviated = words.length > 100;
  const preview = abbreviated ? `${lead.slice(0, words[100].index).trimEnd()}…` : lead.trim();
  const remainder = abbreviated ? original : rest.join('\n\n').trim();
  const leadHtml = preview ? `<p class="proof-scope-lead">${esc(preview)}</p>` : '';
  const restHtml = remainder ? `<details class="proof-scope"><summary>Scope details and reading limits</summary><p>${esc(remainder)}</p></details>` : '';
  return leadHtml + restHtml;
}

function mathDiagnosticsHtml(data) {
  const entries = Array.isArray(data.math_diagnostics) ? data.math_diagnostics : [];
  if (!entries.length) return '';
  const groups = new Map();
  for (const entry of entries) {
    if (!groups.has(entry.reason)) groups.set(entry.reason, []);
    groups.get(entry.reason).push(entry);
  }
  const itemNames = new Map([...(data.items || []), ...(data.details || [])].map((item) => [item.id, item.label]));
  const useNames = new Map();
  for (const use of [...(data.uses || []), ...(data.detail_uses || [])]) {
    useNames.set(use.id, `${itemNames.get(use.from) || use.from} → ${itemNames.get(use.to) || use.to}`);
  }
  const fieldNames = { statement: 'statement', proof_idea: 'proof idea', reason: 'contribution explanation', regime: 'applicability condition', issue: 'open question', comparison_note: 'source comparison note', scope: 'scope' };
  const rows = [...groups].slice(0,5).map(([reason, occurrences]) => `<li>${sourceDisclosure({title:`${reason} (${occurrences.length})`,bodyHtml:`<ul>${occurrences.slice(0,5).map((entry) => `<li>${esc(entry.collection === 'metadata' ? 'Overview' : (entry.collection === 'uses' ? useNames : itemNames).get(entry.id) || 'Selected source text')} (${esc(fieldNames[entry.field] || 'source text')}):<br><code>${esc(entry.excerpt)}</code></li>`).join('')}</ul>`})}</li>`).join('');
  return mathDisplayNotes({messages:[...groups].slice(0,5).map(([reason,occurrences])=>`${reason} (${occurrences.length})`),groups_truncated:groups.size>5 || [...groups.values()].some(occurrences=>occurrences.length>5)},`<ul>${rows}</ul>`);
}

function cycleContextHtml(graph) {
  if (!graph.cycles.length) return '';
  const uses = new Map([...graph.outgoing.values()].flat().map((use) => [use.id, use]));
  return `<details class="proof-render-warnings proof-cycles"><summary>Recorded cycles (${graph.cycles.length}): all connections remain visible</summary><p>Return arrows preserve the recorded direction. A cycle can reflect argument reuse, alternative regimes, or an unresolved dependency; it does not establish a circular proof. Read the connections and their source passages before interpreting it.</p><ul>${graph.cycles.map((group) => `<li>${group.item_ids.map((id) => `<button type="button" data-proof-focus="${esc(id)}">${esc(graph.nodes.get(id).label)}</button>`).join(', ')}<ul>${group.use_ids.map((id) => {
    const use = uses.get(id);
    return `<li><button type="button" data-proof-use="${esc(id)}">${esc(graph.nodes.get(use.from).label)} → ${esc(graph.nodes.get(use.to).label)} (${esc(useTypes[use.type])})</button>${use.regime ? `; ${esc(use.regime)}` : ''}</li>`;
  }).join('')}</ul></li>`).join('')}</ul></details>`;
}

function emptyConnectionsHtml(data) {
  return data.uses.length ? '' : '<p class="proof-empty-connections" role="note">No connections are recorded in this overview. This does not establish that the results are independent.</p>';
}

function renderIndex(data) {
  const graph = indexGraph(data);
  const warnings = readerWarnings(data).map((warning) => `<li>${esc(warning)}</li>`).join('');
  const mainItems = data.main_items || data.items.map(node => node.id);
  const beforeGraph = `<div class="proof-reader"><p class="proof-kicker">Source overview</p><p class="proof-caption">${data.items.length} selected statements · ${data.uses.length} connections</p><p><strong>Index view.</strong> All selected statements and connections are displayed below. This overview explains the written argument; it does not verify the proofs. Cyclic mappings alone do not establish a circular proof.</p>${emptyConnectionsHtml(data)}${scopeHtml(data.scope, data.scope_display)}${buildContextHtml(data)}${warnings ? `<div class="proof-render-warnings"><ul>${warnings}</ul></div>` : ''}${mathDiagnosticsHtml(data)}</div>`;
  const html = archifyPage({templatePath:path.join(root,'scripts/paper_core/renderer/assets/archify/template.html'),title:data.title,index:true,svg:'<svg class="proof-index-placeholder" viewBox="0 0 100 100" aria-hidden="true" xmlns="http://www.w3.org/2000/svg"></svg>',beforeGraph,afterGraph:`<div class="proof-reader">${scientificSearchPanel()}${fullIndexHtml(data,graph,true)}</div>`,css:graphCss(data),data:recordsHtml(data,'index')+overviewData(data,graph,mainItems)+readerSearchData(searchEntries(data,graph)),runtime:readerRuntime({targets:readerTargets(data,true),graphAvailable:false})});
  const graph_preservation = representationReceipt(data, html, 'index');
  if (graph_preservation.status !== 'pass') throw new Error('Rendered index does not preserve the supplied item and use identities.');
  return { html, items: data.items.length, uses: data.uses.length, viewBox: null, graph_mode: 'index', graph_preservation, geometry: { status: 'not_applicable', checks: [], diagnostics: [], reason: 'The complete records are shown as an index; no dependency geometry is drawn.' } };
}

function graphCss(data) {
  return Object.keys(kinds).map(kind => `.c-${kind}{--proof-tone:var(--kind-${kind});stroke:var(--proof-tone);fill:color-mix(in srgb,var(--proof-tone) 13%,transparent)}[data-kind="${kind}"]{--proof-kind:var(--kind-${kind})}.overview-map-node[data-kind="${kind}"]{fill:var(--proof-kind);stroke:var(--proof-kind)}.semantic-lens-kind[data-kind="${kind}"]{--lens-color:var(--proof-kind)}.proof-legend [data-kind="${kind}"]::before{background:var(--proof-kind)}`).join('\n') + data.uses.filter(use => use.type !== 'dependency' || use.regime || use.group).map(use => `svg[data-focus-active]:not([data-reach-active]):has([data-edge-id="${use.id}"][data-focus-match]) [data-proof-use="${use.id}"],svg[data-reach-active]:has([data-edge-id="${use.id}"][data-reach-match]) [data-proof-use="${use.id}"]{opacity:1}`).join('');
}
function readerTargets(data, index = false) {
  return [...data.items.map(node => ({key:'item:'+node.id,articleId:(index?'proof-index-item-':'proof-detail-')+node.id,nodeId:node.id})),...data.uses.map(use => ({key:'use:'+use.id,articleId:(index?'proof-index-use-':'proof-use-')+use.id,edgeId:use.id}))];
}
const SEARCH_BLOCKS = new Set('address article aside blockquote div dl dt dd fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table tbody td tfoot th thead tr ul details summary br'.split(' '));
const SEARCH_IGNORED = new Set(['annotation', 'annotation-xml', 'script', 'style']);
const SEARCH_LABELS = new Set(['proof-use-type', 'proof-regime', 'proof-group']);

function searchText(scan) {
  const chunks = [], ranges = new Map();
  let length = 0;
  const emit = text => { chunks.push(text); length += text.length; };
  // Decode only selected text, never reparsing literal markup from source excerpts.
  const gap = text => emit(decodeEntities(text.replace(/<!--[\s\S]*?-->/g, '')));
  function content(node, presentation) {
    let cursor = node.openEnd;
    for (const child of node.children) {
      gap(scan.html.slice(cursor, child.start));
      walk(child, presentation);
      cursor = child.closeEnd;
    }
    gap(scan.html.slice(cursor, node.closeStart));
  }
  function mathSource(math) {
    const pending = [...math.children].reverse();
    while (pending.length) {
      const node = pending.pop();
      if (node.tag === 'annotation' && node.attrs.encoding?.trim().toLowerCase() === 'application/x-tex') {
        const tex = textOf(scan, node);
        if (tex.trim()) return tex;
      }
      if (!SEARCH_IGNORED.has(node.tag)) pending.push(...[...node.children].reverse());
    }
    // scanHtml already decodes attribute values once.
    const label = (math.attrs['aria-label'] || '').replace(/^LaTeX: /, '');
    return label.trim() ? label : null;
  }
  function walk(node, presentation = false) {
    if (SEARCH_IGNORED.has(node.tag)) return;
    const block = SEARCH_BLOCKS.has(node.tag) || node.tag === 'math' && node.attrs.display === 'block'
      || node.tag === 'span' && (node.attrs.class || '').split(/\s+/).some(name => SEARCH_LABELS.has(name));
    if (block) emit(' ');
    const start = length;
    if (node.tag === 'math') {
      const source = mathSource(node);
      if (source !== null) emit(source);
      else content(node, true);
    } else if (presentation && node.tag === 'semantics') {
      const primary = node.children.find(child => !SEARCH_IGNORED.has(child.tag));
      if (primary) walk(primary, true);
    } else {
      content(node, presentation);
    }
    ranges.set(node, [start, length]);
    if (block) emit(' ');
  }
  // Shared sections and the whole card reuse one buffer instead of rewalking HTML.
  walk(scan.root);
  const text = chunks.join('');
  return element => {
    const [start, end] = ranges.get(element);
    return text.slice(start, end).replace(/\s+/gu, ' ').trim();
  };
}

function searchEntries(data, graph) {
  const entries = [];
  const index = (row, detail, owner, html) => {
    const scan = scanHtml(`<div>${html}</div>`), plainText = searchText(scan);
    const destinations = scan.elements.filter(element => Object.hasOwn(element.attrs,'data-reader-search-key'));
    destinations.sort((a,b)=>Number(!a.attrs['data-reader-search-key'].includes(':source:'))-Number(!b.attrs['data-reader-search-key'].includes(':source:')));
    for (const element of destinations) {
      const key = element.attrs['data-reader-search-key'];
      const label = key.endsWith(':sources') || key.includes(':source:') ? 'Source passages and locators' : key.endsWith(':outgoing') ? 'Used by' : key.endsWith(':logic') ? 'Proof idea and contributions' : key.startsWith('detail:') ? graph.details.get(key.slice(7))?.label || 'Intermediate argument' : row.label || owner;
      entries.push({key,aliases:[row.id,key,...(row.aliases||[])],label,detail,section:null,owner,text:`${label} ${owner} ${plainText(element)}`});
    }
    // Remaining saved context, including issues and source comparisons, stays searchable.
    entries.push({key:detail,aliases:[row.id,...(row.aliases||[])],label:row.label || owner,detail,section:null,owner,text:plainText(scan.root)});
  };
  for (const node of data.items) index(node,'item:'+node.id,node.label,fullItemHtml(node,graph));
  for (const use of data.uses) index(use,'use:'+use.id,graph.nodes.get(use.from).label+' applied to '+graph.nodes.get(use.to).label,fullUseHtml(use,graph));
  return entries;
}
function overviewData(data, graph, mainItems) {
  const payload = {items:[...graph.nodes.values()].map(({id,x,y})=>({id,x:x+box.w/2,y:y+box.h/2})),uses:data.uses.map(({id})=>({id})),main_items:mainItems};
  return `<div id="proof-tooltip" role="tooltip" hidden></div><script id="proof-overview-data" type="application/json">${jsonForScript(payload)}</script>`;
}

function render(input) {
  const data = preparedDataset(input);
  if (data.graph_mode === 'index') return renderIndex(data);
  const graph = layoutGraph(data);
  const graphMode = graph.cycles.length ? 'cyclic' : 'dag';
  if (data.graph_mode !== undefined && data.graph_mode !== graphMode) throw new Error('Prepared graph_mode does not match the recorded connections. Prepare the records again.');
  if (data.graph_cycles !== undefined && JSON.stringify(data.graph_cycles) !== JSON.stringify(graph.cycles)) throw new Error('Prepared cycle diagnostics do not match the recorded connections. Prepare the records again.');
  // A terminal cyclic group has no individual sink. Keep its members available
  // as reading entry points without presenting their internal order as a proof.
  const terminalCycles = graph.cycles.filter((group) => {
    const members = new Set(group.item_ids);
    return group.item_ids.every((id) => graph.outgoing.get(id).every((use) => members.has(use.to)));
  });
  const terminalIds = new Set([...data.items.filter((item) => !graph.outgoing.get(item.id).length).map((item) => item.id), ...terminalCycles.flatMap((group) => group.item_ids)]);
  const mainItems = data.main_items || data.items.filter((item) => terminalIds.has(item.id)).map((item) => item.id);
  const hasRegimes = data.uses.some((use) => use.regime);
  const presentKinds = new Set(data.items.map((item) => item.kind));
  const legend = `<ul class="proof-legend" aria-label="Mathematical item types">${Object.entries(kinds).filter(([kind]) => presentKinds.has(kind)).map(([kind, [label]]) => `<li data-kind="${kind}">${label}</li>`).join('')}</ul>`;
  const cards = `<div class="proof-caption"><p>Arrows point from prerequisites to the results that use them. Badges distinguish definition uses, proof arguments, and regime-specific uses. Dashed arrows mark connections with an open issue.</p></div>${legend}`;
  const templatePath = path.join(root, 'scripts/paper_core/renderer/assets/archify/template.html');
  const svg = renderSvg(data, graph), geometry = geometryReceipt(data, graph);
  if (geometry.status !== 'pass') {
    const error = new Error('Proof diagram geometry checks failed. The previous artifact was preserved.');
    error.diagnostics = geometry.diagnostics; error.stage = 'geometry';
    throw error;
  }
  const warningNotes = readerWarnings(data);
  const warnings = warningNotes.length ? `<div class="proof-render-warnings" role="note"><strong>Source and rendering notes</strong><ul>${warningNotes.map((warning) => `<li>${esc(warning)}</li>`).join('')}</ul></div>` : '';
  const resultsHtml = resultsNavigation({entries:data.items.map(node=>({key:'item:'+node.id,nodeId:node.id,articleId:'proof-index-item-'+node.id,label:node.label,caption:node.caption,kind:node.kind})),mainIds:mainItems,heading:data.main_items?'Main results':terminalCycles.length?'Results and terminal cycle groups':'Terminal results in the recorded graph'});
  const beforeGraph = `<div class="proof-reader"><div class="proof-caption"><p class="proof-kicker">Source overview</p><p>${esc(data.source?.title || data.title)} · ${data.items.length} selected statements · ${data.uses.length} connections</p><p><strong>Selected main results and important prerequisites.</strong> Select a result for its statement, source, and connections. This map explains the written argument; it does not verify the proofs.</p>${buildContextHtml(data)}</div>${emptyConnectionsHtml(data)}${scopeHtml(data.scope, data.scope_display)}${warnings}${mathDiagnosticsHtml(data)}${cycleContextHtml(graph)}</div>${viewControls({traceHtml:hasRegimes?'<p class="proof-trace-note" role="note">Some connections apply only in a named regime. Dependency tracing follows all recorded arrows, including alternative routes. Regime labels still apply; a trace is not one required or verified proof route.</p>':''})}`;
  const fragments = data.items.map((node) => `<template id="proof-detail-${esc(node.id)}">${fullItemHtml(node, graph)}</template><template id="proof-hover-${esc(node.id)}">${fullItemHtml(node, graph, { hover: true })}</template>`).join('');
  const useFragments = data.uses.map((use) => `<template id="proof-use-${esc(use.id)}">${fullUseHtml(use, graph)}</template>`).join('');
  const index = `<div class="proof-reader">${scientificSearchPanel()}${fullIndexHtml(data, graph, true)}</div><p class="proof-attribution">Viewer adapted from Archify 3.0.1 by tt-a1i and Cocoon AI, MIT licensed. Proof-specific dataset and rendering by proof-graphify.</p>`;
  const html = archifyPage({templatePath,title:data.title,svg,beforeGraph,resultsHtml,afterGraph:cards+index,css:graphCss(data),data:fragments+useFragments+recordsHtml(data,graphMode)+overviewData(data,graph,mainItems)+readerSearchData(searchEntries(data,graph)),runtime:readerRuntime({targets:readerTargets(data),graphAvailable:true})});
  const graph_preservation = representationReceipt(data, html, graphMode);
  if (graph_preservation.status !== 'pass') throw new Error('Rendered SVG does not preserve the supplied item and use identities.');
  return { html, items: data.items.length, uses: data.uses.length, viewBox: [graph.width, graph.height], graph_mode: graphMode, graph_preservation, geometry };
}

try {
  if (process.argv.length !== 4) throw new Error('Usage: node scripts/render.mjs prepared.json output.html');
  const inputPath = path.resolve(process.argv[2]), outputPath = path.resolve(process.argv[3]);
  if (inputPath === outputPath) throw new Error('Output must differ from the prepared dataset.');
  const inputBytes = fs.readFileSync(inputPath);
  const result = render(JSON.parse(inputBytes.toString('utf8').replace(/^\uFEFF/u, '')));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const candidate = `${outputPath}.${process.pid}.tmp`;
  try { fs.writeFileSync(candidate, result.html, { encoding: 'utf8', flag: 'wx' }); fs.renameSync(candidate, outputPath); }
  finally { if (fs.existsSync(candidate)) fs.unlinkSync(candidate); }
  console.log(JSON.stringify({ ok: true, output: outputPath, items: result.items, uses: result.uses, viewBox: result.viewBox, graph_mode: result.graph_mode, graph_preservation: result.graph_preservation, geometry: result.geometry, bytes: Buffer.byteLength(result.html), input_sha256: crypto.createHash('sha256').update(inputBytes).digest('hex'), artifact_sha256: crypto.createHash('sha256').update(result.html).digest('hex'), browser_review: 'not_performed', visual_review: 'not_performed', mathematical_assessment: 'not_performed' }));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error.message, ...(error.stage ? { stage: error.stage } : {}), ...(error.diagnostics ? { diagnostics: error.diagnostics } : {}) }));
  process.exitCode = 1;
}
