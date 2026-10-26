import React from 'react';

export default function AgentIdentityLabel({ agent, fallbackName = 'AI', children = null }) {
  return (
    <span className="mobile-agent-label">
      <span className="mobile-agent-label__dot" aria-hidden="true" />
      <strong className="mobile-agent-label__name">{agent?.name || fallbackName}</strong>
      {agent?.roleText && <span className="mobile-agent-label__role">{agent.roleText}</span>}
      {children}
    </span>
  );
}
