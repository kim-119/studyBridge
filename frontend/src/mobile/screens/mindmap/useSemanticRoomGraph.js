import { useMemo } from 'react';
import { useSemanticMindmap } from '../../../hooks/useSemanticMindmap';
import { buildSemanticAnswers } from '../../../utils/graph/semanticGraphMerge';
import { withSemanticConcepts } from './semanticGraphModel';

export function useSemanticRoomGraph({ roomId, question, messages, agents, baseGraph }) {
  const answers = useMemo(() => buildSemanticAnswers(messages, agents), [messages, agents]);
  const { state, semantic, reason, retry } = useSemanticMindmap({
    roomId,
    question,
    answers,
    enabled: roomId != null && Boolean(baseGraph),
  });

  const graph = useMemo(() => withSemanticConcepts(baseGraph, state, semantic), [baseGraph, state, semantic]);

  return { graph, semanticState: state, semanticReason: reason, retrySemantic: retry };
}
