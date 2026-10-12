package com.studybridge.api.service.recommendation;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.Set;

/**
 * 학습 단계 선수관계 그래프 G = (V, E). (u, v) ∈ E 는 "u 를 먼저 학습해야 v 에 진입" 을 뜻한다.
 *
 * <ul>
 *   <li>V 는 한 사용자·한 로드맵의 노드만 담는다(생성 시 호출자가 userId 로 필터한 데이터만 넣는다).</li>
 *   <li>{@link #validate()} 는 존재하지 않는 노드를 가리키는 간선·자기 루프·순환을 검출한다(Kahn 위상 정렬).</li>
 *   <li>기존 순차형 로드맵은 {@link #sequential} 로 order 순 인접 간선을 만든다 — 저장 데이터는 바꾸지 않는다.</li>
 * </ul>
 * 상태가 없는 값 객체 — 스레드 안전.
 */
public final class LearningGraph {

    /** order 는 위상 정렬 동률 시 안정적 순서(기존 week/day 순서) 를 위한 키. */
    public record Node(String key, String title, long order) {}

    public record Edge(String from, String to) {}

    public record Validation(boolean valid, List<String> unknownNodeEdges, List<String> selfLoops, List<String> cycleNodes) {
        public static Validation ok() {
            return new Validation(true, List.of(), List.of(), List.of());
        }
    }

    private final Map<String, Node> nodes;
    private final List<Edge> edges;
    private final Map<String, Set<String>> prereqs = new HashMap<>();
    private final Map<String, Set<String>> successors = new HashMap<>();

    public LearningGraph(List<Node> nodeList, List<Edge> edgeList) {
        Map<String, Node> m = new LinkedHashMap<>();
        for (Node n : nodeList) m.putIfAbsent(n.key(), n);
        this.nodes = Collections.unmodifiableMap(m);
        this.edges = List.copyOf(new LinkedHashSet<>(edgeList));
        for (Edge e : this.edges) {
            prereqs.computeIfAbsent(e.to(), k -> new LinkedHashSet<>()).add(e.from());
            successors.computeIfAbsent(e.from(), k -> new LinkedHashSet<>()).add(e.to());
        }
    }

    /** 순차형(레거시) 로드맵 호환: order 오름차순으로 인접한 노드끼리 간선. */
    public static LearningGraph sequential(List<Node> nodeList) {
        List<Node> sorted = new ArrayList<>(nodeList);
        sorted.sort(Comparator.comparingLong(Node::order).thenComparing(Node::key));
        List<Edge> es = new ArrayList<>();
        for (int i = 1; i < sorted.size(); i++) {
            es.add(new Edge(sorted.get(i - 1).key(), sorted.get(i).key()));
        }
        return new LearningGraph(sorted, es);
    }

    public Map<String, Node> nodes() { return nodes; }

    public List<Edge> edges() { return edges; }

    public boolean contains(String key) { return nodes.containsKey(key); }

    /** Prereq(v) = { u | (u, v) ∈ E } */
    public Set<String> prereqs(String key) {
        return prereqs.getOrDefault(key, Set.of());
    }

    public Set<String> successors(String key) {
        return successors.getOrDefault(key, Set.of());
    }

    /** 새 간선을 더한 그래프(원본 불변). 후보 간선 검증용. */
    public LearningGraph withEdges(List<Edge> extra) {
        List<Edge> all = new ArrayList<>(edges);
        all.addAll(extra);
        return new LearningGraph(new ArrayList<>(nodes.values()), all);
    }

    public Validation validate() {
        List<String> unknown = new ArrayList<>();
        List<String> self = new ArrayList<>();
        for (Edge e : edges) {
            if (!nodes.containsKey(e.from()) || !nodes.containsKey(e.to())) unknown.add(e.from() + "->" + e.to());
            else if (e.from().equals(e.to())) self.add(e.from());
        }
        List<String> cycle = unknown.isEmpty() && self.isEmpty() ? cycleNodes() : List.of();
        boolean valid = unknown.isEmpty() && self.isEmpty() && cycle.isEmpty();
        return valid ? Validation.ok() : new Validation(false, unknown, self, cycle);
    }

    /**
     * 위상 정렬(Kahn). 진입 차수 0 인 노드 중 order 가 작은 것을 먼저 꺼내 기존 순서를 최대한 보존한다.
     *
     * @throws IllegalStateException 순환/잘못된 간선이 있으면
     */
    public List<String> topologicalOrder() {
        Validation v = validate();
        if (!v.valid()) throw new IllegalStateException("learning graph is not a DAG: " + v);
        return kahn().order;
    }

    private record KahnResult(List<String> order, Map<String, Integer> remainingIndegree) {}

    private KahnResult kahn() {
        Map<String, Integer> indeg = new HashMap<>();
        for (String k : nodes.keySet()) indeg.put(k, 0);
        for (Edge e : edges) {
            if (nodes.containsKey(e.from()) && nodes.containsKey(e.to())) indeg.merge(e.to(), 1, Integer::sum);
        }
        PriorityQueue<Node> ready = new PriorityQueue<>(Comparator.comparingLong(Node::order).thenComparing(Node::key));
        indeg.forEach((k, d) -> { if (d == 0) ready.add(nodes.get(k)); });
        List<String> order = new ArrayList<>();
        while (!ready.isEmpty()) {
            Node n = ready.poll();
            order.add(n.key());
            for (String s : successors(n.key())) {
                if (!nodes.containsKey(s)) continue;
                int d = indeg.merge(s, -1, Integer::sum);
                if (d == 0) ready.add(nodes.get(s));
            }
        }
        return new KahnResult(order, indeg);
    }

    /** 위상 정렬 후에도 진입 차수가 남은 노드 = 순환에 속하거나 순환 뒤에 있는 노드. */
    private List<String> cycleNodes() {
        KahnResult r = kahn();
        if (r.order.size() == nodes.size()) return List.of();
        Set<String> done = new LinkedHashSet<>(r.order);
        List<String> rest = new ArrayList<>();
        for (String k : nodes.keySet()) if (!done.contains(k)) rest.add(k);
        return rest;
    }

    /** 모든 선행 노드(전이적). */
    public Set<String> ancestors(String key) {
        Set<String> seen = new LinkedHashSet<>();
        Deque<String> stack = new ArrayDeque<>(prereqs(key));
        while (!stack.isEmpty()) {
            String u = stack.pop();
            if (seen.add(u)) stack.addAll(prereqs(u));
        }
        return seen;
    }
}
