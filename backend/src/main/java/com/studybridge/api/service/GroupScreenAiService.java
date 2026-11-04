package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.dto.ScreenAiDTO.AnalyzeRequest;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.VideoConnectionMetadata.Kind;
import com.studybridge.api.service.VisionUpstreamClient.VisionCall;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Scheduler;
import reactor.core.scheduler.Schedulers;

import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Pattern;

/**
 * 그룹스터디 화면공유 AI 분석(멀티모달 Vision) — 브라우저가 캡처한 현재 프레임 1장 + 질문을 ai07 로 중계한다.
 *
 * <p>검증 순서(값싼 것부터, 사용자 입력은 로그에 남기지 않는다):</p>
 * <ol>
 *   <li>기능 플래그(ai.vision.enabled) → JWT 사용자(컨트롤러) → 그룹 JOINED 멤버</li>
 *   <li>요청 형식: connectionId/streamId/clientRequestId 패턴, 질문 1~1000자, JPEG Base64(크기·해상도, {@link ScreenAiImageValidator})</li>
 *   <li>사용자별 동시 1건(Redis 잠금) · 사용자별/그룹별 분당 한도</li>
 *   <li>OpenVidu 실시간 상태(Source of Truth, 한 번 조회): 대상 Connection 이 이 방의 서버 발급 SCREEN 이고 active, 소유 PRIMARY 가 살아 있고,
 *       요청한 streamId 를 지금 SCREEN 타입으로 게시 중 → 공유자(serverData.userId) 식별. 질문자도 이 방에 active PRIMARY 로 접속해 있어야
 *       한다(지금 그 화면을 볼 수 있는 사람만 분석). 공유자가 아직 JOINED 멤버인지 확인.</li>
 *   <li>공유자 동의({@link ScreenAiConsentStore}, opt-in) — 본인 화면은 질문 자체가 동의다.</li>
 * </ol>
 *
 * <p>호출: {@link VisionUpstreamClient}(PRIMARY 전용, 전용 타임아웃). requestId 는 서버가 UUID 로 만든다(재시도도 새 id).
 * 결과는 질문자에게 HTTP 응답으로만 돌려준다 — 답변·질문·이미지를 DB·Redis·로그에 저장하지 않는다.
 * 취소: 브라우저가 보낸 clientRequestId 로 DELETE 하면 ai07 연결을 끊어(ai07 은 연결 끊김 시 추론 취소) GPU 를 돌려준다.</p>
 */
@Service
@Slf4j
public class GroupScreenAiService {

    static final String FEATURE = "screen-ai";
    private static final Pattern STREAM_ID = Pattern.compile("^[A-Za-z0-9_.:-]{1,128}$");
    private static final Pattern CLIENT_REQUEST_ID = Pattern.compile("^[A-Za-z0-9_-]{8,64}$");
    private static final Set<String> MIMES = Set.of(ScreenAiImageValidator.JPEG);

    private final GroupVideoCallService videoCallService;
    private final OpenViduService openVidu;
    private final GroupStudyMemberRepository memberRepository;
    private final UserRepository userRepository;
    private final ObjectMapper objectMapper;
    private final ScreenAiConsentStore consentStore;
    private final AiRequestGuard guard;
    private final VisionUpstreamClient upstream;
    private final Clock clock;

    private final boolean enabled;
    private final int maxQuestionChars;
    private final ScreenAiImageValidator.Limits imageLimits;
    private final int perUserPerMinute;
    private final int perGroupPerMinute;

    /** userId:clientRequestId → 취소 신호. 같은 JVM 에서만 취소할 수 있다(운영 단일 인스턴스). */
    private final Map<String, Sinks.One<Boolean>> inflight = new ConcurrentHashMap<>();

    /**
     * 이벤트 루프에서 끝난 요청의 Redis 잠금 해제 전용. 공용 boundedElastic(ChatService JDBC 영속화 등)과 분리해 Redis 지연이 다른 AI 기능으로
     * 번지지 않게 한다. 동시 해제 수는 진행 중인 비전 요청 수(전용 연결 풀 + 대기열)를 넘지 않는다.
     */
    private final Scheduler cleanupScheduler = Schedulers.newBoundedElastic(4, 1000, "screen-ai-cleanup", 60, true);

