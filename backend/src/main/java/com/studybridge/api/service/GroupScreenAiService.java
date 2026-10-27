package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ScreenAiDTO.AnalyzeRequest;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.VideoConnectionMetadata.Kind;
import com.studybridge.api.service.VisionUpstreamClient.VisionCall;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;

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

        AiRequestGuard.Lock lock = guard.tryLock(AiRequestGuard.lockKey(FEATURE, userId, "inflight"), upstream.timeout().plusSeconds(30));
        if (!lock.acquired()) {
            throw new ScreenAiException(HttpStatus.TOO_MANY_REQUESTS, "SCREEN_AI_IN_PROGRESS",
                    "이전 화면 분석이 아직 진행 중입니다. 끝난 뒤 다시 질문해 주세요.", true, 3);
        }
        Share share;
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
        } catch (RuntimeException e) {
            guard.release(lock);
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

        Mono<Map<String, Object>> call$ = upstream.analyze(call).map(r -> {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("requestId", requestId);
            body.put("clientRequestId", clientRequestId);
            body.put("answer", r.answer());
            body.put("model", r.model());
            body.put("connectionId", share.connectionId());
            body.put("streamId", share.streamId());
            Map<String, Object> sharer = new LinkedHashMap<>();
            sharer.put("userId", share.sharerUserId());
            sharer.put("name", displayName(share.sharerUserId()));
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
            return body;
        });
        // 취소 신호가 먼저 오면 firstWithSignal 이 ai07 호출을 구독 해제한다 → WebClient 연결 종료 → ai07 추론 취소.
        Mono<Map<String, Object>> cancelled$ = cancel.asMono().flatMap(x -> Mono.error(new ScreenAiException(
                HttpStatus.CONFLICT, "SCREEN_AI_CANCELLED", "화면 분석을 취소했습니다.")));
        return Mono.firstWithSignal(call$, cancelled$)
                .doOnSuccess(b -> outcome.set("OK"))
                .doOnError(e -> outcome.set(e instanceof ScreenAiException se ? se.getCode() : e.getClass().getSimpleName()))
                .doFinally(sig -> {
                    guard.release(lock);
                    if (cancelKey != null) inflight.remove(cancelKey, cancel);
                    log.info("[SCREEN-AI] analyze end requestId={} groupId={} askerId={} outcome={} signal={} latencyMs={}",
                            requestId, groupId, userId, outcome.get(), sig, clock.millis() - startedAt);
                });
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
