#!/usr/bin/env python3
"""
sanitize_text.py
텍스트에서 민감정보 후보를 탐지하고 마스킹한다.

주의: 완벽한 보안 도구가 아닌 '후보 탐지' 수준.
      contains_secret_candidate=true 샘플은 반드시 사람이 재검토해야 한다.

실행 예시:
  python app/scripts/sanitize_text.py --input text.txt --output sanitized.txt
"""
import argparse
import re
import sys
from pathlib import Path

# ── 민감정보 탐지 패턴 ──────────────────────────────────────────────
PATTERNS = [
    # API Keys
    (r'sk-[A-Za-z0-9]{48}', '[REDACTED_OPENAI_KEY]'),
    (r'tvly-[A-Za-z0-9_\-]+', '[REDACTED_TAVILY_KEY]'),
    (r'AKIA[0-9A-Z]{16}', '[REDACTED_AWS_ACCESS_KEY_ID]'),
    (r'hf_[A-Za-z0-9]{30,}', '[REDACTED_HF_TOKEN]'),
    (r'ghp_[A-Za-z0-9]{36}', '[REDACTED_GITHUB_TOKEN]'),

    # DB URLs
    (r'postgresql://[^\s"\'<>]+', '[REDACTED_DB_URL]'),
    (r'jdbc:postgresql://[^\s"\'<>]+', '[REDACTED_JDBC_URL]'),
    (r'jdbc:mysql://[^\s"\'<>]+', '[REDACTED_JDBC_URL]'),
    (r'mongodb://[^\s"\'<>]+', '[REDACTED_DB_URL]'),

    # 이메일
    (r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}', '[REDACTED_EMAIL]'),

    # 전화번호 (한국)
    (r'01[0-9][-\s]?\d{3,4}[-\s]?\d{4}', '[REDACTED_PHONE]'),
    (r'\d{3}[-\s]\d{3,4}[-\s]\d{4}', '[REDACTED_PHONE]'),

    # 비밀번호/시크릿 할당
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\'][^"\']{4,}["\']',
     r'\1 = "[REDACTED_PASSWORD]"'),
    (r'(?i)(secret|token)\s*[=:]\s*["\'][^"\']{8,}["\']',
     r'\1 = "[REDACTED_SECRET]"'),
    (r'(?i)(api[_\-]?key)\s*[=:]\s*["\'][A-Za-z0-9_\-]{16,}["\']',
     r'\1 = "[REDACTED_API_KEY]"'),

    # JWT / Bearer
    (r'Authorization:\s*Bearer\s+[A-Za-z0-9\-_\.]{20,}',
     'Authorization: Bearer [REDACTED_TOKEN]'),

    # Private key block
    (r'-----BEGIN[^\n]+PRIVATE KEY-----[\s\S]+?-----END[^\n]+PRIVATE KEY-----',
     '[REDACTED_PRIVATE_KEY_BLOCK]'),
]

def check_and_mask(text: str) -> tuple[str, bool, list[str]]:
    """
    텍스트에서 민감정보 후보를 탐지하고 마스킹한다.

    Returns:
        (마스킹된 텍스트, secret_found: bool, 탐지된 유형 목록)
    """
    masked = text
    found_types = []
    secret_found = False

    for pattern, replacement in PATTERNS:
        matches = re.findall(pattern, masked)
        if matches:
            secret_found = True
            found_types.append(pattern[:30])
            masked = re.sub(pattern, replacement if isinstance(replacement, str)
                           else replacement, masked)

    return masked, secret_found, found_types

def sanitize_file(input_path: str, output_path: str) -> dict:
    """파일 단위 민감정보 탐지 및 마스킹."""
    content = Path(input_path).read_text(encoding="utf-8", errors="ignore")
    masked, found, types = check_and_mask(content)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(masked, encoding="utf-8")

    return {
        "input": input_path,
        "output": output_path,
        "secret_found": found,
        "pattern_types": types,
        "original_length": len(content),
        "masked_length": len(masked),
    }

def main():
    parser = argparse.ArgumentParser(description="민감정보 탐지 및 마스킹")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = sanitize_file(args.input, args.output)
    print(f"[INFO] 민감정보 발견: {result['secret_found']}")
    if result["pattern_types"]:
        print(f"[WARN] 탐지 패턴: {result['pattern_types']}")
    print(f"[INFO] 저장 완료: {args.output}")

if __name__ == "__main__":
    main()
