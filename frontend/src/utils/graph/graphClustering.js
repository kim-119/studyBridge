// ─────────────────────────────────────────────────────────────────────────────
// 클러스터링: 대량 그래프에서 노드를 묶고 클러스터 라벨/경계를 만든다.
//  · 우선순위: sourceId → questionId → tag → type.
// ─────────────────────────────────────────────────────────────────────────────
import { NODE_TYPES } from './graphTypes';

const clusterKeyFor = (node) => {
  if (node.sourceId && node.sourceType && node.sourceType !== 'multi_agent_chat') {
    return `src:${node.sourceType}:${node.sourceId}`;
  }
  if (Array.isArray(node.tags) && node.tags.length) {
    const meaningful = node.tags.find((t) => !['StudyBridge', 'mindmap'].includes(t));
    if (meaningful) return `tag:${meaningful}`;
  }
  return `type:${node.type}`;
};

const clusterLabelFor = (key) => {
  const [, , id] = key.split(':');
  if (key.startsWith('tag:')) return key.slice(4);
  if (key.startsWith('type:')) return key.slice(5);
  return id || key;
};

/**
 * @param {{nodes:any[]}} graph
 * @returns {{clusters:Array<{id:string,label:string,nodeIds:string[]}>, nodeToCluster:Map<string,string>}}
 */
export function computeClusters(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const map = new Map();
  const nodeToCluster = new Map();
  nodes.forEach((n) => {
    if (n.type === NODE_TYPES.CLUSTER) return;
    const key = clusterKeyFor(n);
    if (!map.has(key)) map.set(key, { id: key, label: clusterLabelFor(key), nodeIds: [] });
    map.get(key).nodeIds.push(n.id);
    nodeToCluster.set(n.id, key);
  });
  return { clusters: Array.from(map.values()), nodeToCluster };
}
