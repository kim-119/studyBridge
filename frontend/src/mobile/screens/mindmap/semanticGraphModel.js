import { attachSemanticGraph } from '../../../utils/graph/semanticGraphMerge.js';

export function withSemanticConcepts(baseGraph, semanticState, semantic) {
  if (!baseGraph) return null;
  if (semanticState === 'ok' || semanticState === 'degraded') return attachSemanticGraph(baseGraph, semantic);
  return { ...baseGraph, semanticStatus: semanticState === 'loading' ? 'LOADING' : 'FAILED' };
}
