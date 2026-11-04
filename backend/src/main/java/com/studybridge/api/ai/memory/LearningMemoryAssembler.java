package com.studybridge.api.ai.memory;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.AiContractException;
import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.AiSigningKeys;
import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.LearningContextV1;
import com.studybridge.api.ai.contract.v1.LearningContextV1.ContextItem;
import com.studybridge.api.ai.contract.v1.LearningContextV1.Kind;
import com.studybridge.api.ai.contract.v1.LearningContextV1.Provenance;
import com.studybridge.api.ai.contract.v1.LearningContextV1.SourceType;
import com.studybridge.api.ai.contract.v1.LearningContextV1.TrustLevel;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.LearningEventOrigin;
import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialMemo;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.MaterialSummary;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import com.studybridge.api.repository.LearningLoopEventRepository;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.service.MaterialQuizScoreService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Learning Memory 조립기 — 사용자별 학습 기록을 learning-context.v1({@link LearningContextV1})로 묶어 학습메이트 추론 요청
 * (ChatService → ai07 /api/ai/multi-chat[/stream] 본문 {@code learningContext} + 헤더 {@code X-AI-Scope})에 싣는다. 기본 OFF
 * ({@code ai.learning-memory.enabled} / {@code AI_LEARNING_MEMORY_ENABLED}).
 *
 * <h2>추론 시 메모리 ≠ 가중치 학습</h2>
 * 이 클래스가 만드는 것은 <b>추론 시점(inference-time) 컨텍스트</b>다. 요청 한 번의 프롬프트 데이터로만 쓰이고 그 요청이 끝나면 사라진다.
 * QLoRA 등 모델 <b>가중치 학습과는 무관</b>하다 — 학습 후보는 동의·승인·서명을 거친 training-sample.v1 경로
 * ({@code ai/training/TrainingCandidateCollector} → outbox)로만 나가며, 여기서 조립한 컨텍스트를 학습 데이터로 저장·전송하지 않는다.
 *
 * <h2>신뢰 규칙(LearningContextV1.TrustLevel / SourceType 상한, effectiveTrust 를 넘게 주장하지 않는다)</h2>
 * <ul>
 *   <li>최근 대화(그 방, 최근 N건): 사용자 발화 = CHAT_MESSAGE/USER_ASSERTED(role user). AI 답변은 {@code quality_status=APPROVED} 만
 *       AI_ANSWER/AI_GENERATED(role assistant) — 미승인·레거시(null) AI 답변은 품질 게이트 ON/OFF 와 무관하게 다시 넣지 않는다.</li>
 *   <li>PDF 원문 발췌(요청 materialId 가 사용자 소유일 때만): PDF_ORIGINAL/SOURCE_PRIMARY + 페이지·청크·리비전 provenance.
 *       추출 텍스트에 페이지 경계({@code [Page N]} 표식 또는 form-feed)가 없으면 페이지를 추측하지 않고 발췌를 싣지 않는다.</li>
 *   <li>PDF 요약: {@code material_summaries.quality_status=APPROVED} 만 AI_SUMMARY/AI_GENERATED.</li>
 *   <li>반복 오답 개념: APPROVED 오답노트의 "다시 볼 개념"(AI 생성 라벨) 이름·횟수 → AI_ANSWER/AI_GENERATED.</li>
 *   <li>퀴즈 정답률: 숫자만(SYSTEM_RECORD). 문항·해설(AI 생성)은 싣지 않는다.</li>
 *   <li>일정: 사용자 할 일(todos, 직접 입력 = USER_PROVIDED_TEXT/USER_ASSERTED, 시스템 등록 = SYSTEM_RECORD)·오답노트 복습 예정일(SYSTEM_RECORD).</li>
 *   <li>사용자 직접 메모(material memo): USER_MEMO/USER_ASSERTED.</li>
 * </ul>
 * 다른 사용자의 방·자료·기록은 넣지 않는다(방 소유자·자료 소유자·userId 범위 조회). 예산: contextItems 합계
 * {@code max-total-chars}(기본 6000 코드포인트) + 항목별 상한, 그룹 우선순위로 자르며 잘린 항목은 본문 끝 표식과 provenance.notes
 * {@code truncated} 로 표시한다. 조립 결과가 계약 검증({@link LearningContextV1#validate})을 통과하지 못하면 보내지 않는다(null).
 * scope 서명 키(AI_SCOPE_SIGNING_KEY)나 가명 키(AI_PSEUDONYM_SECRET)가 없으면 컨텍스트를 보내지 않는다(fail-closed, 요청 자체는 진행).
 * 로그에는 개수·코드만 남기고 본문은 남기지 않는다.
 */
@Slf4j
@Component
public class LearningMemoryAssembler {

    static final String APPROVED = "APPROVED";
    static final String QS_SOURCE = "SOURCE";
    static final String QS_USER = "USER_DATA";
    static final String QS_SYSTEM = "SYSTEM_RECORD";
    static final String TRUNCATION_MARK = " …[이하 생략]";
    static final String NOTE_TRUNCATED = "truncated";
    static final int MIN_TRUNCATED_CHARS = 40;
    static final int MAX_PDF_SCAN_CHUNKS = 400;
    static final int SMALL_ITEM_CHARS = 200;
    static final int QUIZ_ITEMS = 5;
    static final int CONCEPT_ITEMS = 5;
    static final int SCHEDULE_ITEMS = 5;

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern PAGE_MARKER = Pattern.compile("(?m)^[ \\t]*\\[Page (\\d{1,6})\\][ \\t]*\\r?$");
    private static final Pattern NON_WORD = Pattern.compile("[^\\p{L}\\p{N}]+");
    private static final Pattern WS = Pattern.compile("\\s+");

    /** 예산 그룹 — 선언 순서 = 우선순위 = 본문 순서. share = 1차 배분 비율(%), 남는 예산은 2차에 우선순위대로 넘긴다. */
    enum Group {
        QUIZ(6), WRONG_CONCEPT(7), PDF(35), CHAT(25), MEMO(10), SCHEDULE(7), SUMMARY(10);

        final int share;

        Group(int share) {
            this.share = share;
        }
    }

    /** 조립 통계(로그·테스트용, 본문 없음). */
    public record Stats(int included, int truncated, int omitted, int totalChars, Map<String, Integer> byKind) { }

    /** ChatService 에 넘기는 결과: 요청 본문에 넣을 JSON + 업스트림 시도마다 새로 서명하는 X-AI-Scope 헤더 공급자. */
    public record Attachment(LearningContextV1 context, JsonNode body, Supplier<Map<String, String>> headers, Stats stats) { }

    private final LearningMemorySettings settings;
    private final AiSigningKeys signingKeys;
    private final PseudonymousUserKeys pseudonymousUserKeys;
    private final AgentChatRoomRepository roomRepository;
    private final ChatMessageRepository chatMessageRepository;
    private final MaterialRepository materialRepository;
    private final MaterialSummaryRepository summaryRepository;
    private final MaterialMemoRepository memoRepository;
    private final ReviewNoteRepository reviewNoteRepository;
    private final MaterialQuizRepository quizRepository;
    private final MaterialQuizScoreService quizScoreService;
    private final LearningLoopEventRepository eventRepository;
    private final TodoRepository todoRepository;
    private Clock clock = Clock.systemUTC();
    private ZoneId zone = ZoneId.systemDefault();

    public LearningMemoryAssembler(LearningMemorySettings settings, AiSigningKeys signingKeys,
                                   PseudonymousUserKeys pseudonymousUserKeys, AgentChatRoomRepository roomRepository,
                                   ChatMessageRepository chatMessageRepository, MaterialRepository materialRepository,
                                   MaterialSummaryRepository summaryRepository, MaterialMemoRepository memoRepository,
                                   ReviewNoteRepository reviewNoteRepository, MaterialQuizRepository quizRepository,
                                   MaterialQuizScoreService quizScoreService, LearningLoopEventRepository eventRepository,
                                   TodoRepository todoRepository) {
        this.settings = settings;
        this.signingKeys = signingKeys;
        this.pseudonymousUserKeys = pseudonymousUserKeys;
        this.roomRepository = roomRepository;
        this.chatMessageRepository = chatMessageRepository;
        this.materialRepository = materialRepository;
        this.summaryRepository = summaryRepository;
        this.memoRepository = memoRepository;
        this.reviewNoteRepository = reviewNoteRepository;
        this.quizRepository = quizRepository;
        this.quizScoreService = quizScoreService;
        this.eventRepository = eventRepository;
        this.todoRepository = todoRepository;
    }

    /** 테스트용 시계/시간대 주입. */
    void setClock(Clock clock, ZoneId zone) {
        this.clock = clock;
        this.zone = zone;
    }

    public boolean enabled() {
        return settings.enabled();
    }

    // ── 공개 API ─────────────────────────────────────────────────────────────────────

    /**
     * 플래그 ON + 키 구성 + 조립·검증 성공일 때만 첨부물을 돌려준다. 그 밖(OFF, 키 없음, 내용 없음, 검증 실패, 내부 오류)은 null —
     * 호출자는 요청 본문·헤더를 바꾸지 않고 그대로 진행한다.
     */
    public Attachment attach(Long userId, Long roomId, Long materialId, String requestId, String currentQuestion) {
        if (!settings.enabled() || userId == null || requestId == null) {
            return null;
        }
        if (!signingKeys.configured(AiSigningKeys.Purpose.SCOPE) || !signingKeys.configured(AiSigningKeys.Purpose.PSEUDONYM)) {
            log.warn("[LEARNING-MEMORY] requestId={} 서명/가명 키 미구성 — learningContext 미전송(fail-closed)", requestId);
            return null;
        }
        Assembled a = assembleInternal(userId, roomId, materialId, requestId, currentQuestion);
        if (a == null) {
            return null;
        }
        LearningContextV1 ctx = a.context();
        List<Long> materialIds = ctx.materialId() == null ? List.of() : List.of(ctx.materialId());
        List<String> documentIds = ctx.documentId() == null ? List.of() : List.of(ctx.documentId());
        String sub = ctx.pseudonymousUserKey();
        Supplier<Map<String, String>> headers = () -> Map.of(AiContractSigning.HEADER_SCOPE,
                scopeToken(sub, materialIds, documentIds, requestId));
        try {
            headers.get(); // 지금 서명할 수 없으면 보내지 않는다(fail-closed)
        } catch (RuntimeException e) {
            log.warn("[LEARNING-MEMORY] requestId={} scope 서명 실패 — learningContext 미전송: {}", requestId, code(e));
            return null;
        }
        JsonNode body = ContractJson.STRICT.valueToTree(ctx);
        Stats s = a.stats();
        log.info("[LEARNING-MEMORY] requestId={} roomId={} materialScoped={} items={} truncated={} omitted={} chars={} kinds={}",
                requestId, roomId, ctx.materialId() != null, s.included(), s.truncated(), s.omitted(), s.totalChars(), s.byKind());
        return new Attachment(ctx, body, headers, s);
    }

    /**
     * userId·roomId·(선택)materialId·requestId → 검증을 통과한 learning-context.v1, 실을 내용이 없거나 키·검증 실패면 null.
     * 플래그와 무관한 순수 조립(플래그 판단은 {@link #attach}).
     */
    public LearningContextV1 assemble(Long userId, Long roomId, Long materialId, String requestId, String currentQuestion) {
        Assembled a = assembleInternal(userId, roomId, materialId, requestId, currentQuestion);
        return a == null ? null : a.context();
    }

    // ── 조립 ────────────────────────────────────────────────────────────────────────

    record Assembled(LearningContextV1 context, Stats stats) { }

    /** 예산 배분 전 후보. rank = 그룹 안 우선순위(작을수록 먼저), order = 그룹 안 본문 순서. */
    static final class Candidate {
        final Group group;
        final int rank;
        long order;
        final String id;
        final Kind kind;
        final String role;
        String content;
        final SourceType sourceType;
        final String sourceId;
        final String revision;
        final Integer page;
        final String chunkId;
        final OffsetDateTime createdAt;
        final String qualityStatus;
        final String origin;
        final Double retrievalScore;
        final List<String> notes = new ArrayList<>();
        final TrustLevel trust;
        boolean truncated;

        Candidate(Group group, int rank, String id, Kind kind, String role, String content, SourceType sourceType, String sourceId,
                  String revision, Integer page, String chunkId, OffsetDateTime createdAt, String qualityStatus, String origin,
                  Double retrievalScore, TrustLevel trust) {
            this.group = group;
            this.rank = rank;
            this.order = rank;
            this.id = id;
            this.kind = kind;
            this.role = role;
            this.content = content;
            this.sourceType = sourceType;
            this.sourceId = sourceId;
            this.revision = revision;
            this.page = page;
            this.chunkId = chunkId;
            this.createdAt = createdAt;
            this.qualityStatus = qualityStatus;
            this.origin = origin;
            this.retrievalScore = retrievalScore;
            // 신뢰는 sourceType 상한을 넘지 않는다(처음부터 상한 이하로만 보낸다).
            TrustLevel cap = LearningContextV1.MAX_TRUST_BY_SOURCE.get(sourceType);
            this.trust = trust.ordinal() > cap.ordinal() ? cap : trust;
        }

        int len() {
            return ContractJson.len(content);
        }

        ContextItem toItem() {
            return new ContextItem(id, kind, role, content, sourceType, sourceId, revision, page, chunkId, createdAt, qualityStatus,
                    new Provenance(origin, null, retrievalScore, revision, List.copyOf(notes)), trust);
        }
    }

    private Assembled assembleInternal(Long userId, Long roomId, Long materialId, String requestId, String currentQuestion) {
        if (userId == null || requestId == null || !ContractJson.ID_1_128.matcher(requestId).matches()) {
            return null;
        }
        final String pseudo;
        try {
            pseudo = pseudonymousUserKeys.of(userId);
        } catch (AiContractException e) {
            log.warn("[LEARNING-MEMORY] requestId={} 가명 키 미구성 — learningContext 미전송: {}", requestId, e.code());
            return null;
        }
        try {
            Material owned = ownedMaterial(userId, materialId);
            if (materialId != null && owned == null) {
                log.warn("[LEARNING-MEMORY] requestId={} materialId 가 요청 사용자 소유가 아님 — 자료 범위 항목 제외", requestId);
            }
            List<Candidate> all = new ArrayList<>();
            all.addAll(safe("quiz", requestId, () -> quizCandidates(userId, owned)));
            List<ReviewNote> notes = safe("review-notes", requestId, () -> reviewNotes(userId, owned));
            all.addAll(safe("wrong-concept", requestId, () -> conceptCandidates(userId, notes)));
            all.addAll(safe("pdf", requestId, () -> pdfCandidates(owned, currentQuestion)));
            all.addAll(safe("chat", requestId, () -> chatCandidates(userId, roomId, requestId, currentQuestion)));
            all.addAll(safe("memo", requestId, () -> memoCandidates(owned)));
            all.addAll(safe("schedule", requestId, () -> scheduleCandidates(userId, notes)));
            all.addAll(safe("summary", requestId, () -> summaryCandidates(owned)));

            Budgeted b = budget(all, settings.maxTotalChars());
            if (b.kept().isEmpty()) {
                return null;
            }
            List<ContextItem> items = b.kept().stream().map(Candidate::toItem).toList();
            LearningContextV1 ctx = new LearningContextV1(LearningContextV1.SCHEMA_VERSION, requestId, pseudo,
                    owned != null ? owned.getMaterialId() : null, null, clean(clip(currentQuestion, 4000)), items, null, null);
            ContractJson.Violations v = LearningContextV1.validate(ctx);
            if (!v.ok()) {
                log.warn("[LEARNING-MEMORY] requestId={} 계약 검증 실패 — learningContext 미전송 violations={}", requestId, v.list());
                return null;
            }
            Map<String, Integer> byKind = new LinkedHashMap<>();
            for (ContextItem it : items) {
                byKind.merge(it.kind().name(), 1, Integer::sum);
            }
            int chars = items.stream().mapToInt(it -> ContractJson.len(it.content())).sum();
            int truncated = (int) b.kept().stream().filter(c -> c.truncated).count();
            return new Assembled(ctx, new Stats(items.size(), truncated, b.omitted(), chars, byKind));
        } catch (RuntimeException e) {
            log.warn("[LEARNING-MEMORY] requestId={} 조립 실패 — learningContext 미전송: {}", requestId, code(e));
            return null;
        }
    }

    private <T> List<T> safe(String what, String requestId, Supplier<List<T>> s) {
        try {
            List<T> out = s.get();
            return out == null ? List.of() : out;
        } catch (RuntimeException e) {
            log.warn("[LEARNING-MEMORY] requestId={} {} 수집 실패 — 생략: {}", requestId, what, code(e));
            return List.of();
        }
    }

    private Material ownedMaterial(Long userId, Long materialId) {
        if (materialId == null || materialId < 1) {
            return null;
        }
        return materialRepository.findById(materialId).filter(m -> userId.equals(m.getUserId())).orElse(null);
    }

    // ── 예산 ────────────────────────────────────────────────────────────────────────

    record Budgeted(List<Candidate> kept, int omitted) { }

    /**
     * 1차: 그룹마다 share% 상한 안에서 rank 순으로 온전히 들어가는 항목만(첫 초과에서 그 그룹은 멈춤).
     * 2차: 남은 전체 예산을 그룹 우선순위·rank 순으로 대기 항목에 준다(다 안 들어가면 표식을 붙여 자르고, 너무 짧으면 생략).
     * 결과는 그룹 순서 → 그룹 안 본문 순서(대화는 시간순).
     */
    static Budgeted budget(List<Candidate> all, int totalBudget) {
        List<Candidate> keep = new ArrayList<>();
        List<Candidate> pending = new ArrayList<>();
        int used = 0;
        for (Group g : Group.values()) {
            int cap = totalBudget * g.share / 100;
            int groupUsed = 0;
            boolean stopped = false;
            List<Candidate> inGroup = all.stream().filter(c -> c.group == g)
                    .sorted(Comparator.comparingInt((Candidate c) -> c.rank)).toList();
            for (Candidate c : inGroup) {
                if (!stopped && groupUsed + c.len() <= cap) {
                    keep.add(c);
                    groupUsed += c.len();
                } else {
                    stopped = true;
                    pending.add(c);
                }
            }
            used += groupUsed;
        }
        int left = totalBudget - used;
        int omitted = 0;
        for (Candidate c : pending) { // pending 은 이미 그룹 우선순위 → rank 순
            if (keep.size() >= LearningContextV1.MAX_CONTEXT_ITEMS) {
                omitted++;
                continue;
            }
            if (c.len() <= left) {
                keep.add(c);
                left -= c.len();
            } else if (left >= MIN_TRUNCATED_CHARS) {
                c.content = truncate(c.content, left);
                c.truncated = true;
                if (!c.notes.contains(NOTE_TRUNCATED)) {
                    c.notes.add(NOTE_TRUNCATED);
                }
                keep.add(c);
                left -= c.len();
            } else {
                omitted++;
            }
        }
        while (keep.size() > LearningContextV1.MAX_CONTEXT_ITEMS) {
            keep.remove(keep.size() - 1);
            omitted++;
        }
        keep.sort(Comparator.comparingInt((Candidate c) -> c.group.ordinal()).thenComparingLong(c -> c.order));
        return new Budgeted(keep, omitted);
    }

    /** 항목 상한 적용: 넘으면 표식 포함 max 코드포인트로 자르고 notes 에 truncated. */
    static Candidate capped(Candidate c, int max) {
        if (c.len() > max) {
            c.content = truncate(c.content, max);
            c.truncated = true;
            c.notes.add(NOTE_TRUNCATED);
        }
        return c;
    }

    static String truncate(String s, int max) {
        int markLen = ContractJson.len(TRUNCATION_MARK);
        return clip(s, Math.max(0, max - markLen)).stripTrailing() + TRUNCATION_MARK;
    }

    private int itemCap(int groupDefault) {
        return Math.min(settings.maxItemChars(), groupDefault);
    }

    // ── 1) 최근 대화 ────────────────────────────────────────────────────────────────

    private List<Candidate> chatCandidates(Long userId, Long roomId, String requestId, String currentQuestion) {
        if (roomId == null || settings.chatTurns() == 0) {
            return List.of();
        }
        Optional<AgentChatRoom> room = roomRepository.findById(roomId);
        if (room.isEmpty() || room.get().getUser() == null || !userId.equals(room.get().getUser().getId())) {
            return List.of(); // 다른 사용자의 방 — 대화 기록을 싣지 않는다
        }
        List<ChatMessage> rows = chatMessageRepository.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(roomId);
        List<Candidate> out = new ArrayList<>();
        boolean leading = true; // 아직 이전 턴을 하나도 만나지 않은 구간(이번 질문의 저장본·재시도 echo 가 놓이는 곳)
        int cap = itemCap(600);
        for (ChatMessage m : rows == null ? List.<ChatMessage>of() : rows) {
            if (out.size() >= settings.chatTurns()) {
                break;
            }
            if (m == null || m.getContent() == null || m.getContent().isBlank()) {
                continue;
            }
            if (requestId.equals(m.getRequestId())) {
                continue; // 이번 턴(방금 저장한 질문) 제외
            }
            boolean user = "USER".equalsIgnoreCase(m.getSender());
            if (leading && user && currentQuestion != null && currentQuestion.trim().equals(m.getContent().trim())) {
                continue; // 답 없이 끝난 같은 질문(다시 시도) echo 제외 — 이번 질문과 중복
            }
            leading = false;
            if (!user && !APPROVED.equals(m.getQualityStatus())) {
                continue; // 미승인·레거시 AI 답변은 다음 추론 맥락으로 넣지 않는다
            }
            int rank = out.size(); // 최신일수록 먼저 예산을 받는다
            Candidate c = new Candidate(Group.CHAT, rank, "chat:" + m.getId(), Kind.CHAT_TURN, user ? "user" : "assistant",
                    clean(m.getContent()), user ? SourceType.CHAT_MESSAGE : SourceType.AI_ANSWER, "chat_message:" + m.getId(),
                    null, null, null, at(m.getCreatedAt()), user ? QS_USER : APPROVED, "spring-db", null,
                    user ? TrustLevel.USER_ASSERTED : TrustLevel.AI_GENERATED);
            out.add(capped(c, cap));
        }
        // 본문은 시간순(오래된 → 최신)
        for (int i = 0; i < out.size(); i++) {
            out.get(i).order = out.size() - 1 - i;
        }
        return out;
    }

    // ── 2) PDF 원문 발췌 ─────────────────────────────────────────────────────────────

    record Page(int number, String body) { }

    record Chunk(int page, int index, String text) { }

    private List<Candidate> pdfCandidates(Material m, String question) {
        if (m == null || settings.pdfChunks() == 0 || m.getExtractedText() == null || m.getExtractedText().isBlank()) {
            return List.of();
        }
        String text = m.getExtractedText();
        List<Page> pages = pages(text);
        if (pages.isEmpty()) {
            log.info("[LEARNING-MEMORY] materialId={} 추출 텍스트에 페이지 경계 없음 — PDF 원문 발췌 생략(페이지 추측 금지)", m.getMaterialId());
            return List.of();
        }
        int cap = itemCap(1200);
        List<Chunk> chunks = new ArrayList<>();
        for (Page p : pages) {
            int idx = 0;
            for (String piece : split(p.body(), cap)) {
                if (chunks.size() >= MAX_PDF_SCAN_CHUNKS) {
                    break;
                }
                chunks.add(new Chunk(p.number(), idx++, piece));
            }
        }
        Set<String> tokens = tokens(question);
        record Scored(Chunk chunk, int hits) { }
        List<Scored> scored = new ArrayList<>();
        for (Chunk c : chunks) {
            scored.add(new Scored(c, hits(c.text(), tokens)));
        }
        scored.sort(Comparator.comparingInt((Scored s) -> -s.hits()).thenComparingInt(s -> s.chunk().page())
                .thenComparingInt(s -> s.chunk().index()));
        String revision = sha256(text);
        OffsetDateTime created = at(m.getUpdatedAt() != null ? m.getUpdatedAt() : m.getUploadedAt());
        List<Candidate> out = new ArrayList<>();
        for (Scored s : scored) {
            if (out.size() >= settings.pdfChunks()) {
                break;
            }
            Chunk c = s.chunk();
            Double score = tokens.isEmpty() ? null : Math.round(1000.0 * s.hits() / tokens.size()) / 1000.0;
            String chunkId = "m" + m.getMaterialId() + "-p" + c.page() + "-c" + c.index();
            Candidate cand = new Candidate(Group.PDF, out.size(), "pdf:" + chunkId, Kind.PDF_CHUNK, null, c.text(),
                    SourceType.PDF_ORIGINAL, "material:" + m.getMaterialId(), revision, c.page(), chunkId, created, QS_SOURCE,
                    "spring-db", score, TrustLevel.SOURCE_PRIMARY);
            cand.notes.add("selection=lexical");
            out.add(cand);
        }
        return out;
    }

    /** 페이지 경계: form-feed(\f, 추출기 페이지 구분) 우선, 없으면 줄 단독 "[Page N]" 표식(ai07 추출기 출력). 둘 다 없으면 빈 목록. */
    static List<Page> pages(String text) {
        List<Page> out = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return out;
        }
        if (text.indexOf('\f') >= 0) {
            String[] parts = text.split("\f", -1);
            for (int i = 0; i < parts.length && i < 100000; i++) {
                String body = stripPageMarker(parts[i]).strip();
                if (!body.isEmpty()) {
                    out.add(new Page(i + 1, body));
                }
            }
            return out;
        }
        Matcher mm = PAGE_MARKER.matcher(text);
        List<int[]> marks = new ArrayList<>(); // [pageNo, markerStart, bodyStart]
        while (mm.find()) {
            marks.add(new int[]{Integer.parseInt(mm.group(1)), mm.start(), mm.end()});
        }
        for (int i = 0; i < marks.size(); i++) {
            int page = marks.get(i)[0];
            int end = i + 1 < marks.size() ? marks.get(i + 1)[1] : text.length();
            String body = text.substring(marks.get(i)[2], end).strip();
            if (page >= 1 && page <= 100000 && !body.isEmpty()) {
                out.add(new Page(page, body));
            }
        }
        return out;
    }

    private static String stripPageMarker(String part) {
        Matcher mm = PAGE_MARKER.matcher(part);
        return mm.find() && part.substring(0, mm.start()).isBlank() ? part.substring(mm.end()) : part;
    }

    /** 코드포인트 기준 max 이하 조각(원문 부분 문자열 그대로 — 요약·의역하지 않는다). 가능하면 끝 80자 안의 공백에서 끊는다. */
    static List<String> split(String body, int max) {
        List<String> out = new ArrayList<>();
        int i = 0;
        while (i < body.length()) {
            int remaining = body.codePointCount(i, body.length());
            int end = remaining <= max ? body.length() : body.offsetByCodePoints(i, max);
            if (end < body.length()) {
                int floor = body.offsetByCodePoints(i, Math.max(1, max - 80));
                for (int k = end; k > floor; k--) {
                    if (Character.isWhitespace(body.charAt(k - 1))) {
                        end = k;
                        break;
                    }
                }
            }
            String piece = clean(body.substring(i, end)).strip();
            if (!piece.isEmpty()) {
                out.add(piece);
            }
            i = end;
        }
        return out;
    }

    static Set<String> tokens(String q) {
        Set<String> out = new LinkedHashSet<>();
        if (q == null) {
            return out;
        }
        for (String t : NON_WORD.split(q.toLowerCase(Locale.ROOT))) {
            if (t.codePointCount(0, t.length()) < 2) {
                continue;
            }
            out.add(t);
            // 한국어 조사("핸드셰이크가") 대응: 3자 이상 한글 토큰은 끝 한 글자를 뗀 형태도 본다.
            if (t.codePointCount(0, t.length()) >= 3 && Character.UnicodeScript.of(t.codePointBefore(t.length()))
                    == Character.UnicodeScript.HANGUL) {
                out.add(t.substring(0, t.offsetByCodePoints(t.length(), -1)));
            }
        }
        return out;
    }

    static int hits(String text, Set<String> tokens) {
        if (tokens.isEmpty()) {
            return 0;
        }
        String lower = text.toLowerCase(Locale.ROOT);
        int n = 0;
        for (String t : tokens) {
            if (lower.contains(t)) {
                n++;
            }
        }
        return n;
    }

    // ── 3) 승인된 PDF 요약 ───────────────────────────────────────────────────────────

    private List<Candidate> summaryCandidates(Material m) {
        if (m == null) {
            return List.of();
        }
        Optional<MaterialSummary> s = summaryRepository.findByMaterial_MaterialId(m.getMaterialId());
        if (s.isEmpty() || !APPROVED.equals(s.get().getQualityStatus())) {
            return List.of(); // 미승인·레거시 AI 요약은 싣지 않는다
        }
        MaterialSummary sum = s.get();
        StringBuilder b = new StringBuilder();
        if (sum.getOverview() != null && !sum.getOverview().isBlank()) {
            b.append("자료 요약: ").append(sum.getOverview().strip());
        }
        List<String> points = keyPoints(sum.getCoreContents());
        if (!points.isEmpty()) {
            b.append(b.length() > 0 ? "\n" : "").append("핵심: ").append(String.join("; ", points));
        }
        if (b.length() == 0) {
            return List.of();
        }
        Candidate c = new Candidate(Group.SUMMARY, 0, "summary:" + sum.getSummaryId(), Kind.SUMMARY, null, clean(b.toString()),
                SourceType.AI_SUMMARY, "material_summary:" + sum.getSummaryId(), null, null, null, at(sum.getCreatedAt()), APPROVED,
                "spring-db", null, TrustLevel.AI_GENERATED);
        return List.of(capped(c, itemCap(800)));
    }

    private static List<String> keyPoints(String coreContentsJson) {
        List<String> out = new ArrayList<>();
        if (coreContentsJson == null || coreContentsJson.isBlank()) {
            return out;
        }
        try {
            JsonNode n = JSON.readTree(coreContentsJson);
            JsonNode kp = n.isObject() ? n.path("key_points") : n;
            if (kp.isArray()) {
                for (JsonNode p : kp) {
                    if (p.isTextual() && !p.asText().isBlank() && out.size() < 8) {
                        out.add(p.asText().strip());
                    }
                }
            }
        } catch (Exception ignored) {
            // 형식이 다르면 핵심 목록 없이 개요만 싣는다
        }
        return out;
    }

    // ── 4) 사용자 메모 ──────────────────────────────────────────────────────────────

    private List<Candidate> memoCandidates(Material m) {
        if (m == null) {
            return List.of();
        }
        Optional<MaterialMemo> memo = memoRepository.findByMaterial_MaterialId(m.getMaterialId());
        if (memo.isEmpty() || memo.get().getContent() == null || memo.get().getContent().isBlank()) {
            return List.of();
        }
        MaterialMemo mm = memo.get();
        Candidate c = new Candidate(Group.MEMO, 0, "memo:" + mm.getMemoId(), Kind.USER_MEMO, null, clean(mm.getContent().strip()),
                SourceType.USER_MEMO, "material_memo:" + mm.getMemoId(), null, null, null,
                at(mm.getUpdatedAt() != null ? mm.getUpdatedAt() : mm.getCreatedAt()), QS_USER, "spring-db", null,
                TrustLevel.USER_ASSERTED);
        return List.of(capped(c, itemCap(800)));
    }

    // ── 5) 반복 오답 개념 ────────────────────────────────────────────────────────────

    private List<ReviewNote> reviewNotes(Long userId, Material owned) {
        List<ReviewNote> rows = owned != null
                ? reviewNoteRepository.findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(userId, owned.getMaterialId())
                : reviewNoteRepository.findTop20ByUserIdOrderByCreatedAtDesc(userId);
        return rows == null ? List.of() : rows.stream().filter(Objects::nonNull).filter(n -> userId.equals(n.getUserId())).toList();
    }

    private List<Candidate> conceptCandidates(Long userId, List<ReviewNote> notes) {
        final class Agg {
            String label;
            int count;
            final Set<Long> noteIds = new LinkedHashSet<>();
            Long latestNoteId;
            LocalDateTime latest;
        }
        Map<String, Agg> byConcept = new LinkedHashMap<>();
        for (ReviewNote n : notes) {
            if (!APPROVED.equals(n.getQualityStatus()) || n.getRetryJson() == null || n.getRetryJson().isBlank()) {
                continue; // 미승인 오답노트의 AI 개념 라벨은 싣지 않는다
            }
            JsonNode arr;
            try {
                arr = JSON.readTree(n.getRetryJson());
            } catch (Exception e) {
                continue;
            }
            if (!arr.isArray()) {
                continue;
            }
            for (JsonNode q : arr) {
                String concept = q.path("concept").isTextual() ? WS.matcher(q.path("concept").asText()).replaceAll(" ").strip() : "";
                if (concept.isEmpty()) {
                    continue;
                }
                concept = clip(concept, 100);
                Agg a = byConcept.computeIfAbsent(concept.toLowerCase(Locale.ROOT), k -> new Agg());
                if (a.label == null) {
                    a.label = concept;
                }
                a.count++;
                a.noteIds.add(n.getReviewNoteId());
                if (a.latest == null || (n.getCreatedAt() != null && n.getCreatedAt().isAfter(a.latest))) {
                    a.latest = n.getCreatedAt();
                    a.latestNoteId = n.getReviewNoteId();
                }
                if (a.latestNoteId == null) {
                    a.latestNoteId = n.getReviewNoteId();
                }
            }
        }
        List<Agg> sorted = new ArrayList<>(byConcept.values());
        sorted.sort(Comparator.comparingInt((Agg a) -> -a.count)
                .thenComparing(a -> a.latest, Comparator.nullsLast(Comparator.reverseOrder())));
        List<Candidate> out = new ArrayList<>();
        for (Agg a : sorted) {
            if (out.size() >= CONCEPT_ITEMS) {
                break;
            }
            String content = "반복 오답 개념: " + a.label + " — 틀리거나 못 푼 문항 " + a.count + "회(오답노트 " + a.noteIds.size() + "건)";
            Candidate c = new Candidate(Group.WRONG_CONCEPT, out.size(), "wrong-concept:" + (out.size() + 1), Kind.WRONG_NOTE, null,
                    clean(content), SourceType.AI_ANSWER, "review_note:" + a.latestNoteId, null, null, null, at(a.latest), APPROVED,
                    "spring-db", null, TrustLevel.AI_GENERATED);
            c.notes.add("count=" + a.count);
            c.notes.add("noteCount=" + a.noteIds.size());
            out.add(capped(c, itemCap(SMALL_ITEM_CHARS)));
        }
        return out;
    }

    // ── 6) 퀴즈 정답률 ──────────────────────────────────────────────────────────────

    private List<Candidate> quizCandidates(Long userId, Material owned) {
        List<Candidate> out = new ArrayList<>();
        if (owned != null) {
            List<MaterialQuiz> quizzes = quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(owned.getMaterialId());
            for (MaterialQuiz q : quizzes == null ? List.<MaterialQuiz>of() : quizzes) {
                if (out.size() >= QUIZ_ITEMS) {
                    break;
                }
                if (q == null || q.getQuizId() == null) {
                    continue;
                }
                MaterialQuizScoreService.StoredScore s = quizScoreService.find(q.getQuizId(), userId);
                if (s == null || s.getScore() == null || !userId.equals(s.getUserId() != null ? s.getUserId() : userId)) {
                    continue;
                }
                StringBuilder b = new StringBuilder("퀴즈 정답률(자료 퀴즈 #").append(q.getQuizId());
                if (q.getDifficulty() != null && !q.getDifficulty().isBlank()) {
                    b.append(", 난이도 ").append(clip(q.getDifficulty().strip(), 20));
                }
                b.append("): 최근 ");
                if (s.getCorrectCount() != null && s.getTotalQuestions() != null && s.getTotalQuestions() > 0) {
                    b.append(s.getCorrectCount()).append('/').append(s.getTotalQuestions()).append(" 정답, ");
                }
                b.append(s.getScore()).append("점");
                b.append(" · 최고 ").append(s.effectiveBestScore()).append("점");
                if (s.getAttempt() != null) {
                    b.append(" · 응시 ").append(s.getAttempt()).append("회");
                }
                Candidate c = new Candidate(Group.QUIZ, out.size(), "quiz:" + q.getQuizId(), Kind.QUIZ_RESULT, null, clean(b.toString()),
                        SourceType.SYSTEM_RECORD, "material_quiz:" + q.getQuizId(), null, null, null,
                        at(s.getSubmittedAt() != null ? s.getSubmittedAt() : q.getCreatedAt()), QS_SYSTEM, "spring-redis", null,
                        TrustLevel.SYSTEM_RECORD);
                c.notes.add("scoreSemantics=percent");
                out.add(capped(c, itemCap(SMALL_ITEM_CHARS)));
            }
            return out;
        }
        List<LearningLoopEvent> events = eventRepository.findByUserIdAndEventTypeOrderByCreatedAtDesc(userId,
                LearningEventType.QUIZ_SUBMITTED, PageRequest.of(0, QUIZ_ITEMS * 2));
        for (LearningLoopEvent e : events == null ? List.<LearningLoopEvent>of() : events) {
            if (out.size() >= QUIZ_ITEMS) {
                break;
            }
            // 클라이언트·레거시(origin null) 기록은 시스템 기록으로 승격하지 않는다.
            if (e == null || e.getOrigin() != LearningEventOrigin.SERVER || !userId.equals(e.getUserId()) || e.getScore() == null) {
                continue;
            }
            StringBuilder b = new StringBuilder("퀴즈 정답률");
            if (e.getQuizId() != null) {
                b.append("(퀴즈 #").append(e.getQuizId()).append(')');
            }
            b.append(": ").append(e.getScore()).append("점");
            if (e.getDifficulty() != null && !e.getDifficulty().isBlank()) {
                b.append(" · 난이도 ").append(clip(e.getDifficulty().strip(), 20));
            }
            Candidate c = new Candidate(Group.QUIZ, out.size(), "quiz-event:" + e.getId(), Kind.QUIZ_RESULT, null, clean(b.toString()),
                    SourceType.SYSTEM_RECORD, "learning_loop_event:" + e.getId(), null, null, null, at(e.getCreatedAt()), QS_SYSTEM,
                    "spring-db", null, TrustLevel.SYSTEM_RECORD);
            c.notes.add("scoreSemantics=percent");
            out.add(capped(c, itemCap(SMALL_ITEM_CHARS)));
        }
        return out;
    }

    // ── 7) 할 일·복습 예정일 ─────────────────────────────────────────────────────────

    private List<Candidate> scheduleCandidates(Long userId, List<ReviewNote> notes) {
        LocalDate today = LocalDate.now(clock.withZone(zone));
        List<Candidate> out = new ArrayList<>();
        Set<Long> reviewNotesWithTodo = new HashSet<>();
        List<Todo> todos = todoRepository.findTop20ByUserIdAndCompletedFalseAndEndDateGreaterThanEqualOrderByEndDateAsc(userId,
                today.atStartOfDay());
        for (Todo t : todos == null ? List.<Todo>of() : todos) {
            if (out.size() >= SCHEDULE_ITEMS) {
                break;
            }
            if (t == null || t.getText() == null || t.getText().isBlank()
                    || (t.getUser() != null && t.getUser().getId() != null && !userId.equals(t.getUser().getId()))) {
                continue;
            }
            boolean manual = t.getSourceType() == null || t.getSourceType().isBlank();
            if ("REVIEW_NOTE".equals(t.getSourceType()) && t.getSourceId() != null) {
                reviewNotesWithTodo.add(t.getSourceId());
            }
            LocalDate due = t.getScheduleDate() != null ? t.getScheduleDate()
                    : t.getEndDate() != null ? t.getEndDate().toLocalDate() : null;
            String label = manual ? "할 일" : "REVIEW_NOTE".equals(t.getSourceType()) ? "복습 일정" : "학습 일정";
            String content = label + ": " + WS.matcher(t.getText()).replaceAll(" ").strip() + (due != null ? " (" + due + ")" : "");
            Candidate c = new Candidate(Group.SCHEDULE, out.size(), "todo:" + t.getId(), Kind.PLANNER_REVIEW, null, clean(content),
                    manual ? SourceType.USER_PROVIDED_TEXT : SourceType.SYSTEM_RECORD, "todo:" + t.getId(), null, null, null,
                    at(t.getCreatedAt()), manual ? QS_USER : QS_SYSTEM, "spring-db", null,
                    manual ? TrustLevel.USER_ASSERTED : TrustLevel.SYSTEM_RECORD);
            c.notes.add("dateKind=" + (manual ? "due" : "scheduled"));
            out.add(capped(c, itemCap(SMALL_ITEM_CHARS)));
        }
        List<ReviewNote> due = notes.stream()
                .filter(n -> n.getRecommendedReviewDate() != null && !n.getRecommendedReviewDate().isBefore(today.minusDays(1)))
                .filter(n -> !reviewNotesWithTodo.contains(n.getReviewNoteId()))
                .sorted(Comparator.comparing(ReviewNote::getRecommendedReviewDate))
                .toList();
        for (ReviewNote n : due) {
            if (out.size() >= SCHEDULE_ITEMS) {
                break;
            }
            // 제목(자료명+"오답노트")·문항 수·난이도·추천일은 Spring 이 결정적으로 만든 기록(AI 본문 아님).
            String content = "복습 예정: " + clip(WS.matcher(Objects.toString(n.getTitle(), "오답노트")).replaceAll(" ").strip(), 80)
                    + " " + n.getRecommendedReviewDate()
                    + " (오답 " + nz(n.getWrongCount()) + " · 미응답 " + nz(n.getUnansweredCount())
                    + (n.getDifficulty() != null ? ", 난이도 " + clip(n.getDifficulty().strip(), 20) : "") + ")";
            Candidate c = new Candidate(Group.SCHEDULE, out.size(), "review-schedule:" + n.getReviewNoteId(), Kind.PLANNER_REVIEW, null,
                    clean(content), SourceType.SYSTEM_RECORD, "review_note:" + n.getReviewNoteId(), null, null, null,
                    at(n.getCreatedAt()), QS_SYSTEM, "spring-db", null, TrustLevel.SYSTEM_RECORD);
            c.notes.add("dateKind=review");
            out.add(capped(c, itemCap(SMALL_ITEM_CHARS)));
        }
        return out;
    }

    // ── scope 서명 ──────────────────────────────────────────────────────────────────

    private String scopeToken(String sub, List<Long> materialIds, List<String> documentIds, String requestId) {
        return AiContractSigning.issueScopeToken(signingKeys.key(AiSigningKeys.Purpose.SCOPE), sub, materialIds, documentIds,
                requestId, clock.instant().getEpochSecond(), settings.scopeTtlSeconds());
    }

    // ── 공용 ────────────────────────────────────────────────────────────────────────

    private OffsetDateTime at(LocalDateTime t) {
        LocalDateTime v = t != null ? t : LocalDateTime.now(clock.withZone(zone));
        return v.atZone(zone).toOffsetDateTime().truncatedTo(ChronoUnit.SECONDS);
    }

    static String clip(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.codePointCount(0, s.length()) <= max ? s : s.substring(0, s.offsetByCodePoints(0, max));
    }

    /** 계약 JSON 이 표현할 수 없는 문자(고립 서러게이트, NUL 등 제어문자 — 개행·탭 제외)를 뺀다. */
    static String clean(String s) {
        if (s == null) {
            return null;
        }
        StringBuilder b = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (Character.isHighSurrogate(c)) {
                if (i + 1 < s.length() && Character.isLowSurrogate(s.charAt(i + 1))) {
                    b.append(c).append(s.charAt(++i));
                }
                continue;
            }
            if (Character.isLowSurrogate(c)) {
                continue;
            }
            if (c < 0x20 && c != '\n' && c != '\t') {
                b.append(c == '\r' ? "" : " ");
                continue;
            }
            b.append(c);
        }
        return b.toString();
    }

    private static int nz(Integer v) {
        return v == null ? 0 : v;
    }

    static String sha256(String s) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String code(Throwable e) {
        return e instanceof AiContractException ce ? ce.code() : e.getClass().getSimpleName();
    }
}