    /** 품질 게이트(response-quality.v1, VISION_CAPTION). 생성자 시그니처 보존을 위해 setter 주입 — null 이면 게이트 OFF. */
    private AiResponseQualityGate qualityGate;
    /** 평가기 서킷 상태 확인용(열려 있으면 VLM 추론 자체를 하지 않는다 — 어차피 노출할 수 없다). */
    private QualityEvaluatorClient qualityEvaluator;

    /** 재생성으로 해결되지 않는 거절 사유: ai07 은 판독 근거(관찰)를 응답에 싣지 않는다(인계 5.3) → 재생성해도 근거가 생기지 않는다. */
    static final Set<String> NO_REGENERATION_CODES = Set.of("VISION_NO_OBSERVATION_EVIDENCE");

    @Autowired(required = false)
    public void setQualityGate(AiResponseQualityGate qualityGate) {
        this.qualityGate = qualityGate;
    }

    @Autowired(required = false)
    public void setQualityEvaluator(QualityEvaluatorClient qualityEvaluator) {
        this.qualityEvaluator = qualityEvaluator;
    }

    private boolean qualityGateOn() {
        return qualityGate != null && qualityGate.enabled();
    }

    public GroupScreenAiService(GroupVideoCallService videoCallService,
                                OpenViduService openVidu,
                                GroupStudyMemberRepository memberRepository,
                                UserRepository userRepository,
                                ObjectMapper objectMapper,
                                ScreenAiConsentStore consentStore,
                                AiRequestGuard guard,
                                VisionUpstreamClient upstream,
                                Clock clock,
                                @Value("${ai.vision.enabled:true}") boolean enabled,
                                @Value("${ai.vision.max-question-chars:1000}") int maxQuestionChars,
                                @Value("${ai.vision.max-image-bytes:1048576}") int maxImageBytes,
                                @Value("${ai.vision.max-long-side:1280}") int maxLongSide,
                                @Value("${ai.vision.min-side:32}") int minSide,
                                @Value("${ai.vision.rate-limit.per-user-per-minute:6}") int perUserPerMinute,
                                @Value("${ai.vision.rate-limit.per-group-per-minute:30}") int perGroupPerMinute) {
        this.videoCallService = videoCallService;
        this.openVidu = openVidu;
        this.memberRepository = memberRepository;
        this.userRepository = userRepository;
        this.objectMapper = objectMapper;
        this.consentStore = consentStore;
        this.guard = guard;
        this.upstream = upstream;
        this.clock = clock;
        this.enabled = enabled;
        this.maxQuestionChars = Math.max(1, maxQuestionChars);
        this.imageLimits = new ScreenAiImageValidator.Limits(Math.max(1024, maxImageBytes), Math.max(64, maxLongSide), Math.max(1, minSide));
        this.perUserPerMinute = Math.max(1, perUserPerMinute);
        this.perGroupPerMinute = Math.max(1, perGroupPerMinute);
    }

    // ───────────────────────────── 화면공유 목록 ─────────────────────────────

