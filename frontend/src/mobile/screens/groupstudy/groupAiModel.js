export const GROUP_AI_LEARNING_MODE = 'basic';

export function buildGroupAiRequestBody(message, conversationState) {
  return {
    message,
    source: 'group_study',
    mode: 'multi_agent_discussion',
    learningMode: GROUP_AI_LEARNING_MODE,
    rounds: 3,
    showFinalSynthesis: true,
    agents: [],
    ...conversationState,
  };
}

function firstPresent(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== '');
}

export function captureConversationState(current, parsed) {
  const next = { ...current };
  const candidates = {
    debateState: firstPresent(parsed.debateState, parsed.debate_state),
    selectedTopic: firstPresent(parsed.selectedTopic, parsed.selected_topic),
    debateSessionId: firstPresent(parsed.debateSessionId, parsed.debate_session_id, parsed.sessionId),
    simulationState: firstPresent(parsed.simulationState, parsed.simulation_state),
    scenarioId: firstPresent(parsed.scenarioId, parsed.scenario_id),
  };

  Object.entries(candidates).forEach(([key, value]) => {
    if (value !== undefined) next[key] = value;
  });

  const turnIndex = parsed.turnIndex ?? parsed.turn_index;
  if (typeof turnIndex === 'number') next.turnIndex = turnIndex;

  return next;
}

function sectionItemText(item) {
  if (typeof item === 'string') return item;
  return item?.content || item?.text || item?.summary || item?.claim || '';
}

function upsertDebateSection(messages, parsed, requestId) {
  const debateId = `debate-${requestId}`;
  const index = messages.findIndex((message) => message.id === debateId);
  const base =
    index === -1
      ? { id: debateId, requestId, kind: 'agent', isUser: false, senderName: 'AI 토론', sections: {} }
      : { ...messages[index], sections: { ...messages[index].sections } };

  if (parsed.section === 'debateSummary') {
    base.sections.debateSummary = [parsed.content || ''];
  } else if (parsed.section) {
    base.sections[parsed.section] = (parsed.items || []).map(sectionItemText).filter(Boolean);
  }

  base.content = Object.values(base.sections).flat().join('\n\n');

  if (index === -1) return [...messages, base];
  const next = [...messages];
  next[index] = base;
  return next;
}

function appendAgentContent(messages, agentName, content, requestId) {
  const index = messages.findIndex(
    (message) =>
      message.kind === 'agent' && message.requestId === requestId && message.senderName === agentName
  );

  if (index !== -1) {
    const next = [...messages];
    next[index] = { ...next[index], content: next[index].content + content };
    return next;
  }

  return [
    ...messages,
    {
      id: `agent-${requestId}-${messages.length}`,
      requestId,
      kind: 'agent',
      senderName: agentName,
      content,
      isUser: false,
    },
  ];
}

function hasAgentReply(messages, requestId) {
  return messages.some((message) => message.kind === 'agent' && message.requestId === requestId);
}

function appendCompletedReplies(messages, parsed, requestId) {
  if (hasAgentReply(messages, requestId)) return messages;

  return parsed.replies.reduce((current, reply) => {
    const content = reply?.answer || '';
    if (!content) return current;
    return appendAgentContent(current, reply.agentName || 'AI', content, requestId);
  }, messages);
}

export function describeStreamErrorFrame(parsed) {
  return parsed?.errorMessage || parsed?.message || 'AI 응답 중 오류가 발생했습니다.';
}

export function applyGroupAiFrame(messages, frame, requestId) {
  const parsed = frame.parsed;

  if (frame.event === 'error') {
    return [
      ...messages,
      {
        id: `error-${requestId}-${messages.length}`,
        requestId,
        senderName: 'System',
        content: describeStreamErrorFrame(parsed),
        isUser: false,
        isError: true,
      },
    ];
  }

  if (parsed.type === 'route_message' || parsed.type === 'route_notice') {
    if (!parsed.message) return messages;
    return [
      ...messages,
      {
        id: `route-${requestId}-${messages.length}`,
        requestId,
        senderName: 'AI',
        content: parsed.message,
        isUser: false,
        isNotice: parsed.type === 'route_notice',
      },
    ];
  }

  if (parsed.section || parsed.type === 'debate_section') {
    return upsertDebateSection(messages, parsed, requestId);
  }

  if (parsed.done) return messages;

  if (frame.event === 'all_complete' && Array.isArray(parsed.replies)) {
    return appendCompletedReplies(messages, parsed, requestId);
  }

  if (parsed.agentName && parsed.content) {
    return appendAgentContent(messages, parsed.agentName, parsed.content, requestId);
  }

  return messages;
}
