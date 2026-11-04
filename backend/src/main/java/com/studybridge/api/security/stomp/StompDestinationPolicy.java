package com.studybridge.api.security.stomp;

import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * STOMP 목적지 허용 목록. 클라이언트가 SUBSCRIBE·SEND 할 수 있는 목적지는 아래 정규식에 정확히 맞는 것뿐이다.
 *
 * <ul>
 *   <li>simple broker 는 구독 목적지를 AntPathMatcher 패턴으로 해석한다. {@code /topic/group/*}{@code /chat} 같은
 *       와일드카드 구독을 허용하면 모든 그룹의 채팅·퀴즈를 받아 볼 수 있으므로 숫자 그룹 ID 와 고정 채널명만 허용한다.</li>
 *   <li>클라이언트가 {@code /topic/**} 로 직접 SEND 하면 컨트롤러를 거치지 않고 브로커가 그대로 방송한다
 *       (가짜 채팅·가짜 정답 공개·가짜 강퇴 이벤트). SEND 는 {@code /pub/group/{id}/...} 의 세 핸들러만 허용한다.</li>
 *   <li>그룹 ID 는 앞자리 0 을 허용하지 않는다({@code 05} 와 {@code 5} 가 같은 그룹으로 해석되는 별칭을 막는다).</li>
 * </ul>
 */
public final class StompDestinationPolicy {

    private static final Pattern SUBSCRIBE_DESTINATION = Pattern.compile(
            "^/topic/group/([1-9][0-9]{0,17})/"
                    + "(chat|members|quiz/(?:session|question|next|timer|submitted|reveal|scoreboard|end|error))$");

    private static final Pattern SEND_DESTINATION = Pattern.compile(
            "^/pub/group/([1-9][0-9]{0,17})/(chat|quiz/start|quiz/submit)$");

    private StompDestinationPolicy() {
    }

    /** 그룹 목적지. channel 은 {@code chat}, {@code members}, {@code quiz/start} 처럼 그룹 ID 뒤의 경로다. */
    public record GroupDestination(long groupId, String channel) {
    }

    public static Optional<GroupDestination> subscribable(String destination) {
        return match(SUBSCRIBE_DESTINATION, destination);
    }

    public static Optional<GroupDestination> sendable(String destination) {
        return match(SEND_DESTINATION, destination);
    }

    /** 그룹 토픽 접두어. 세션 차단 시 이 그룹을 구독한 세션을 찾는 데 쓴다. */
    public static String groupTopicPrefix(long groupId) {
        return "/topic/group/" + groupId + "/";
    }

    private static Optional<GroupDestination> match(Pattern pattern, String destination) {
        if (destination == null) {
            return Optional.empty();
        }
        Matcher matcher = pattern.matcher(destination);
        if (!matcher.matches()) {
            return Optional.empty();
        }
        return Optional.of(new GroupDestination(Long.parseLong(matcher.group(1)), matcher.group(2)));
    }
}
