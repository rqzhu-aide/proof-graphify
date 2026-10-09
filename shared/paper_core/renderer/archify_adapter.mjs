// Prepared audit content adapter for the common scientific reader.
import { archifyPage, mainResultNavigation } from './scientific_reader.mjs';
export { archifyPage };
export function mainNavigation(nodes, connections, requested = [], graphAvailable = true) {
  const ids = new Set(nodes.map(node => node.id));
  const selected = requested.filter(id => ids.has(id));
  const main = selected.length ? selected : nodes.filter(node => !connections.some(edge => edge.from === node.id)).map(node => node.id);
  const chosen = main.length ? main : nodes.map(node => node.id);
  return mainResultNavigation({entries:chosen.map(id => {
    const node = nodes.find(candidate => candidate.id === id);
    return {key:node.detail_key,nodeId:id,label:node.label,caption:node.caption,kind:node.kind};
  }),heading:selected.length ? 'Main results' : 'Results to explore',graphAvailable,
  traceHtml:'<p class="proof-trace-note">Tracing follows recorded connections, including alternative routes. It identifies supporting or potentially affected results; it does not establish a complete or verified proof route.</p>'});
}
