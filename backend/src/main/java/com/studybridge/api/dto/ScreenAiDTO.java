package com.studybridge.api.dto;

/**
 * 그룹스터디 화면공유 AI 분석 API 요청 본문. 응답은 계약 필드가 명시된 Map(JSON) — GroupScreenAiService 참고.
 */
public class ScreenAiDTO {

    private ScreenAiDTO() {}

    /**
     * POST /api/groups/{id}/screen-ai/analyze 본문. 사용자 식별자(질문자·공유자)는 받지 않는다(JWT·OpenVidu serverData 로 서버가 결정).
     *
     * @param connectionId    분석할 화면공유(SCREEN) Connection id
     * @param streamId        그 Connection 이 지금 게시 중인 SCREEN 스트림 id(공유를 다시 시작했으면 바뀐다)
     * @param question        질문 1~1000자
     * @param image           현재 프레임 1장 JPEG Base64(data:image/jpeg;base64, 접두사 허용)
     * @param mime            image/jpeg
     * @param clientRequestId 브라우저가 만든 요청 id(취소용, [A-Za-z0-9_-]{8,64}). 없으면 취소 불가.
     */
    public record AnalyzeRequest(String connectionId, String streamId, String question, String image, String mime,
                                 String clientRequestId) {
        /** 로그·예외 메시지로 이미지·질문 원문이 새지 않게 길이만 남긴다. */
        @Override
        public String toString() {
            return "AnalyzeRequest[connectionId=" + connectionId + ", streamId=" + streamId
                    + ", questionChars=" + (question == null ? 0 : question.length())
                    + ", imageChars=" + (image == null ? 0 : image.length())
                    + ", mime=" + mime + ", clientRequestId=" + clientRequestId + "]";
        }
    }

    /** PUT /api/groups/{id}/screen-ai/shares/{connectionId}/consent 본문. */
    public record ConsentRequest(Boolean allowed) {}
}
