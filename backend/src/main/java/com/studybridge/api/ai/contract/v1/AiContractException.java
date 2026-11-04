package com.studybridge.api.ai.contract.v1;

/**
 * EC2↔ai07 내부 계약 오류. code 는 ai07 {@code app.contracts.signing.SignatureError.code} 와 같은 어휘를 쓴다.
 * 이 예외가 나면 사용자 자료를 ai07 로 보내거나 검색하지 않는다(fail-closed).
 */
public class AiContractException extends RuntimeException {

    private final String code;

    public AiContractException(String code) {
        super(code);
        this.code = code;
    }

    public AiContractException(String code, String detail) {
        super(code + ": " + detail);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