    /** 지금 분석할 수 있는 화면공유 목록(공유자·스트림·동의 상태). 토큰·IP 는 내보내지 않는다. */
    public Map<String, Object> listShares(long userId, long groupId) {
        requireJoinedMember(userId, groupId);
        Room room = loadRoom(groupId);
        List<Map<String, Object>> shares = new ArrayList<>();
        Map<Long, String> names = new HashMap<>();
        for (Share s : room.shares()) {
            boolean mine = s.sharerUserId() == userId;
            boolean consent = consentStore.isAllowed(groupId, s.connectionId(), s.sharerUserId());
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("connectionId", s.connectionId());
            item.put("streamId", s.streamId());
            item.put("sharerUserId", s.sharerUserId());
            item.put("sharerName", names.computeIfAbsent(s.sharerUserId(), this::displayName));
            item.put("isMine", mine);
            item.put("aiConsent", consent);
            item.put("analyzable", mine || consent);
            item.put("deviceType", s.deviceType());
            item.put("activeAt", s.activeAt());
            shares.add(item);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("enabled", enabled && upstream.configured());
        body.put("viewerConnected", room.hasActivePrimary(userId));
        body.put("shares", shares);
        body.put("limits", limits());
        body.put("fetchedAt", clock.millis());
        return body;
    }

    private Map<String, Object> limits() {
        Map<String, Object> l = new LinkedHashMap<>();
        l.put("maxQuestionChars", maxQuestionChars);
        l.put("maxImageBytes", imageLimits.maxBytes());
        l.put("maxLongSide", imageLimits.maxLongSide());
        l.put("minSide", imageLimits.minSide());
        l.put("perUserPerMinute", perUserPerMinute);
        l.put("timeoutSeconds", upstream.timeout().toSeconds());
        return l;
    }

    // ───────────────────────────── 공유자 동의 ─────────────────────────────

    /** 내 화면공유에 대한 AI 분석 허용/철회. 다른 사람의 공유·PRIMARY Connection 이면 403. */
    public Map<String, Object> setConsent(long userId, long groupId, String connectionId, boolean allowed) {
        requireJoinedMember(userId, groupId);
        if (!VideoConnectionMetadata.isValidConnectionId(connectionId)) {
            throw badRequest("connectionId 형식이 올바르지 않습니다.");
        }
        Map<String, Object> c = openVidu.getConnection(videoCallService.sessionIdFor(groupId), connectionId)
                .orElseThrow(this::shareNotFound);
        VideoConnectionMetadata m = VideoConnectionMetadata.fromRest(objectMapper, c.get("serverData"), c.get("clientData"));
        if (!m.serverVerified() || m.kind() != Kind.SCREEN || m.userId() == null) throw shareNotFound();
        if (m.userId() != userId) {
            throw new ScreenAiException(HttpStatus.FORBIDDEN, "NOT_SHARE_OWNER", "본인의 화면공유만 AI 분석 허용 여부를 바꿀 수 있습니다.");
        }
        consentStore.set(groupId, connectionId, userId, allowed);
        log.info("[SCREEN-AI] consent updated groupId={} userId={} connectionId={} allowed={}", groupId, userId, connectionId, allowed);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("connectionId", connectionId);
        body.put("aiConsent", allowed);
        return body;
    }

    // ───────────────────────────── 분석 ─────────────────────────────

    public Mono<Map<String, Object>> analyze(long userId, long groupId, AnalyzeRequest req) {
        long startedAt = clock.millis();
        if (!enabled) {
            throw new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_DISABLED", "AI 화면 분석 기능이 지금은 꺼져 있습니다.");
        }
        requireJoinedMember(userId, groupId);
        if (req == null) throw badRequest("요청 본문이 필요합니다.");
        if (!VideoConnectionMetadata.isValidConnectionId(req.connectionId())) throw badRequest("분석할 화면(connectionId)이 올바르지 않습니다.");
        if (req.streamId() == null || !STREAM_ID.matcher(req.streamId()).matches()) throw badRequest("분석할 화면 스트림(streamId)이 올바르지 않습니다.");
        String clientRequestId = req.clientRequestId();
        if (clientRequestId != null && !CLIENT_REQUEST_ID.matcher(clientRequestId).matches()) throw badRequest("clientRequestId 형식이 올바르지 않습니다.");
        String question = req.question() == null ? "" : req.question().strip();
        if (question.isEmpty()) {
            throw new ScreenAiException(HttpStatus.UNPROCESSABLE_ENTITY, "SCREEN_AI_QUESTION_INVALID", "질문을 입력해 주세요.");
        }
        if (question.codePointCount(0, question.length()) > maxQuestionChars) {
            throw new ScreenAiException(HttpStatus.UNPROCESSABLE_ENTITY, "SCREEN_AI_QUESTION_INVALID",
                    "질문은 최대 " + maxQuestionChars + "자까지 입력할 수 있습니다.");
        }
        String mime = ScreenAiImageValidator.normalizeMime(req.mime() == null ? ScreenAiImageValidator.JPEG : req.mime());
        ScreenAiImageValidator.ValidatedImage image = ScreenAiImageValidator.validate(req.image(), mime, imageLimits);

        final boolean gateOn = qualityGateOn();
        AiRequestGuard.Lock lock = guard.tryLock(AiRequestGuard.lockKey(FEATURE, userId, "inflight"), lockTtl(gateOn));
        if (!lock.acquired()) {
            throw new ScreenAiException(HttpStatus.TOO_MANY_REQUESTS, "SCREEN_AI_IN_PROGRESS",
                    "이전 화면 분석이 아직 진행 중입니다. 끝난 뒤 다시 질문해 주세요.", true, 3);
        }
        AtomicBoolean lockReleased = new AtomicBoolean(false);
        Share share;
        String sharerName;
        try {
            if (!guard.allow(AiRequestGuard.rateKey(FEATURE, userId), perUserPerMinute, Duration.ofMinutes(1))) {
                throw new ScreenAiException(HttpStatus.TOO_MANY_REQUESTS, "SCREEN_AI_RATE_LIMITED",
                        "화면 분석은 1분에 " + perUserPerMinute + "번까지 요청할 수 있습니다. 잠시 후 다시 시도해 주세요.", true, 60);
            }
            if (!guard.allow(AiRequestGuard.PREFIX + "rate:" + FEATURE + ":g" + groupId, perGroupPerMinute, Duration.ofMinutes(1))) {
                throw new ScreenAiException(HttpStatus.TOO_MANY_REQUESTS, "SCREEN_AI_RATE_LIMITED",
                        "이 스터디방의 화면 분석 요청이 많습니다. 잠시 후 다시 시도해 주세요.", true, 30);
            }
            share = authorize(userId, groupId, req.connectionId(), req.streamId());
            // 공유자 이름(RDS)은 여기(요청 스레드)서 미리 읽는다 — ai07 응답 콜백(reactor-netty 이벤트 루프)에서 DB 를 부르지 않는다.
            sharerName = displayName(share.sharerUserId());
        } catch (RuntimeException e) {
            releaseLockOnce(lock, lockReleased, null);
            throw e;
        }

        String requestId = UUID.randomUUID().toString();
        String cancelKey = clientRequestId == null ? null : userId + ":" + clientRequestId;
        Sinks.One<Boolean> cancel = Sinks.one();
        if (cancelKey != null) inflight.put(cancelKey, cancel);
        VisionCall call = new VisionCall(requestId, groupId, share.streamId(), share.sharerUserId(), userId, question, image.base64(), mime);
        AtomicReference<String> outcome = new AtomicReference<>("CANCELLED");
        log.info("[SCREEN-AI] analyze start requestId={} groupId={} askerId={} sharerId={} connectionId={} image={}x{} bytes={} questionChars={}",
                requestId, groupId, userId, share.sharerUserId(), share.connectionId(), image.width(), image.height(), image.bytes(),
                question.length());

        // 게이트 ON: VLM 답변을 평가해 승인된 것만 응답한다(거절·평가 불가 = SCREEN_AI_QUALITY_* 명시 실패, 답변 본문 미노출).
        Mono<VisionOutcome> outcome$ = gateOn ? gatedAnalyze(call) : upstream.analyze(call).map(r -> new VisionOutcome(r, null));
        Mono<Map<String, Object>> call$ = outcome$.map(o -> {
            VisionUpstreamClient.VisionResult r = o.result();
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("requestId", requestId);
            body.put("clientRequestId", clientRequestId);
            body.put("answer", r.answer());
            body.put("model", r.model());
            body.put("connectionId", share.connectionId());
            body.put("streamId", share.streamId());
            Map<String, Object> sharer = new LinkedHashMap<>();
            sharer.put("userId", share.sharerUserId());
            sharer.put("name", sharerName);
            sharer.put("isMine", share.sharerUserId() == userId);
            body.put("sharer", sharer);
            Map<String, Object> img = new LinkedHashMap<>();
            img.put("width", image.width());
            img.put("height", image.height());
            img.put("bytes", image.bytes());
            body.put("image", img);
            body.put("latencyMs", clock.millis() - startedAt);
            body.put("upstreamLatencyMs", r.latencyMs());
            body.put("queueWaitMs", r.queueWaitMs());
            body.put("inferenceMs", r.inferenceMs());
            body.put("analyzedAt", clock.millis());
            if (o.decision() != null) {
                body.put("qualityStatus", "APPROVED");
                body.put("qualityScore", o.decision().score());
                body.put("verified", Boolean.TRUE);
            }
            return body;
        });
        // 취소 신호가 먼저 오면 firstWithSignal 이 ai07 호출을 구독 해제한다 → WebClient 연결 종료 → ai07 추론 취소.
        Mono<Map<String, Object>> cancelled$ = cancel.asMono().flatMap(x -> Mono.error(new ScreenAiException(
                HttpStatus.CONFLICT, "SCREEN_AI_CANCELLED", "화면 분석을 취소했습니다.")));
        return Mono.firstWithSignal(call$, cancelled$)
                .doOnSuccess(b -> outcome.set("OK"))
                .doOnError(e -> outcome.set(e instanceof ScreenAiException se ? se.getCode() : e.getClass().getSimpleName()))
                .doFinally(sig -> {
                    // 취소 핸들을 먼저 지운다 — 잠금이 풀린 뒤 같은 사용자의 다음 요청이 옛 핸들과 섞이지 않게.
                    if (cancelKey != null) inflight.remove(cancelKey, cancel);
                    log.info("[SCREEN-AI] analyze end requestId={} groupId={} askerId={} outcome={} signal={} latencyMs={}",
                            requestId, groupId, userId, outcome.get(), sig, clock.millis() - startedAt);
                    releaseLockOnce(lock, lockReleased, requestId);
                });
    }

    // ───────────────────────────── 품질 게이트(VISION_CAPTION) ─────────────────────────────

    record VisionOutcome(VisionUpstreamClient.VisionResult result, GateDecision decision) {}

    /** 사용자별 진행 중 잠금 TTL: 게이트 ON 이면 재생성(최대 2회)·평가 시간까지 덮는다(잠금이 처리 도중 풀려 동시 요청이 끼지 않게). */
    Duration lockTtl(boolean gateOn) {
        if (!gateOn) return upstream.timeout().plusSeconds(30);
        int attempts = 1 + qualityGate.settings().maxRegenerations();
        long evalMs = qualityGate.settings().evaluateTimeoutMs() + qualityGate.settings().queueWaitMs() + 2000;
        return upstream.timeout().multipliedBy(attempts).plusMillis(evalMs * attempts).plusSeconds(30);
    }

    /**
     * 생성 → 평가(VISION_CAPTION / vision_text, 근거 없음 — ai07 이 판독 근거를 돌려주지 않는다) → 거절 시 재생성(최대 settings.maxRegenerations).
     * AiResponseQualityGate.generateApproved 와 같은 규칙을 리액티브로 따른다(이벤트 루프를 막지 않고, 취소 시 진행 중 VLM/평가 호출도 끊긴다):
     *  평가기 장애(VALIDATION_ERROR) = 즉시 중단, 같은 초안 반복 = 중단, 재생성 중 상류 실패 = 중단(직전 판정으로 실패), 근거 부재 거절 = 재생성 안 함,
     *  다음 시도가 기존 단일 호출 시간 상한을 넘길 것으로 보이면 재생성 안 함.
     *  첫 생성의 상류 오류는 기존 SCREEN_AI_* 오류 그대로. 서킷 열림이면 VLM 을 부르지 않는다.
     */
    Mono<VisionOutcome> gatedAnalyze(VisionCall call) {
        if (qualityEvaluator != null && !qualityEvaluator.acceptingRequests()) {
            return Mono.error(qualityFailure(GateDecision.unavailable("EVALUATOR_CIRCUIT_OPEN", 0, 0)));
        }
        return visionAttempt(call, 0, null, ConcurrentHashMap.newKeySet(), clock.millis());
    }

    private Mono<VisionOutcome> visionAttempt(VisionCall base, int attempt, GateDecision previous, Set<String> seenDrafts, long startedAt) {
        VisionCall c = attempt == 0 ? base : new VisionCall(base.requestId() + "-r" + attempt, base.groupId(), base.streamId(),
                base.sharerUserId(), base.askerUserId(), base.question(), base.imageBase64(), base.mime());
        Mono<VisionUpstreamClient.VisionResult> gen = upstream.analyze(c);
        if (attempt > 0) {
            gen = gen.onErrorResume(e -> !(e instanceof ScreenAiException se && "SCREEN_AI_CANCELLED".equals(se.getCode())),
                    e -> Mono.error(qualityFailure(previous)));
        }
        return gen.flatMap(r -> {
            String answer = r.answer();
            if (!seenDrafts.add(answer)) {
                return Mono.error(qualityFailure(GateDecision.noDraft("IDENTICAL_DRAFT_REPEATED", attempt + 1)));
            }
            String model = r.model() != null && r.model().length() <= 128 ? r.model() : null;
            AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(base.requestId(), ResponseQualityV1.TaskType.VISION_CAPTION,
                    ResponseQualityV1.OutputKind.VISION_TEXT, base.question(), List.of(), ResponseQualityV1.Constraints.empty(), model);
            return qualityGate.evaluateOnce(spec, base.requestId() + ".qv" + attempt, attempt, AiResponseQualityGate.text(answer))
                    .onErrorResume(e -> Mono.just(GateDecision.unavailable("EVALUATOR_EXCEPTION", attempt + 1, 0)))
                    .flatMap(d -> {
                        if (d.approved()) {
                            return Mono.just(new VisionOutcome(r, d));
                        }
                        // 시간 예산: 지금까지의 시도 평균만큼 한 번 더 걸려도 기존 단일 호출 상한(ai.vision.timeout-seconds) 안이어야 재생성한다
                        //  (브라우저 대기 상한 SCREEN_AI_TIMEOUT_MS 는 이 상한 기준 — 재생성 때문에 클라이언트 타임아웃으로 끝나지 않게).
                        long elapsed = Math.max(0, clock.millis() - startedAt);
                        boolean overBudget = elapsed + elapsed / (attempt + 1) > upstream.timeout().toMillis();
                        boolean stop = d.qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR
                                || attempt >= qualityGate.settings().maxRegenerations()
                                || d.reasonCodes().stream().anyMatch(NO_REGENERATION_CODES::contains)
                                || overBudget;
                        log.info("[SCREEN-AI] quality requestId={} attempt={} status={} score={} codes={} elapsedMs={} next={}", base.requestId(),
                                attempt, d.qualityStatus(), d.score(), d.reasonCodes(), elapsed, stop ? "STOP" : "REGENERATE");
                        return stop ? Mono.<VisionOutcome>error(qualityFailure(d))
                                : visionAttempt(base, attempt + 1, d, seenDrafts, startedAt);
                    });
        });
    }

    /** 품질 거절/평가 불가 → SCREEN_AI_* 오류 형식({status, code, message, retryable, details}). 답변 본문·평가 사유 원문은 싣지 않는다. */
    static ScreenAiException qualityFailure(GateDecision d) {
        boolean unavailable = d.qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR;
        String errorCode = unavailable ? GateDecision.UNAVAILABLE : GateDecision.REJECTED;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("errorCode", errorCode);
        details.put("qualityStatus", d.qualityStatus().name());
        details.put("verified", Boolean.FALSE);
        details.put("attempts", d.attempts());
        if (d.reasonCodes() != null && !d.reasonCodes().isEmpty()) details.put("reasonCodes", d.reasonCodes());
        return new ScreenAiException(unavailable ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.UNPROCESSABLE_ENTITY,
                unavailable ? "SCREEN_AI_QUALITY_UNAVAILABLE" : "SCREEN_AI_QUALITY_REJECTED",
                GateDecision.userMessage(errorCode), true, unavailable ? 10 : null, details);
    }

    /**
     * 요청당 잠금을 정확히 한 번 해제한다(토큰 일치 시에만 지우는 {@link AiRequestGuard#release}).
     *
     * <p>ai07 응답·오류·응답 타임아웃은 reactor-netty 이벤트 루프나 Reactor 타이머(parallel) 스레드에서 끝난다. 그 스레드에서 Redis 를 부르면
     * Redis 지연(Lettuce 명령 타임아웃 60s) 동안 같은 루프의 다른 AI 호출(학습메이트 SSE·그룹 AI 등)이 멈추므로 전용 스케줄러로 넘긴다.
     * 요청 스레드(Tomcat — 검증 실패, DELETE 취소)에서는 지금처럼 바로 해제해, 취소 응답 시점에 잠금이 이미 풀려 있게 한다.</p>
     */
    private void releaseLockOnce(AiRequestGuard.Lock lock, AtomicBoolean released, String requestId) {
        if (!released.compareAndSet(false, true)) return;
        if (!Schedulers.isInNonBlockingThread()) {
            guard.release(lock);
            return;
        }
        try {
            cleanupScheduler.schedule(() -> guard.release(lock));
        } catch (RejectedExecutionException e) {
            // 정리 대기열이 가득 찼거나 종료 중 — 이벤트 루프에서 Redis 를 부르지 않고 잠금 TTL(응답 제한 + 30s) 만료에 맡긴다.
            log.warn("[SCREEN-AI] lock release deferred to TTL requestId={} ({})", requestId, e.getClass().getSimpleName());
        }
    }

    @PreDestroy
    void shutdown() {
        cleanupScheduler.dispose();
    }

    /** 진행 중인 내 분석 요청을 취소한다(멱등). ai07 연결을 끊어 추론도 멈춘다. */
    public Map<String, Object> cancel(long userId, long groupId, String clientRequestId) {
        requireJoinedMember(userId, groupId);
        if (clientRequestId == null || !CLIENT_REQUEST_ID.matcher(clientRequestId).matches()) throw badRequest("clientRequestId 형식이 올바르지 않습니다.");
        Sinks.One<Boolean> s = inflight.remove(userId + ":" + clientRequestId);
        boolean cancelled = s != null && s.tryEmitValue(Boolean.TRUE).isSuccess();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("clientRequestId", clientRequestId);
        body.put("cancelled", cancelled);
        return body;
    }

    // ───────────────────────────── 권한 판정 ─────────────────────────────

    record Share(String connectionId, String streamId, long sharerUserId, String ownerConnectionId, String deviceType, Long activeAt) {}

    /** OpenVidu active Connection 한 번 조회로 만든 방 상태. */
    record Room(List<Share> shares, Map<Long, Boolean> activePrimaryUsers) {
        boolean hasActivePrimary(long userId) {
            return activePrimaryUsers.containsKey(userId);
        }

        Optional<Share> find(String connectionId) {
            return shares.stream().filter(s -> s.connectionId().equals(connectionId)).findFirst();
        }
    }

    private Room loadRoom(long groupId) {
        List<Map<String, Object>> raw;
        try {
            raw = openVidu.listConnections(videoCallService.sessionIdFor(groupId), false);
        } catch (RuntimeException e) {
            throw new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "VIDEO_STATE_UNAVAILABLE",
                    "화상통화 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.", true, 5);
        }
        Map<String, Long> primaryOwner = new HashMap<>();
        Map<Long, Boolean> activeUsers = new HashMap<>();
        for (Map<String, Object> c : raw) {
            if (!"active".equals(c.get("status")) || !(c.get("connectionId") instanceof String id)) continue;
            VideoConnectionMetadata m = VideoConnectionMetadata.fromRest(objectMapper, c.get("serverData"), c.get("clientData"));
            if (m.kind() == Kind.PRIMARY && m.serverVerified() && m.userId() != null && sameGroup(m, groupId)) {
                primaryOwner.put(id, m.userId());
                activeUsers.put(m.userId(), Boolean.TRUE);
            }
        }
        List<Share> shares = new ArrayList<>();
        for (Map<String, Object> c : raw) {
            if (!"active".equals(c.get("status")) || !(c.get("connectionId") instanceof String id)) continue;
            VideoConnectionMetadata m = VideoConnectionMetadata.fromRest(objectMapper, c.get("serverData"), c.get("clientData"));
            if (m.kind() != Kind.SCREEN || !m.serverVerified() || m.userId() == null || !sameGroup(m, groupId)) continue;
            // 소유 PRIMARY 가 살아 있고 같은 사용자여야 한다(orphan·위조 귀속 제외).
            Long ownerUser = m.ownerConnectionId() == null ? null : primaryOwner.get(m.ownerConnectionId());
            if (ownerUser == null || !ownerUser.equals(m.userId())) continue;
            String streamId = screenStreamId(c);
            if (streamId == null) continue; // 접속만 하고 아직 게시 전
            Long activeAt = c.get("activeAt") instanceof Number n ? n.longValue() : null;
            shares.add(new Share(id, streamId, m.userId(), m.ownerConnectionId(), m.deviceType(), activeAt));
        }
        shares.sort((a, b) -> Long.compare(a.activeAt() == null ? 0 : a.activeAt(), b.activeAt() == null ? 0 : b.activeAt()));
        return new Room(List.copyOf(shares), Map.copyOf(activeUsers));
    }

