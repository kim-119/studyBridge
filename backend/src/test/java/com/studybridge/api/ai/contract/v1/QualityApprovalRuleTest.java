package com.studybridge.api.ai.contract.v1;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.ai.contract.v1.ResponseQualityV1.Output;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.QualityStatus;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.Severity;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.TaskType;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.Violation;
import java.util.List;
import org.junit.jupiter.api.Test;

/** 사용자 노출 승인 규칙(유일 판정 함수 isDisplayable)의 경계값. 80점은 rubric 점수이지 정답 확률이 아니다. */
class QualityApprovalRuleTest {

        static final String RID = "req-approval-0001";

        static Output out(Double score, boolean hardFail, QualityStatus st, List<Violation> v, Boolean success, Boolean verified,
                        Boolean mandatory, String rid) {
                return new Output("response-quality.v1", rid, TaskType.PDF_SUMMARY, success, verified, st, score, 80, hardFail, v,
                                List.of(), null, "rqg-1.0.0", null, 3, mandatory);
        }

        static Output approved(Double score) {
                return out(score, false, QualityStatus.APPROVED, List.of(), true, true, null, RID);
        }

        @Test
        void boundaryScores() {
                assertFalse(ResponseQualityV1.isDisplayable(approved(79.0), RID), "79 거절");
                assertFalse(ResponseQualityV1.isDisplayable(approved(79.999), RID), "79.999 거절");
                assertTrue(ResponseQualityV1.isDisplayable(approved(80.0), RID), "80 승인");
                assertTrue(ResponseQualityV1.isDisplayable(approved(100.0), RID), "100 승인");
                assertFalse(ResponseQualityV1.isDisplayable(approved(100.5), RID), "100 초과 거절");
                assertFalse(ResponseQualityV1.isDisplayable(approved(null), RID), "null 거절");
                assertFalse(ResponseQualityV1.isDisplayable(approved(Double.NaN), RID), "NaN 거절");
                assertFalse(ResponseQualityV1.isDisplayable(approved(Double.POSITIVE_INFINITY), RID), "Inf 거절");
        }

        @Test
        void hardFailAndValidatorsOverrideHighScore() {
                assertFalse(ResponseQualityV1.isDisplayable(out(95.0, true, QualityStatus.APPROVED, List.of(), true, true, null, RID), RID));
                assertFalse(ResponseQualityV1.isDisplayable(out(95.0, false, QualityStatus.APPROVED,
                                List.of(new Violation("SOURCE_CONTRADICTION", Severity.HARD, "근거와 모순", null)), true, true, null, RID), RID));
                assertFalse(ResponseQualityV1.isDisplayable(out(95.0, false, QualityStatus.APPROVED, List.of(), true, true, false, RID), RID));
                assertTrue(ResponseQualityV1.isDisplayable(out(95.0, false, QualityStatus.APPROVED,
                                List.of(new Violation("STYLE", Severity.MINOR, "문체", null)), true, true, true, RID), RID));
        }

        @Test
        void evaluationFailuresAreNeverDisplayable() {
                assertFalse(ResponseQualityV1.isDisplayable(null, RID), "평가 결과 없음(timeout/503)");
                assertFalse(ResponseQualityV1.isDisplayable(out(90.0, false, QualityStatus.APPROVED, List.of(), false, true, null, RID), RID),
                                "success=false");
                assertFalse(ResponseQualityV1.isDisplayable(out(90.0, false, QualityStatus.APPROVED, List.of(), true, false, null, RID), RID),
                                "verified=false");
                assertFalse(ResponseQualityV1.isDisplayable(out(90.0, false, QualityStatus.VALIDATION_ERROR, List.of(), true, true, null, RID),
                                RID), "VALIDATION_ERROR");
                assertFalse(ResponseQualityV1.isDisplayable(out(90.0, false, QualityStatus.REJECTED, List.of(), true, true, null, RID), RID));
                assertFalse(ResponseQualityV1.isDisplayable(approved(90.0), "req-other-00001"), "다른 요청의 판정 재사용 금지");
                assertFalse(ResponseQualityV1.isDisplayable(approved(90.0), null));
        }
}
