package com.studybridge.api.ai.quality;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * GATED 경로의 "실제로 게이트가 걸려 있다" 는 증거 테스트 표식(허위 GATED 라벨 방지, Phase D2).
 * value = "METHOD pattern"(AiQualityGateCoverage.ROUTES 와 같은 문자열). 붙이는 테스트는 최소한 다음을 실제 실행으로 보여야 한다:
 *  · 게이트 ON + 거절(또는 평가 불가) 평가기 → 응답·저장소·캐시 어디에도 AI 초안 본문이 없다(성공 위장 없음)
 *  · 게이트 ON + 승인 평가기 → 평가기가 실제로 호출되고 승인 본문만 노출·저장된다
 * AiQualityGateCoverageTest 가 모든 GATED 경로에 이 표식이 하나 이상 있는지, 표식이 GATED 가 아닌 경로를 가리키지 않는지 검사한다.
 */
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
public @interface GateEvidence {
    String[] value();
}