    Share authorize(long askerUserId, long groupId, String connectionId, String streamId) {
        Room room = loadRoom(groupId);
        Share share = room.find(connectionId).orElseThrow(this::shareNotFound);
        if (!share.streamId().equals(streamId)) {
            throw new ScreenAiException(HttpStatus.CONFLICT, "SCREEN_STREAM_MISMATCH",
                    "선택한 화면공유가 다시 시작되었습니다. 화면을 다시 선택해 주세요.");
        }
        if (!room.hasActivePrimary(askerUserId)) {
            throw new ScreenAiException(HttpStatus.FORBIDDEN, "VIEWER_NOT_CONNECTED",
                    "화상통화에 접속한 참여자만 공유 화면을 분석할 수 있습니다.");
        }
        boolean own = share.sharerUserId() == askerUserId;
        if (!own && !memberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, share.sharerUserId(), GroupStudyMemberStatus.JOINED)) {
            throw shareNotFound();
        }
        if (!own && !consentStore.isAllowed(groupId, connectionId, share.sharerUserId())) {
            throw new ScreenAiException(HttpStatus.FORBIDDEN, "SHARER_CONSENT_REQUIRED",
                    "공유자가 이 화면의 AI 분석을 허용하지 않았습니다. 공유자에게 'AI 분석 허용'을 요청해 주세요.");
        }
        return share;
    }

    private static boolean sameGroup(VideoConnectionMetadata m, long groupId) {
        return m.groupId() == null || m.groupId() == groupId;
    }

    private static String screenStreamId(Map<String, Object> connection) {
        if (!(connection.get("publishers") instanceof List<?> pubs)) return null;
        for (Object p : pubs) {
            if (!(p instanceof Map<?, ?> pub) || !(pub.get("streamId") instanceof String sid)) continue;
            if (pub.get("mediaOptions") instanceof Map<?, ?> media && "SCREEN".equals(media.get("typeOfVideo"))) return sid;
        }
        return null;
    }

    private void requireJoinedMember(long userId, long groupId) {
        if (!memberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId, GroupStudyMemberStatus.JOINED)) {
            log.warn("[SCREEN-AI] access denied (not a JOINED member) userId={} groupId={}", userId, groupId);
            throw new ScreenAiException(HttpStatus.FORBIDDEN, "NOT_GROUP_MEMBER", "그룹스터디 참여 멤버만 화면 분석을 사용할 수 있습니다.");
        }
    }

    private String displayName(long userId) {
        return userRepository.findById(userId).map(User::getDisplayName).filter(n -> n != null && !n.isBlank()).orElse("참여자");
    }

    private ScreenAiException shareNotFound() {
        return new ScreenAiException(HttpStatus.NOT_FOUND, "SCREEN_NOT_FOUND", "화면공유가 종료되었거나 찾을 수 없습니다.");
    }

    private static ScreenAiException badRequest(String message) {
        return new ScreenAiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", message);
    }
}
