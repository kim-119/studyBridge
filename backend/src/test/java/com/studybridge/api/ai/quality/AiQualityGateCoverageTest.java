package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.core.type.filter.AnnotationTypeFilter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 사용자 노출 AI 경로 커버리지 증명:
 *  1) 레지스트리의 모든 (method, pattern) 이 실제 컨트롤러 매핑에 존재한다(죽은 항목 없음).
 *  2) 게이트 ON: BLOCKED_WHEN_GATE_ON 경로는 503 AI_QUALITY_GATE_NOT_WIRED(본문에 AI 결과 없음), GATED/비AI 경로는 통과.
 *  3) 게이트 OFF: 아무것도 막지 않는다(기존 기능 회귀 없음).
 */
class AiQualityGateCoverageTest {

        static Set<String> controllerMappings() throws Exception {
                ClassPathScanningCandidateComponentProvider p = new ClassPathScanningCandidateComponentProvider(false);
                p.addIncludeFilter(new AnnotationTypeFilter(RestController.class));
                Set<String> out = new HashSet<>();
                for (BeanDefinition bd : p.findCandidateComponents("com.studybridge.api.controller")) {
                        Class<?> c = Class.forName(bd.getBeanClassName());
                        RequestMapping base = AnnotatedElementUtils.findMergedAnnotation(c, RequestMapping.class);
                        String[] bases = base == null || base.path().length == 0 ? new String[]{""} : base.path();
                        for (Method m : c.getDeclaredMethods()) {
                                RequestMapping rm = AnnotatedElementUtils.findMergedAnnotation(m, RequestMapping.class);
                                if (rm == null) {
                                        continue;
                                }
                                String[] paths = rm.path().length == 0 ? new String[]{""} : rm.path();
                                for (String b : bases) {
                                        for (String path : paths) {
                                                for (var httpMethod : rm.method()) {
                                                        out.add(httpMethod.name() + " " + b + path);
                                                }
                                        }
                                }
                        }
                }
                return out;
        }

        @Test
        void everyRegisteredRouteExistsInControllers() throws Exception {
                Set<String> mappings = controllerMappings();
                List<String> stale = new ArrayList<>();
                for (AiQualityGateCoverage.Route r : AiQualityGateCoverage.ROUTES) {
                        if (!mappings.contains(r.method() + " " + r.pattern())) {
                                stale.add(r.method() + " " + r.pattern());
                        }
                }
                assertEquals(List.of(), stale, "컨트롤러에 없는 레지스트리 항목");
                assertEquals(AiQualityGateCoverage.ROUTES.size(),
                                AiQualityGateCoverage.ROUTES.stream().map(r -> r.method() + " " + r.pattern()).distinct().count(), "중복 항목");
        }

        @Test
        void gateOnBlocksUnwiredRoutesAndPassesGatedOnes() throws Exception {
                AiQualityGateCoverage cov = new AiQualityGateCoverage(AiQualityGateSettings.forTest(true));
                for (AiQualityGateCoverage.Route r : AiQualityGateCoverage.ROUTES) {
                        String path = r.pattern().replaceAll("\\{[^}]+}", "7");
                        MockHttpServletRequest req = new MockHttpServletRequest(r.method(), path);
                        MockHttpServletResponse res = new MockHttpServletResponse();
                        boolean pass = cov.preHandle(req, res, new Object());
                        if (r.status() == AiQualityGateCoverage.Status.BLOCKED_WHEN_GATE_ON) {
                                assertFalse(pass, path);
                                assertEquals(503, res.getStatus());
                                assertTrue(res.getContentAsString().contains("AI_QUALITY_GATE_NOT_WIRED"));
                        } else {
                                assertTrue(pass, path);
                        }
                }
                MockHttpServletResponse res = new MockHttpServletResponse();
                assertTrue(cov.preHandle(new MockHttpServletRequest("GET", "/api/materials/7/memo"), res, new Object()), "비AI 경로");
                assertTrue(cov.preHandle(new MockHttpServletRequest("PUT", "/api/materials/7/summary"), res, new Object()), "메서드 다름");
        }

        @Test
        void gateOffBlocksNothing() throws Exception {
                AiQualityGateCoverage cov = new AiQualityGateCoverage(AiQualityGateSettings.forTest(false));
                for (AiQualityGateCoverage.Route r : AiQualityGateCoverage.ROUTES) {
                        MockHttpServletResponse res = new MockHttpServletResponse();
                        assertTrue(cov.preHandle(new MockHttpServletRequest(r.method(), r.pattern().replaceAll("\\{[^}]+}", "7")), res,
                                        new Object()));
                        assertEquals(200, res.getStatus());
                }
        }

