package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.VideoConnectionMetadata.Kind;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 방별 화면공유 슬롯 판정(순수 함수 — OpenVidu REST 응답만 보고 판단한다).
 *
 * <p>슬롯의 원천(Source of Truth)은 OpenVidu 의 SCREEN Connection 자체다(Spring 만 발급 가능, OpenVidu Secret 은 서버 전용).
 * 별도 슬롯 저장소를 두지 않으므로 OpenVidu 상태와 어긋날 일이 없고, 브라우저 강제 종료·네트워크 단절은 OpenVidu 가 WebSocket ping 으로
 * Connection 을 없애는 순간 슬롯도 함께 사라진다(하트비트 = OpenVidu 연결 감시).</p>
 *
 * <ul>
 *   <li>ACTIVE  — 소유 PRIMARY 가 살아 있고 브라우저가 접속한 화면공유(슬롯 점유)</li>
 *   <li>PENDING — 발급 후 아직 접속 전인 토큰(시작 중 예약, pendingTtl 안에서만 점유)</li>
 *   <li>EXPIRED_PENDING — pendingTtl 이 지나도록 접속하지 않은 토큰(시작 실패·탭 종료 잔여 → 정리 대상)</li>
 *   <li>ORPHAN — 소유 PRIMARY 가 사라진 화면공유(새로고침·재입장·크래시 잔여 → 정리 대상)</li>
 * </ul>
 */
public final class ScreenSharePolicy {

    private ScreenSharePolicy() {}

    public enum SlotState { ACTIVE, PENDING, EXPIRED_PENDING, ORPHAN }

    public record ScreenSlot(String connectionId, Long userId, String ownerConnectionId, SlotState state,
                             long createdAt, long activeAt) {
        public boolean occupying() {
            return state == SlotState.ACTIVE || state == SlotState.PENDING;
        }
    }

    /** PRIMARY(카메라·마이크) Connection 이 SCREEN 타입 스트림을 게시한 경우 — 화면공유 승인(SCREEN 토큰)을 우회한 게시. */
    public record ScreenStreamOnPrimary(String connectionId, Long userId, String streamId) {}

    public record Snapshot(List<ScreenSlot> screens, Set<String> activePrimaryIds, List<ScreenStreamOnPrimary> screenStreamsOnPrimary) {

        public List<ScreenSlot> occupying() {
            return screens.stream().filter(ScreenSlot::occupying).toList();
        }

        /** 정리 대상(만료된 예약 + 소유자가 사라진 화면공유). */
        public List<ScreenSlot> stale() {
            return screens.stream().filter(s -> !s.occupying()).toList();
        }

        /**
         * 한도를 넘은 점유 슬롯(정상 승인 경로에서는 생기지 않는다 — 배포 이전 발급분·다중 인스턴스 이상 대비).
         * 먼저 시작해 이미 송출 중인 공유를 남기고(ACTIVE 의 activeAt 순 → PENDING 의 createdAt 순), 뒤에 들어온 것을 넘긴다.
         */
        public List<ScreenSlot> overLimit(int limit) {
            List<ScreenSlot> occ = new ArrayList<>(occupying());
            if (limit < 0 || occ.size() <= limit) return List.of();
            occ.sort(Comparator.comparing((ScreenSlot s) -> s.state() == SlotState.ACTIVE ? 0 : 1)
                    .thenComparingLong(s -> s.state() == SlotState.ACTIVE ? s.activeAt() : s.createdAt()));
            return List.copyOf(occ.subList(limit, occ.size()));
        }
    }

    /**
     * @param connections OpenVidu GET /sessions/{id}?pendingConnections=true 의 connections.content
     * @param now         현재 시각(ms)
     * @param pendingTtlMs 발급 후 이 시간 안에 접속하지 않은 SCREEN 토큰은 예약으로 보지 않는다
     */
    public static Snapshot inspect(ObjectMapper om, List<Map<String, Object>> connections, long now, long pendingTtlMs) {
        Set<String> activePrimary = new LinkedHashSet<>();
        for (Map<String, Object> c : connections) {
            if (!"active".equals(c.get("status")) || !(c.get("connectionId") instanceof String id)) continue;
            if (VideoConnectionMetadata.fromRest(om, c.get("serverData"), c.get("clientData")).kind() != Kind.SCREEN) {
                activePrimary.add(id);
            }
        }

        List<ScreenSlot> screens = new ArrayList<>();
        List<ScreenStreamOnPrimary> bypass = new ArrayList<>();
        for (Map<String, Object> c : connections) {
            if (!(c.get("connectionId") instanceof String id)) continue;
            VideoConnectionMetadata m = VideoConnectionMetadata.fromRest(om, c.get("serverData"), c.get("clientData"));
            boolean active = "active".equals(c.get("status"));
            if (m.kind() != Kind.SCREEN) {
                if (active) {
                    for (String streamId : screenStreamIds(c)) bypass.add(new ScreenStreamOnPrimary(id, m.userId(), streamId));
                }
                continue;
            }
            long createdAt = longOr(c.get("createdAt"), m.issuedAt() == null ? 0L : m.issuedAt());
            long activeAt = longOr(c.get("activeAt"), 0L);
            SlotState state;
            if (m.ownerConnectionId() == null || !activePrimary.contains(m.ownerConnectionId())) {
                state = SlotState.ORPHAN;
            } else if (active) {
                state = SlotState.ACTIVE;
            } else {
                state = createdAt > 0 && now - createdAt <= pendingTtlMs ? SlotState.PENDING : SlotState.EXPIRED_PENDING;
            }
            screens.add(new ScreenSlot(id, m.userId(), m.ownerConnectionId(), state, createdAt, activeAt));
        }
        return new Snapshot(List.copyOf(screens), Set.copyOf(activePrimary), List.copyOf(bypass));
    }

    private static List<String> screenStreamIds(Map<String, Object> connection) {
        List<String> ids = new ArrayList<>();
        if (!(connection.get("publishers") instanceof List<?> pubs)) return ids;
        for (Object p : pubs) {
            if (!(p instanceof Map<?, ?> pub) || !(pub.get("streamId") instanceof String sid)) continue;
            if (pub.get("mediaOptions") instanceof Map<?, ?> media && "SCREEN".equals(media.get("typeOfVideo"))) ids.add(sid);
        }
        return ids;
    }

    private static long longOr(Object v, long fallback) {
        return v instanceof Number n ? n.longValue() : fallback;
    }
}
