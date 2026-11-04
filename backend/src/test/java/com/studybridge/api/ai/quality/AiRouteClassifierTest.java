package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.springframework.asm.ClassReader;
import org.springframework.asm.ClassVisitor;
import org.springframework.asm.Handle;
import org.springframework.asm.MethodVisitor;
import org.springframework.asm.Opcodes;
import org.springframework.asm.Type;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * Phase D2 — 미등록 AI 경로 자동 탐지(CI 실패). 컴파일된 main 바이트코드로 호출 그래프를 만든다(람다·인터페이스 구현 포함).
 *
 *  · AI 생성 도달(GEN): 컨트롤러 메서드에서 출발해 WebClient/RestTemplate 필드를 읽는 메서드(= ai07 등 외부 HTTP 호출부)에 닿음.
 *    비AI HTTP 클래스(OpenVidu 등)는 {@link AiRouteExposurePolicy#NON_AI_HTTP_CLASSES} 로만 제외.
 *  · AI 저장본 재노출 도달(READ): AI 산출물 저장소({@link AiRouteExposurePolicy#AI_ARTIFACT_STORES})의 조회 메서드에 닿음.
 *  · 규칙: GEN 또는 READ 인 모든 엔드포인트는 AiQualityGateCoverage.ROUTES(GATED/BLOCKED/EXEMPT) 또는
 *    AiRouteExposurePolicy.NOT_USER_EXPOSED(사유 필수) 중 하나에 있어야 한다. 새 AI 엔드포인트를 등록 없이 추가하면 이 테스트가 실패한다.
 *  · 역방향: ROUTES 의 GATED/BLOCKED 항목은 실제로 GEN/READ 에 닿아야 한다(죽은·허위 항목 방지).
 * 일반 비AI API(로그인·타이머·그룹 관리 등)는 GEN/READ 에 닿지 않으므로 차단 대상이 아니다.
 */
class AiRouteClassifierTest {

        record Node(String owner, String name, String desc) {
                String id() {
                        return owner + "." + name + desc;
                }
        }

        static final class Graph {
                final Map<String, Set<String>> edges = new HashMap<>();
                final Set<String> genSinks = new HashSet<>();
                final Set<String> readSinks = new HashSet<>();
                final Map<String, String> superOf = new HashMap<>();
                final Map<String, List<String>> interfacesOf = new HashMap<>();
                final Map<String, Set<String>> methodsOf = new HashMap<>();
                final Set<String> classes = new HashSet<>();
                final Map<String, String> sinkWhy = new HashMap<>();
        }

        static final String PKG = "com/studybridge/api/";
        static final Set<String> HTTP_TYPES = Set.of("Lorg/springframework/web/reactive/function/client/WebClient;",
                        "Lorg/springframework/web/client/RestTemplate;", "Ljava/net/http/HttpClient;");

        static Path mainClassesDir() throws URISyntaxException {
                return Path.of(AiQualityGateCoverage.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        }

        static Graph build() throws Exception {
                Graph g = new Graph();
                Set<String> stores = new HashSet<>();
                AiRouteExposurePolicy.AI_ARTIFACT_STORES.forEach(c -> stores.add(c.replace('.', '/')));
                Set<String> nonAiHttp = new HashSet<>();
                AiRouteExposurePolicy.NON_AI_HTTP_CLASSES.forEach(c -> nonAiHttp.add(c.replace('.', '/')));
                Path root = mainClassesDir();
                try (Stream<Path> files = Files.walk(root.resolve("com/studybridge/api"))) {
                        for (Path p : (Iterable<Path>) files.filter(f -> f.toString().endsWith(".class"))::iterator) {
                                try (InputStream in = Files.newInputStream(p)) {
                                        read(g, new ClassReader(in), stores, nonAiHttp);
                                }
                        }
                }
                return g;
        }

        static boolean isStoreOwner(String owner, Set<String> stores) {
                for (String s : stores) {
                        if (owner.equals(s) || owner.startsWith(s + "$")) {
                                return true;
                        }
                }
                return false;
        }

        static void read(Graph g, ClassReader cr, Set<String> stores, Set<String> nonAiHttp) throws IOException {
                cr.accept(new ClassVisitor(Opcodes.ASM9) {
                        String cls;

                        @Override
                        public void visit(int version, int access, String name, String signature, String superName, String[] interfaces) {
                                cls = name;
                                g.classes.add(name);
                                g.superOf.put(name, superName);
                                g.interfacesOf.put(name, interfaces == null ? List.of() : List.of(interfaces));
                        }

                        @Override
                        public MethodVisitor visitMethod(int access, String name, String desc, String signature, String[] exceptions) {
                                String me = cls + "." + name + desc;
                                g.methodsOf.computeIfAbsent(cls, k -> new HashSet<>()).add(name + desc);
                                Set<String> out = g.edges.computeIfAbsent(me, k -> new HashSet<>());
                                boolean httpExempt = nonAiHttp.stream().anyMatch(n -> cls.equals(n) || cls.startsWith(n + "$"));
                                return new MethodVisitor(Opcodes.ASM9) {
                                        @Override
                                        public void visitFieldInsn(int opcode, String owner, String fname, String fdesc) {
                                                if ((opcode == Opcodes.GETFIELD || opcode == Opcodes.GETSTATIC) && HTTP_TYPES.contains(fdesc) && !httpExempt) {
                                                        g.genSinks.add(me);
                                                        g.sinkWhy.putIfAbsent(me, "HTTP client field " + owner + "." + fname);
                                                }
                                        }

                                        @Override
                                        public void visitMethodInsn(int opcode, String owner, String mname, String mdesc, boolean itf) {
                                                if (owner.startsWith(PKG)) {
                                                        out.add(owner + "." + mname + mdesc);
                                                        if (isStoreOwner(owner, stores) && isRead(mname)) {
                                                                g.readSinks.add(me);
                                                                g.sinkWhy.putIfAbsent(me, "AI artifact store " + owner.substring(owner.lastIndexOf('/') + 1) + "." + mname);
                                                        }
                                                }
                                        }

                                        @Override
                                        public void visitInvokeDynamicInsn(String n, String d, Handle bsm, Object... args) {
                                                for (Object a : args) {
                                                        if (a instanceof Handle h && h.getOwner().startsWith(PKG)) {
                                                                out.add(h.getOwner() + "." + h.getName() + h.getDesc());
                                                        }
                                                }
                                        }
                                };
                        }
                }, ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
        }

        static boolean isRead(String m) {
                return m.startsWith("find") || m.startsWith("get") || m.startsWith("read") || m.startsWith("query") || m.startsWith("stream")
                                || m.startsWith("load") || m.startsWith("list") || m.startsWith("count") || m.startsWith("search");
        }

        /** 인터페이스/상위 클래스 호출을 구현 메서드로 넓힌다(가상 호출). */
        static Set<String> targets(Graph g, String callee) {
                Set<String> out = new HashSet<>();
                out.add(callee);
                int dot = callee.indexOf('.');
                String owner = callee.substring(0, dot);
                String sig = callee.substring(dot + 1);
                for (String c : g.classes) {
                        if (!c.equals(owner) && isSubtype(g, c, owner) && g.methodsOf.getOrDefault(c, Set.of()).contains(sig)) {
                                out.add(c + "." + sig);
                        }
                }
                // 상속받은 구현(호출 owner 에 메서드가 없고 상위에 있을 때)
                String s = owner;
                while (s != null && s.startsWith(PKG) && !g.methodsOf.getOrDefault(s, Set.of()).contains(sig)) {
                        s = g.superOf.get(s);
                        if (s != null && g.methodsOf.getOrDefault(s, Set.of()).contains(sig)) {
                                out.add(s + "." + sig);
                        }
                }
                return out;
        }

        static boolean isSubtype(Graph g, String c, String target) {
                Deque<String> q = new ArrayDeque<>();
                q.add(c);
                Set<String> seen = new HashSet<>();
                while (!q.isEmpty()) {
                        String x = q.poll();
                        if (x == null || !seen.add(x)) {
                                continue;
                        }
                        if (x.equals(target)) {
                                return true;
                        }
                        String sup = g.superOf.get(x);
                        if (sup != null) {
                                q.add(sup);
                        }
                        q.addAll(g.interfacesOf.getOrDefault(x, List.of()));
                }
                return false;
        }

        /** 도달 결과: GEN/READ 여부 + 처음 닿은 싱크의 사유(진단용). */
        record Reach(boolean gen, boolean read, String why) { }

        static Reach reach(Graph g, String start, Map<String, Set<String>> expandCache) {
                Deque<String> q = new ArrayDeque<>();
                q.add(start);
                Set<String> seen = new HashSet<>();
                boolean gen = false;
                boolean read = false;
                String why = null;
                while (!q.isEmpty()) {
                        String m = q.poll();
                        if (!seen.add(m)) {
                                continue;
                        }
                        if (g.genSinks.contains(m)) {
                                gen = true;
                                why = why == null ? g.sinkWhy.get(m) : why;
                        }
                        if (g.readSinks.contains(m)) {
                                read = true;
                                why = why == null ? g.sinkWhy.get(m) : why;
                        }
                        for (String callee : g.edges.getOrDefault(m, Set.of())) {
                                for (String t : expandCache.computeIfAbsent(callee, c -> targets(g, c))) {
                                        if (!seen.contains(t)) {
                                                q.add(t);
                                        }
                                }
                        }
                }
                return new Reach(gen, read, why);
        }

        /** 컨트롤러 엔드포인트 → 바이트코드 메서드 id. */
        static Map<String, String> handlers() throws Exception {
                Map<String, String> out = new TreeMap<>();
                // @Conditional(기능 플래그)로 꺼진 컨트롤러도 빠짐없이 분류한다 — 조건 평가를 건너뛰고 @Controller 계열이면 후보.
                var p = new org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider(false) {
                        @Override
                        protected boolean isCandidateComponent(org.springframework.core.type.classreading.MetadataReader mr) {
                                return mr.getAnnotationMetadata().isAnnotated(org.springframework.stereotype.Controller.class.getName());
                        }
                };
                for (var bd : p.findCandidateComponents("com.studybridge.api")) {
                        Class<?> c = Class.forName(bd.getBeanClassName());
                        RequestMapping base = AnnotatedElementUtils.findMergedAnnotation(c, RequestMapping.class);
                        String[] bases = base == null || base.path().length == 0 ? new String[]{""} : base.path();
                        for (Method m : c.getDeclaredMethods()) {
                                RequestMapping rm = AnnotatedElementUtils.findMergedAnnotation(m, RequestMapping.class);
                                if (rm == null) {
                                        continue;
                                }
                                String[] paths = rm.path().length == 0 ? new String[]{""} : rm.path();
                                var methods = rm.method().length == 0 ? org.springframework.web.bind.annotation.RequestMethod.values() : rm.method();
                                for (String b : bases) {
                                        for (String path : paths) {
                                                for (var hm : methods) {
                                                        out.put(hm.name() + " " + b + path,
                                                                        c.getName().replace('.', '/') + "." + m.getName() + Type.getMethodDescriptor(m));
                                                }
                                        }
                                }
                        }
                }
                return out;
        }

        static Map<String, Reach> classify() throws Exception {
                Graph g = build();
                Map<String, Set<String>> cache = new HashMap<>();
                Map<String, Reach> out = new LinkedHashMap<>();
                for (var e : handlers().entrySet()) {
                        out.put(e.getKey(), reach(g, e.getValue(), cache));
                }
                return out;
        }

        @Test
        void everyAiReachingEndpointIsRegisteredOrJustified() throws Exception {
                Map<String, Reach> all = classify();
                Set<String> registered = new HashSet<>();
                AiQualityGateCoverage.ROUTES.forEach(r -> registered.add(r.method() + " " + r.pattern()));
                List<String> unregistered = new ArrayList<>();
                all.forEach((route, r) -> {
                        if ((r.gen() || r.read()) && !registered.contains(route) && !AiRouteExposurePolicy.NOT_USER_EXPOSED.containsKey(route)) {
                                unregistered.add(route + "  [" + (r.gen() ? "GEN" : "") + (r.read() ? " READ" : "") + "] via " + r.why());
                        }
                });
                assertEquals(List.of(), unregistered,
                                "AI 생성/저장본에 닿는 미등록 엔드포인트 — AiQualityGateCoverage.ROUTES 또는 AiRouteExposurePolicy.NOT_USER_EXPOSED(사유)에 등록");
                assertTrue(all.size() > 100, "엔드포인트 수집이 비정상적으로 적다: " + all.size());
        }

        @Test
        void registeredAiRoutesReallyReachAiCode() throws Exception {
                Map<String, Reach> all = classify();
                List<String> dead = new ArrayList<>();
                for (AiQualityGateCoverage.Route r : AiQualityGateCoverage.ROUTES) {
                        if (r.status() == AiQualityGateCoverage.Status.EXEMPT) {
                                continue;
                        }
                        Reach x = all.get(r.method() + " " + r.pattern());
                        if (x == null || !(x.gen() || x.read())) {
                                dead.add(r.method() + " " + r.pattern());
                        }
                }
                assertEquals(List.of(), dead, "레지스트리에는 AI 경로로 있으나 AI 생성/저장본에 닿지 않는 항목(분류 오류)");
        }

        @Test
        void notExposedEntriesExistAndHaveReasons() throws Exception {
                Map<String, Reach> all = classify();
                List<String> bad = new ArrayList<>();
                AiRouteExposurePolicy.NOT_USER_EXPOSED.forEach((route, why) -> {
                        if (!all.containsKey(route) || why == null || why.isBlank()) {
                                bad.add(route);
                        }
                });
                assertEquals(List.of(), bad, "존재하지 않거나 사유 없는 NOT_USER_EXPOSED 항목");
        }

        @Test
        void classificationSanityOnKnownRoutes() throws Exception {
                Map<String, Reach> all = classify();
                assertTrue(all.get("POST /api/materials/{materialId}/question").gen(), "자료 질문 = ai07 생성");
                assertTrue(all.get("POST /api/agent-rooms/{roomId}/chat/stream").gen(), "학습메이트 SSE = ai07 생성");
                assertTrue(all.get("GET /api/review-notes").read(), "오답노트 목록 = AI 저장본");
                Reach login = all.get("POST /api/users/login");
                assertTrue(login != null && !login.gen() && !login.read(), "로그인은 AI 경로가 아니다(무차별 차단 금지)");
                Reach timer = all.entrySet().stream().filter(e -> e.getKey().contains("/api/timers")).map(Map.Entry::getValue).findFirst().orElse(null);
                assertTrue(timer == null || (!timer.gen() && !timer.read()), "타이머는 AI 경로가 아니다");
                long ai = all.values().stream().filter(r -> r.gen() || r.read()).count();
                assertTrue(ai < all.size() / 2, "AI 도달 엔드포인트가 과반이면 분류가 과도하다: " + ai + "/" + all.size());
        }
}

