"""
Qwen2.5 vLLM 서버 호출 서비스.
vLLM이 제공하는 OpenAI-compatible API 엔드포인트를 사용한다.
"""
from openai import OpenAI, APIConnectionError, APIStatusError
from app.core.config import QWEN_BASE_URL, QWEN_MODEL_NAME, QWEN_API_KEY

# OpenAI SDK 클라이언트를 모듈 로드 시 한 번만 생성 (재사용)
_client = OpenAI(
    base_url=QWEN_BASE_URL,
    api_key=QWEN_API_KEY,
)


def ask_qwen(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """
    Qwen2.5 모델에 질문을 보내고 답변 텍스트를 반환한다.

    Args:
        system_prompt: 시스템 역할 지시 (에이전트 성격, 답변 형식 등)
        user_prompt:   사용자 질문 및 수집된 자료 컨텍스트
        temperature:   샘플링 온도 (기본값 0.3)
        max_tokens:    최대 출력 토큰 수 (기본값 1024)

    Returns:
        Qwen2.5가 생성한 답변 문자열.
        연결 실패 시 오류 메시지 문자열을 반환한다 (예외를 상위로 전파하지 않음).
    """
    try:
        response = _client.chat.completions.create(
            model=QWEN_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    except APIConnectionError:
        # vLLM 서버가 꺼져 있거나 주소가 틀린 경우
        return (
            f"Qwen2.5 서버에 연결할 수 없습니다. "
            f"vLLM 서버({QWEN_BASE_URL})가 실행 중인지 확인하세요."
        )
    except APIStatusError as e:
        return f"Qwen2.5 API 오류 (HTTP {e.status_code}): {e.message}"
    except Exception as e:
        return f"Qwen2.5 호출 중 예기치 못한 오류가 발생했습니다: {e}"
