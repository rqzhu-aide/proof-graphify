// Prepared audit content adapter for the common scientific reader.
import { archifyPage, resultsNavigation } from './scientific_reader.mjs';
export { archifyPage };
export function auditResults(nodes, connections, requested, graphAvailable, detailId) {
  const ids = new Set(nodes.map(node => node.id));
  const selected = requested.filter(id => ids.has(id));
  const outgoing = new Set(connections.map(edge => edge.from));
  const mainIds = selected.length ? selected : nodes.filter(node => !outgoing.has(node.id)).map(node => node.id);
  return resultsNavigation({
    entries:nodes.map(node => ({key:node.detail_key,nodeId:node.id,articleId:detailId(node.detail_key),label:node.label,caption:node.caption,kind:node.kind})),
    mainIds:mainIds.length ? mainIds : nodes.map(node => node.id),
    heading:selected.length ? 'Main results' : 'Results to explore',graphAvailable,
  });
}