        @Test
        void coverageNumbersAreReported() {
                // 운영 ON 전환 Go 조건: BLOCKED_WHEN_GATE_ON == 0. 현재 값은 PR/인계 문서에 그대로 보고한다(PASS 로 포장 금지).
                long gated = AiQualityGateCoverage.count(AiQualityGateCoverage.Status.GATED);
                long blocked = AiQualityGateCoverage.count(AiQualityGateCoverage.Status.BLOCKED_WHEN_GATE_ON);
                long exempt = AiQualityGateCoverage.count(AiQualityGateCoverage.Status.EXEMPT);
                System.out.printf("[COVERAGE] routes=%d gated=%d blockedWhenGateOn=%d exempt=%d%n",
                                AiQualityGateCoverage.ROUTES.size(), gated, blocked, exempt);
                assertTrue(gated >= 2);
                assertEquals(AiQualityGateCoverage.ROUTES.size(), gated + blocked + exempt);
        }

        @Test
        void encodedPathCannotBypassBlockAndResolvedPatternIsUsed() throws Exception {
                AiQualityGateCoverage cov = new AiQualityGateCoverage(AiQualityGateSettings.forTest(true));
                MockHttpServletRequest encoded = new MockHttpServletRequest("POST", "/api/materials/1/qu%69z");
                MockHttpServletResponse r1 = new MockHttpServletResponse();
                assertFalse(cov.preHandle(encoded, r1, new Object()), "디코딩된 경로로 매칭(인코딩 우회 차단)");
                assertEquals(503, r1.getStatus());
                MockHttpServletRequest resolved = new MockHttpServletRequest("POST", "/whatever");
                resolved.setAttribute(org.springframework.web.servlet.HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE,
                                "/api/materials/{materialId}/quiz");
                MockHttpServletResponse r2 = new MockHttpServletResponse();
                assertFalse(cov.preHandle(resolved, r2, new Object()), "MVC 가 고른 핸들러 패턴 기준");
                assertEquals(503, r2.getStatus());
        }

        // ── Phase D2: 허위 GATED 방지 — 모든 GATED 경로는 실제 차단을 실행으로 보이는 @GateEvidence 테스트를 가진다 ──

        static java.util.Map<String, List<String>> gateEvidence() throws Exception {
                var resolver = new org.springframework.core.io.support.PathMatchingResourcePatternResolver();
                var readers = new org.springframework.core.type.classreading.CachingMetadataReaderFactory(resolver);
                java.util.Map<String, List<String>> out = new java.util.TreeMap<>();
                for (var res : resolver.getResources("classpath*:com/studybridge/api/**/*Test.class")) {
                        String cn = readers.getMetadataReader(res).getClassMetadata().getClassName();
                        Class<?> c;
                        try {
                                c = Class.forName(cn, false, AiQualityGateCoverageTest.class.getClassLoader());
                        } catch (Throwable t) {
                                continue;
                        }
                        for (Method m : c.getDeclaredMethods()) {
                                GateEvidence ev = m.getAnnotation(GateEvidence.class);
                                if (ev == null) {
                                        continue;
                                }
                                assertTrue(m.isAnnotationPresent(Test.class), "@GateEvidence 는 @Test 메서드에만: " + cn + "#" + m.getName());
                                for (String route : ev.value()) {
                                        out.computeIfAbsent(route, k -> new ArrayList<>()).add(c.getSimpleName() + "#" + m.getName());
                                }
                        }
                }
                return out;
        }

        @Test
        void everyGatedRouteHasExecutableEvidenceAndEvidenceTargetsGatedRoutes() throws Exception {
                java.util.Map<String, List<String>> ev = gateEvidence();
                List<String> missing = new ArrayList<>();
                for (AiQualityGateCoverage.Route r : AiQualityGateCoverage.ROUTES) {
                        if (r.status() == AiQualityGateCoverage.Status.GATED && !ev.containsKey(r.method() + " " + r.pattern())) {
                                missing.add(r.method() + " " + r.pattern());
                        }
                }
                assertEquals(List.of(), missing, "GATED 라벨만 있고 증거 테스트가 없는 경로(허위 연결)");
                Set<String> gated = new HashSet<>();
                AiQualityGateCoverage.ROUTES.stream().filter(r -> r.status() == AiQualityGateCoverage.Status.GATED)
                                .forEach(r -> gated.add(r.method() + " " + r.pattern()));
                List<String> dangling = ev.keySet().stream().filter(k -> !gated.contains(k)).toList();
                assertEquals(List.of(), dangling, "GATED 가 아닌 경로를 가리키는 증거 표식");
        }
}

