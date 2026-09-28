function toServerId(value) {
  if (value === null || value === undefined || value === '') return null;
  return String(value);
}

function matchKey(message) {
  return `${message.senderId ?? ''}\u0000${message.content ?? ''}`;
}

export function toLiveChatMessage(payload, sequence) {
  const serverId = toServerId(payload?.id);
  return {
    id: serverId ? `server-${serverId}` : `live-${sequence}`,
    serverId,
    senderId: payload?.senderId ?? null,
    senderName: payload?.senderName || '참여자',
    content: payload?.content ?? '',
  };
}

export function appendLiveChatMessage(messages, message) {
  if (message.serverId && messages.some((existing) => existing.serverId === message.serverId)) {
    return messages;
  }
  return [...messages, message];
}

function compareServerIds(first, second) {
  const firstNumber = Number(first.serverId);
  const secondNumber = Number(second.serverId);
  if (Number.isFinite(firstNumber) && Number.isFinite(secondNumber)) return firstNumber - secondNumber;
  return String(first.serverId).localeCompare(String(second.serverId));
}

export function mergeChatHistories(...histories) {
  const byServerId = new Map();

  histories.flat().forEach((message) => {
    if (message?.serverId && !byServerId.has(message.serverId)) byServerId.set(message.serverId, message);
  });

  return [...byServerId.values()].sort(compareServerIds);
}

function countUnclaimedByKey(history) {
  const counts = new Map();
  history.forEach((message) => {
    const key = matchKey(message);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
}

function isNewerThan(message, baselineServerId) {
  if (baselineServerId === null || baselineServerId === undefined) return true;
  return Number(message.serverId) > Number(baselineServerId);
}

export function latestServerId(history) {
  const ids = history.map((message) => Number(message.serverId)).filter(Number.isFinite);
  return ids.length > 0 ? Math.max(...ids) : null;
}

export function reconcileChatWithHistory(history, liveMessages, { baselineServerId = null } = {}) {
  const historyServerIds = new Set(history.map((message) => message.serverId).filter(Boolean));
  const unclaimed = countUnclaimedByKey(history.filter((message) => isNewerThan(message, baselineServerId)));
  const survivors = [];

  [...liveMessages].reverse().forEach((message) => {
    if (message.serverId) {
      if (!historyServerIds.has(message.serverId)) survivors.push(message);
      return;
    }

    const key = matchKey(message);
    const remaining = unclaimed.get(key) || 0;
    if (remaining > 0) {
      unclaimed.set(key, remaining - 1);
      return;
    }
    survivors.push(message);
  });

  return [...history, ...survivors.reverse()];
}
