# Human Review Report

## 전체 통계
- 전체 샘플 수: 325
- 검수 완료 수: 254
- 검수 완료율: 78.15%
- auto_generated: 0
- needs_review: 71
- reviewed: 53
- approved: 0
- rejected: 50
- unsafe: 0
- duplicate: 151

## source_type별 통계
- : 325

## 위험 샘플 목록
- 없음

## 추가 검토 필요 샘플
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID
- NO_ID

## 샘플별 검수 메모
| id | source_type | quality_status | reviewed_by | review_notes |
|---|---|---|---|---|
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | needs_review | dohyun | PDF 근거 기반 설명은 적절하지만, 외부 자료 보완 항목에서 “Wikipedia 검색 결과를 참고하세요”처럼 사용자에게 확인을 떠넘기는 표현이 포함되어 있음. 외부 자료를 사용할 경우 실제 확인된 내용을 직접 요약해야 하며, PDF 근거와 외부 보완 지식을 명확히 구분해야 함. 민감정보 없음, 코드/PDF 근거 구조는 유지 가능. |
| NO_ID |  | needs_review | dohyun | 답변의 기술 내용은 충분하지만, 성격/말투가 “비판적 분석형”으로 충분히 드러나지 않음. 현재 답변은 일반적인 코드 리뷰 조언에 가깝고, 문제점의 심각도·운영 리스크·장애 가능성·우선순위 판단이 부족함. 비판적 분석형이라면 block() 사용의 구조적 문제, 타임아웃 부재 시 장애 전파, FastAPI 지연 시 Spring 스레드 점유, 예외 처리와 fallback 부재를 더 날카롭게 지적해야 함. 민감정보 없음, 근거와 코드/PDF 일치성은 유지 가능. |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | needs_review | dohyun | 사용자 추가 요구사항에 “어려운 말 없이 비유로 설명해줘”가 명시되어 있으나, 실제 답변에는 비유가 거의 포함되지 않음. 또한 성격/말투가 “창의적 확장형”인데도 개념을 새로운 이미지나 생활 비유로 확장하지 못하고 일반 설명형으로만 답변함. 입문 수준 답변인데 “마이크로서비스 아키텍처” 같은 어려운 용어가 갑자기 등장하여 지식수준에도 맞지 않음. Spring Boot와 일반 Java의 차이를 밀키트, 자동 주방, 조립식 책상 같은 쉬운 비유로 다시 설명해야 함. 민감정보 없음, 일반 지식 기반 답변으로 수정 가능. |
| NO_ID |  | duplicate | dohyun | 내용 겹침 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있으나, 해당 유형은 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복되므로 AI 에이전트 학습 데이터로 사용하지 않는 것이 적절함. 또한 사용자 질문은 “Spring Boot가 무엇이고 일반 Java와 무엇이 다른가”인데, 답변은 @SpringBootApplication의 스캔 범위를 묻는 문제로 바뀌어 질문 의도와 불일치함. 사용자 추가 요구사항인 “어려운 말 없이 비유로 설명”도 반영되지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | needs_review | dohyun | 답변의 기술 내용은 충분하지만, 성격/말투가 “비판적 분석형”으로 충분히 드러나지 않음 |
| NO_ID |  | needs_review | dohyun | 전체 방향은 맞지만 사용자 추가 요구사항인 “핵심 개념과 예시 위주”가 충분히 반영되지 않음 |
| NO_ID |  | needs_review | dohyun | 전체 방향은 맞지만 사용자 추가 요구사항인 “핵심 개념과 예시 위주”가 충분히 반영되지 않음 |
| NO_ID |  | needs_review | dohyun | 전체 방향은 맞지만 사용자 추가 요구사항인 “핵심 개념과 예시 위주”가 충분히 반영되지 않음 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있어 현재 AI 에이전트 학습 방향과 맞지 않으며, 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복됨. 또한 사용자 질문은 “@Autowired 주입과 생성자 주입의 차이를 설명해달라”는 설명 요청인데, assistant 답변은 객관식 문제 형식으로 전환되어 질문 의도와 불일치함. |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | needs_review | dohyun | 답변이 비판적 분석형처럼 시작은 했지만 실제 내용이 매우 부족함 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | duplicate | dohyun | 겹침 |
| NO_ID |  | duplicate | dohyun | 겹침 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있으나, 해당 유형은 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복되므로 AI 에이전트 학습 데이터로 사용하지 않는 것이 적절함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이  톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이  톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있어 현재 AI 에이전트 학습 방향과 맞지 않으며, 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복됨 |
| NO_ID |  | needs_review | dohyun | 답변의 방향은 맞지만 “전문가 수준”과 “실서비스 운영 관점” 요구에 비해 내용이 너무 요약적임 |
| NO_ID |  | needs_review | dohyun | 답변의 방향은 맞지만 “전문가 수준”과 “실서비스 운영 관점” 요구에 비해 내용이 너무 요약적임 |
| NO_ID |  | needs_review | dohyun | 답변의 방향은 맞지만 “전문가 수준”과 “실서비스 운영 관점” 요구에 비해 내용이 너무 요약적임 |
| NO_ID |  | needs_review | dohyun | 답변이 창의적 확장형으로 설정되어 있으나 실제로는 커넥션 풀 고갈 증상, 진단 지표, 원인 유형을 단순 나열하는 수준에 머무름. |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있어 현재 AI 에이전트 학습 방향과 맞지 않으며, 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복됨 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | needs_review | dohyun | 답변이 프로세스와 스레드의 핵심 차이를 충분히 설명하지 못함. 사용자 추가 요구사항에 “어려운 말 없이 비유로 설명해줘”가 명시되어 있으나 실제 답변에는 생활 비유가 포함되지 않음. 또한 성격/말투가 “비판적 분석형”이지만, 팀 기준의 츤데레 코치형처럼 헷갈리기 쉬운 지점을 살짝 지적하고 바로잡아주는 느낌이 부족함 |
| NO_ID |  | needs_review | dohyun | 질문 의 취지 랑 다름 |
| NO_ID |  | duplicate | dohyun | 중복 |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있어 현재 AI 에이전트 학습 방향과 맞지 않으며, 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복됨 |
| NO_ID |  | needs_review | dohyun | 답변의 기본 개념 설명은 맞지만, 사용자 추가 요구사항인 “핵심 개념과 예시 위주로 설명”이 충분히 반영되지 않음 |
| NO_ID |  | needs_review | dohyun | 답변의 기본 개념 설명은 맞지만, 사용자 추가 요구사항인 “핵심 개념과 예시 위주로 설명”이 충분히 반영되지 않음 |
| NO_ID |  | needs_review | dohyun | 답변의 기본 개념 설명은 맞지만, 사용자 추가 요구사항인 “핵심 개념과 예시 위주로 설명”이 충분히 반영되지 않음 |
| NO_ID |  | needs_review | dohyun | 답변의 기본 개념 설명은 맞지만, 사용자 추가 요구사항인 “핵심 개념과 예시 위주로 설명”이 충분히 반영되지 않음 그리고 또한 톤 이 반영 안됨 |
| NO_ID |  | needs_review | dohyun | 답변의 기본 개념 설명은 맞지만, 사용자 추가 요구사항인 “핵심 개념과 예시 위주로 설명”이 충분히 반영되지 않음 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있어 현재 AI 에이전트 학습 방향과 맞지 않으며, 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복됨 |
| NO_ID |  | needs_review | dohyun | 답변이 가상 메모리와 페이지 교체 알고리즘의 기본 개념은 일부 설명했지만, 사용자 추가 요구사항인 “장단점과 실무 적용 관점”이 충분히 반영되지 않음. |
| NO_ID |  | needs_review | dohyun | 답변의 기술 내용은 충분하지만, 성격/말투가 “비판적 분석형”으로 충분히 드러나지 않음. |
| NO_ID |  | needs_review | dohyun | 질문이 요구한 비교 분석의 핀트에서 일부 벗어남 |
| NO_ID |  | duplicate | dohyun | 중복 |
| NO_ID |  | needs_review | dohyun | 답변이 간결 요약형 형식은 일부 반영했지만, 지식수준이 “석사 수준”인 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있으나, 해당 유형은 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복되므로 AI 에이전트 학습 데이터로 사용하지 않는 것이 적절함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | needs_review | dohyun | 답변이 친절한 설명형 톤은 일부 반영했지만, 지식수준이 “박사 수준”으로 설정된 것에 비해 내용 깊이가 부족함 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”으로 설정되어 있어 현재 AI 에이전트 학습 방향과 맞지 않으며, 자료보관함의 문제 출제/퀴즈 생성 기능과 역할이 중복됨. |
| NO_ID |  | reviewed | dohyun | 통과 |
| NO_ID |  | needs_review | dohyun | 답변의 기술 내용은 충분하지만, 성격/말투가 “비판적 분석형”으로 충분히 드러나지 않음 |
| NO_ID |  | needs_review | dohyun | 답변이 Linux 프로덕션 서버의 CPU 병목, 메모리 부족, I/O 대기 진단 도구를 일부 제시했지만, 전문가 수준과 실서비스 운영 관점에 비해 내용이 명령어 나열에 가까움 |
| NO_ID |  | needs_review | dohyun | 답변이 요구사항을 충분히 반영하지 못함. 핵심 설명은 있으나 예시, 실무 관점, 지식수준 반영이 부족함. |
| NO_ID |  | needs_review | dohyun | 수정 필요: 간결 요약형 형식은 맞지만 전문가 수준의 실서비스 진단 기준이 부족함. CPU 병목, 메모리 부족, I/O 대기를 구분하는 지표 해석과 장애 대응 순서가 더 필요함. 민감정보 없음 |
| NO_ID |  | rejected | dohyun | 학습 제외: 성격/말투가 “문제 출제형”이라 자료보관함의 퀴즈 생성 기능과 역할이 중복됨. 또한 사용자는 실서비스 진단 방법을 설명해달라고 했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 입문 수준에 맞게 설명했고, 책의 찾아보기 비유를 사용해 인덱스 개념을 쉽게 설명함 |
| NO_ID |  | needs_review | dohyun | 책의 찾아보기 비유는 들어갔지만 비판적 분석형의 츤데레 코치 느낌이 부족함. “무작정 인덱스를 쓰면 쓰기 성능이 느려질 수 있다”는 점을 더 자연스럽게 지적하고, 입문자에게 맞게 예시를 조금 더 보완해야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 인덱스 설명 데이터와 내용이 거의 동일한 중복/유사중복 데이터임 |
| NO_ID |  | needs_review | dohyun | 수정 필요: 창의적 확장형인데 실제 창의적 비유나 확장 설명이 부족함. “분산 데이터베이스 시스템”, “새로운 접근법” 같은 문장은 형식적이며, 입문자에게는 오히려 어렵고 불필요함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 검수 통과: 간결 요약형에 맞게 핵심만 짧게 정리했고, 입문 수준에 맞는 책 찾아보기 비유도 포함됨. 장점과 단점이 함께 있어 학습 데이터로 사용 가능함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 학습 제외: 성격/말투가 “문제 출제형”이라 자료보관함의 퀴즈 생성 기능과 역할이 중복됨. 또한 사용자는 실서비스 진단 방법을 설명해달라고 했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | JOIN 종류별 기본 설명은 맞지만, 사용자 요구사항인 “예시를 들어주세요”가 충분히 반영되지 않음. 실제 테이블 예시나 SQL 예시가 없어 학사 수준 전공 튜터 답변으로는 설명력이 부족함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 비판적 분석형 톤이 자연스럽지 않고, 질문에서 요구한 JOIN별 예시가 부족함. INNER, LEFT, RIGHT, FULL OUTER 각각의 사용 상황과 SQL 예시가 필요하며, 현재는 LEFT JOIN 예시만 일부 제시되어 설명이 불완전함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | JOIN 종류별 기본 설명은 있지만 사용자 요구사항인 “예시 위주”가 부족함. LEFT JOIN 예시만 있고 INNER, RIGHT, FULL OUTER 각각의 SQL 예시가 없어 설명이 불완전함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 창의적 확장형인데 창의적 설명이 부족하고, “분산 데이터베이스 시스템” 문장은 형식적임. FULL OUTER JOIN 설명이 빠졌고, JOIN별 SQL 예시도 부족함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | JOIN 4종류의 기본 설명은 있지만, 사용자 요구사항인 “각각 언제 쓰는지 예시”가 부족함. LEFT JOIN 예시만 있고 INNER, RIGHT, FULL OUTER JOIN의 예시와 SQL 예시가 없음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함의 퀴즈 생성 기능과 중복됨. 또한 사용자는 JOIN 종류별 설명과 예시를 요청했는데, 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | MVCC 기본 개념은 설명했지만 석사 수준에 비해 깊이가 부족함. Tuple version, xmin/xmax, snapshot, vacuum, dead tuple, bloat 같은 PostgreSQL MVCC 핵심 구조가 빠졌고, 격리 수준별 데이터 일관성 차이와 실무 장단점도 부족함. “읽기 쿼리가 쓰기 쿼리를 절대 차단하지 않는다”는 표현도 너무 단정적임. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 비판적 분석형의 츤데레 코치 느낌이 부족하고, 석사 수준에 비해 MVCC 구조 설명이 얕음. xmin/xmax, snapshot, dead tuple, VACUUM, 격리 수준별 일관성 차이와 실무 장단점 설명이 더 필요함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 논리적 탐구형 구조는 있으나 석사 수준에 비해 MVCC 설명이 얕음. xmin/xmax, snapshot, dead tuple, VACUUM, 격리 수준별 일관성 차이와 실무 장단점이 부족함. “읽기 쿼리가 쓰기 쿼리를 절대 차단하지 않는다”는 표현도 과하게 단정적임. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 창의적 확장형인데 실제 창의적 비유나 확장 설명이 부족함. “분산 데이터베이스 시스템”, “새로운 접근법” 문장이 형식적이며, 석사 수준에 필요한 xmin/xmax, snapshot, VACUUM, 격리 수준별 일관성 차이와 실무 장단점 설명이 부족함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 간결 요약형 형식은 맞지만 석사 수준에 비해 MVCC 구조 설명이 얕음. xmin/xmax, snapshot, dead tuple, VACUUM, 격리 수준별 일관성 차이와 실무 장단점이 부족함. “읽기 쿼리가 쓰기 쿼리를 절대 차단하지 않는다”는 표현도 과하게 단정적임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함의 퀴즈 생성 기능과 중복됨. 사용자는 MVCC와 격리 수준의 영향 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기본 개념은 맞지만 박사 수준 답변으로는 깊이가 부족함. 쿼리 플래너의 탐색 방식, join order 선택, cost model, selectivity/cardinality 추정, pg_statistic의 MCV·histogram·correlation 역할, 통계 오류가 실행 계획에 미치는 구조적 영향 분석이 더 필요함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 비판적 분석형의 츤데레 코치 느낌이 부족하고, 박사 수준에 비해 분석 깊이가 얕음. 비용 기반 최적화, join order 탐색, cardinality/selectivity 추정, pg_statistic의 MCV·histogram·correlation 역할과 통계 오류가 실행 계획에 미치는 구조적 영향 설명이 부족함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 논리적 탐구형 구조는 있으나 박사 수준에 비해 분석 깊이가 부족함. 비용 기반 최적화, join order 탐색, cardinality/selectivity 추정, pg_statistic의 MCV·histogram·correlation 역할과 통계 오류의 구조적 영향 설명이 더 필요함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 쿼리 플래너/pg_statistic 설명 데이터와 내용이 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 실제 창의적 확장도 부족하고, 핵심 문장과 설명 흐름이 반복됨. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 간결 요약형 형식은 맞지만 박사 수준의 이론적·구조적 분석이 부족함. 비용 모델, join order 탐색, cardinality/selectivity 추정, pg_statistic의 MCV·histogram·correlation 역할 설명이 더 필요함. 기존 데이터와 유사성이 높아 중복 여부도 확인 필요. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함의 퀴즈 생성 기능과 중복됨. 또한 기존 PostgreSQL 쿼리 플래너/pg_statistic 검수 데이터와 주제·핵심 문장이 거의 동일한 중복 데이터임. 사용자는 분석을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와도 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 주제는 기존 PostgreSQL 성능 데이터와 일부 겹치지만 완전 중복은 아님. 느린 쿼리 식별, 인덱스, 파티셔닝은 언급했으나 전문가 수준의 실서비스 절차가 부족하고, 질문에 포함된 커넥션 풀 튜닝 설명이 빠짐. pg_stat_statements, EXPLAIN, 인덱스 전략, 파티셔닝, 커넥션 풀 설정을 장애 대응 순서로 더 구체화해야 함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 직전 PostgreSQL 느린 쿼리/인덱스/파티셔닝/커넥션 풀 튜닝 데이터와 질문 주제와 핵심 내용이 거의 동일한 유사중복 데이터임. 또한 비판적 분석형의 츤데레 코치 느낌이 약하고, 실서비스 개선 절차도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 PostgreSQL 느린 쿼리/인덱스/파티셔닝/커넥션 풀 튜닝 데이터와 질문 주제·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 구조는 있으나 실서비스 절차도 깊지 않음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | PostgreSQL 느린 쿼리/인덱스/파티셔닝/커넥션 풀 튜닝 데이터와 주제·핵심 문장이 거의 동일한 중복 데이터임. 창의적 확장형도 제대로 반영되지 않았고, 파티셔닝·커넥션 풀 튜닝 설명도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 PostgreSQL 느린 쿼리/인덱스/파티셔닝/커넥션 풀 튜닝 데이터와 주제·핵심 문장·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형이지만 커넥션 풀 튜닝 설명도 빠져 있음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 PostgreSQL 느린 쿼리/인덱스/파티셔닝/커넥션 풀 튜닝 데이터와 주제·핵심 내용이 거의 동일한 중복 데이터임. 사용자는 실전 방법 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 열과 링크드 리스트 차이를 입문 수준에 맞게 비유로 설명했고, 접근·삽입·삭제 차이도 간단히 정리됨. 기존 데이터와 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 존 배열/링크드 리스트 설명 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 또한 비판적 분석형의 츤데레 코치 느낌이 부족하고, “신중한 판단” 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 배열/링크드 리스트 설명 데이터와 질문·핵심 내용·비유·설명 구조가 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 배열/링크드 리스트 설명 데이터와 질문·핵심 내용·비유가 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “병렬 알고리즘 및 GPU 가속” 문장은 입문 수준에 맞지 않고 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 배열/링크드 리스트 설명 데이터와 질문·핵심 내용·비유·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 배열/링크드 리스트 설명 데이터와 주제·핵심 내용이 동일한 중복 데이터이며, 사용자는 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 데이터와 주제가 달라 중복은 아님. 이진 탐색의 핵심 개념과 O(log n) 설명은 맞지만, 사용자 요구사항인 “예시 위주”가 부족함. 정렬된 배열에서 mid 값을 비교하며 범위를 줄이는 실제 숫자 예시가 필요함. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 이진 탐색 데이터와 주제는 같지만, 순차 탐색 비교 예시가 추가되어 완전 중복은 아님. 다만 비판적 분석형의 츤데레 코치 느낌이 약하고, 실제 배열 예시로 mid 값을 비교하며 범위를 줄이는 과정이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 이진 탐색 데이터와 질문·핵심 내용·시간복잡도 설명·순차 탐색 비교 예시가 거의 동일한 중복 데이터임. 또한 사용자 요구사항인 “예시 위주”에 비해 실제 배열 탐색 과정 예시가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 이진 탐색 데이터와 질문·핵심 내용·시간복잡도 설명·1000만 개 데이터 비교 예시가 거의 동일한 중복 데이터임. 또한 창의적 확장형으로 설정되어 있지만 “병렬 알고리즘 및 GPU 가속” 문장은 형식적이고 입문/학사 수준 설명 흐름과도 맞지 않음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 이진 탐색 데이터와 질문·핵심 내용·시간복잡도 설명·순차 탐색 비교 예시가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮고, 실제 숫자 배열 예시도 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 이진 탐색 데이터와 질문·핵심 내용·시간복잡도 설명이 동일한 중복 데이터이며, 사용자는 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 데이터와 주제가 달라 중복은 아님. 다익스트라와 벨만-포드의 핵심 차이는 맞지만, 석사 수준에 비해 예시와 실무 적용 관점이 부족함. 음수 가중치에서 왜 다익스트라가 깨지는지 간단한 그래프 예시와, 실제 사용 기준을 보완해야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 다익스트라/벨만-포드 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. 또한 비판적 분석형의 츤데레 코치 느낌이 부족하고, 음수 가중치에서 다익스트라가 왜 깨지는지 구체 예시도 없음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 다익스트라/벨만-포드 데이터와 질문 주제·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 형식만 입혔을 뿐 새 학습 가치가 낮고, 음수 가중치에서 다익스트라가 실패하는 구체 예시도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 다익스트라/벨만-포드 데이터와 질문 주제·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형도 형식적이며, 음수 가중치 실패 예시와 실무 비교 관점이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 다익스트라/벨만-포드 데이터와 질문 주제·핵심 내용·시간복잡도·음수 가중치 한계 설명이 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮고, 실무 적용 관점도 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 다익스트라/벨만-포드 데이터와 질문 주제·핵심 내용이 동일한 중복 데이터이며, 사용자는 비교 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 존 데이터와 주제가 달라 중복은 아님. NP-완전 기본 정의는 있으나 박사 수준의 이론적·구조적 분석이 부족함. P/NP/NP-hard/NP-complete 구분, 다항시간 환원, 결정문제와 최적화문제 차이, 근사비율·PTAS/FPTAS·근사 불가능성까지 보완해야 함. 또한 TSP·Knapsack은 결정문제 기준으로 NP-완전이라 표현을 정밀하게 고쳐야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 NP-완전/근사 알고리즘 데이터와 질문·핵심 내용·예시가 거의 동일한 중복 데이터임. 또한 비판적 분석형의 츤데레 코치 느낌이 약하고, 박사 수준에 필요한 NP-hard/NP-complete 구분, 다항시간 환원, 근사비율, PTAS/FPTAS, 근사 불가능성 설명도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 NP-완전/근사 알고리즘 데이터와 질문·핵심 내용·예시·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 형식만 입혔을 뿐 새 학습 가치가 낮고, 박사 수준에 필요한 NP-hard/NP-complete 구분, 다항시간 환원, 결정문제/최적화문제 구분, PTAS/FPTAS, 근사 불가능성 설명도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 NP-완전/근사 알고리즘 데이터와 질문·핵심 내용·예시가 거의 동일한 중복 데이터임. 창의적 확장형도 형식적이고, 박사 수준에 필요한 NP-hard/NP-complete 구분, 다항시간 환원, 결정문제/최적화문제 구분, PTAS/FPTAS, 근사 불가능성 설명이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 NP-완전/근사 알고리즘 데이터와 질문·핵심 내용·예시·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 박사 수준에 필요한 NP-hard/NP-complete 구분, 다항시간 환원, 결정문제/최적화문제 구분, PTAS/FPTAS, 근사 불가능성 설명이 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 NP-완전/근사 알고리즘 데이터와 질문 주제·핵심 내용이 동일한 중복 데이터이며, 사용자는 이론적 분석을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 데이터와 주제가 달라 중복은 아님. 링 버퍼, Skip List, HashMap/TreeMap 사례는 좋지만 전문가 수준의 실서비스 관점으로는 부족함. latency와 throughput을 구분한 분석, lock-free queue, backpressure, GC 압박, 캐시 미스, 배치 처리, Redis/Kafka/거래 시스템 같은 실제 운영 사례를 더 구체화해야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 직전 대용량 실시간 데이터 처리/자료구조/latency/throughput 데이터와 질문 주제와 핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형의 츤데레 코치 느낌도 약하고, 전문가 수준에 필요한 throughput 분석, lock-free queue, backpressure, GC, 캐시 미스, 실제 운영 사례가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 대용량 실시간 데이터 처리/자료구조/latency/throughput 데이터와 질문 주제·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. Off-heap/Chronicle Map 내용이 추가되었지만 새 학습 가치가 충분하지 않음. 또한 전문가 수준에 비해 backpressure, GC 압박, 캐시 미스, lock-free 구조, 처리량 병목 분석이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 대용량 실시간 데이터 처리/자료구조/latency/throughput 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형도 형식적이며, “병렬 알고리즘 및 GPU 가속” 문장이 실제 답변 확장으로 기능하지 못함. 전문가 수준에 필요한 backpressure, GC, 캐시 미스, lock-free 구조, 처리량 병목 분석도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 대용량 실시간 데이터 처리/자료구조/latency/throughput 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮고, 전문가 수준에 필요한 backpressure, GC 압박, lock-free 구조, 캐시 미스, 처리량 병목 분석이 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 대용량 실시간 데이터 처리/자료구조/latency/throughput 데이터와 질문 주제·핵심 내용이 동일한 중복 데이터이며, 사용자는 실무 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | RAG 개념을 입문 수준에 맞게 쉽게 설명했고, “도서관에서 책을 찾아보고 답하는 사람” 비유도 적절함. PDF를 참고하는 이유도 정확히 연결됨. 기존 데이터와 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 설명 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. 또한 비판적 분석형의 츤데레 코치 느낌이 약하고, “신중한 판단” 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 설명 데이터와 질문·핵심 내용·도서관 비유·StudyBridge PDF 검색 설명이 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입혔을 뿐 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 설명 데이터와 질문·핵심 내용·도서관 비유가 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “멀티모달 AI와의 통합”이 실제로 확장 설명되지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 설명 데이터와 질문·핵심 내용·도서관 비유·StudyBridge PDF 검색 설명이 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음 |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 RAG 설명 데이터와 질문 주제·핵심 내용이 동일한 중복 데이터이며, 사용자는 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | Self-Attention을 수식 없이 개념 중심으로 설명했고, “은행” 예시로 문맥 판단 과정을 보여줘 사용자 요구사항도 충족함. 학사 수준에 맞게 Query/Key/Value와 Multi-Head Attention까지 간단히 포함됨. 기존 데이터와 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Self-Attention 설명 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. RNN 대비 병렬 처리 내용이 추가되었지만 새 학습 가치가 크지 않음. 또한 비판적 분석형의 츤데레 코치 느낌이 약하고 “신중한 판단” 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Self-Attention 설명 데이터와 질문·핵심 내용·은행 예시·Multi-Head Attention 설명이 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입혔을 뿐 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 기존 Self-Attention 설명 데이터와 질문·핵심 내용·은행 예시가 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “멀티모달 AI와의 통합”이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Self-Attention 설명 데이터와 질문·핵심 내용·은행 예시·Multi-Head Attention 설명이 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 또한 기존 Self-Attention 설명 데이터와 질문 주제·핵심 내용이 동일한 중복 데이터이며, 사용자는 개념 설명을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 RAG 기본 설명 데이터와는 주제가 달라 중복은 아님. 다만 석사 수준 분석치고는 검색 품질 평가 기준이 부족함. chunk size/overlap 설명은 괜찮지만 recall·precision·reranking·hybrid search·한국어 임베딩 모델 선택·PDF 구조 기반 분할 같은 실무 요소를 보완해야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 청크 분할/임베딩 모델 선택 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. Recall@K, MRR, Reranker 내용이 추가되었지만 답변이 짧고, 비판적 분석형의 츤데레 코치 느낌도 약함. “신중한 판단” 문장도 형식적으로 붙어 있어 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 청크 분할/임베딩 모델 선택 데이터와 질문 주제·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 구조는 있으나 새 학습 가치가 낮고, 석사 수준에 필요한 reranking, hybrid search, precision/recall 비교, PDF 구조 기반 분할, 실제 운영 튜닝 사례가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 청크 분할/임베딩 모델 선택 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “멀티모달 AI와의 통합”이 실제 확장 분석으로 이어지지 않아 형식적임. 석사 수준에 필요한 hybrid search, reranking, Recall@K/MRR, PDF 구조 기반 청킹, 임베딩 모델 비교 기준도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 청크 분할/임베딩 모델 선택 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮고, 석사 수준에 필요한 hybrid search, Recall@K/MRR, PDF 구조 기반 청킹, 임베딩 모델 비교 기준 설명이 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 기존 RAG 청크 분할/임베딩 모델 선택 데이터와 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 분석을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 RAG 데이터와 일부 겹치지만, LLM 할루시네이션·RAG·RLHF·Constitutional AI 비교 주제라 완전 중복은 아님. 다만 박사 수준에 비해 분석이 얕고 Constitutional AI 설명이 빠져 있음. RAG/RLHF/Constitutional AI의 효과와 한계를 비교 구조로 정리하고, 데이터 분포·불확실성 추정·검색 실패·보상모델 한계까지 보완해야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 LLM 할루시네이션/RAG/RLHF/Constitutional AI 비교 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형의 츤데레 코치 느낌이 약하고, 박사 수준에 필요한 Constitutional AI 설명, RAG/RLHF/Constitutional AI 비교 구조, 검색 실패·보상모델 한계·불확실성 추정 분석이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 LLM 할루시네이션/RAG/RLHF/Constitutional AI 비교 데이터와 질문 주제·핵심 내용이 거의 동일한 중복 데이터임. Constitutional AI가 추가되긴 했지만 한 줄 수준이라 새 학습 가치가 낮고, 박사 수준에 필요한 RAG/RLHF/Constitutional AI 비교표, 검색 실패, 보상모델 한계, 불확실성 추정 분석이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 LLM 할루시네이션/RAG/RLHF/Constitutional AI 비교 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “멀티모달 AI와의 통합”이 실제 확장 분석으로 이어지지 않아 형식적임. 박사 수준에 필요한 Constitutional AI 설명, RLHF 한계, 기법별 비교 구조도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 LLM 할루시네이션/RAG/RLHF/Constitutional AI 비교 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 Constitutional AI 설명이 빠져 있고, 박사 수준에 필요한 기법별 효과·한계 비교가 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 기존 LLM 할루시네이션/RAG/RLHF/Constitutional AI 비교 데이터와 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 비교 분석을 요청했는데 답변이 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 RAG 기본 설명/청크 전략 데이터와 일부 겹치지만, 프로덕션 운영 모니터링·지연·비용 최적화 주제라 완전 중복은 아님. 다만 전문가 수준 치고는 P95/P99 latency, Recall@K/MRR/NDCG, hallucination rate, cache hit rate, token cost per request, tracing, alert 기준, reranker 비용 최적화, top-k/ef_search 튜닝 같은 실전 지표가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 프로덕션 RAG 모니터링/지연/비용 최적화 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. 캐시와 SLA 내용은 추가됐지만 새 학습 가치가 크지 않음. 비판적 분석형의 츤데레 코치 느낌도 약하고, P95/P99, Recall@K/MRR, token cost/request, tracing, alert 기준 같은 전문가급 지표가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 프로덕션 RAG 모니터링/지연/비용 최적화 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 형식만 입혔을 뿐 새 학습 가치가 낮고, 전문가 수준에 필요한 P95/P99, Recall@K/MRR, token cost/request, tracing, alert 기준이 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 프로덕션 RAG 모니터링/지연/비용 최적화 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형도 “멀티모달 AI와의 통합” 문장이 형식적으로 붙은 수준이라 새 학습 가치가 낮음. 전문가 수준에 필요한 P95/P99, Recall@K/MRR, token cost/request, tracing, alert 기준도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 프로덕션 RAG 모니터링/지연/비용 최적화 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮고, 전문가 수준에 필요한 P95/P99, Recall@K/MRR, token cost/request, tracing, alert 기준이 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 기존 프로덕션 RAG 모니터링/지연/비용 최적화 데이터와 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 실전 방법 설명을 요청했는데 객관식 문제로 바뀌었고, 마지막 답안 문장도 잘려 있어 데이터 품질이 낮음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | React 컴포넌트를 입문 수준에 맞게 “레고 블록” 비유로 쉽게 설명했고, 재사용성·JSX·함수 컴포넌트 개념도 적절히 포함됨. 기존 질문/답변과 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 컴포넌트 설명 데이터와 질문·핵심 내용·레고 블록 비유가 거의 동일한 유사중복 데이터임. props 설명이 추가됐지만 새 학습 가치가 크지 않음. 비판적 분석형의 츤데레 코치 느낌도 약하고 “신중한 판단” 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 컴포넌트 설명 데이터와 질문·핵심 내용·레고 블록 비유가 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입혔을 뿐 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 컴포넌트 설명 데이터와 질문·핵심 내용·레고 블록 비유가 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “서버 컴포넌트 및 Edge 런타임”이 입문 수준에 맞게 설명되지 않고 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 컴포넌트 설명 데이터와 질문·핵심 내용·레고 블록 비유가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 기존 React 컴포넌트 설명 데이터와 질문 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 개념 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 React 컴포넌트 데이터와 관련 분야는 같지만, useState/useEffect 훅 주제라 완전 중복은 아님. 다만 “예시와 함께 설명” 요구에 비해 실제 예시 코드가 부족하고, useState는 상태 관리, useEffect는 렌더링 이후 부수 효과 처리라는 차이를 더 명확히 보여줘야 함. useEffect의 API 호출·타이머·cleanup 예시를 보완하면 좋음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 useState/useEffect 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형의 츤데레 코치 느낌도 약하고, “신중한 판단” 문장이 형식적으로 붙어 있음. 또한 예시와 함께 설명해달라는 요구에 비해 실제 코드 예시가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | useState/useEffect 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 형식만 입혔을 뿐 새 학습 가치가 낮고, 예시와 함께 설명해달라는 요구에 비해 실제 코드 예시가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | useState/useEffect 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형으로 설정되어 있지만 “서버 컴포넌트 및 Edge 런타임”이 실제 확장 설명으로 이어지지 않아 형식적임. 또한 예시와 함께 설명해달라는 요구에 비해 실제 코드 예시가 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 useState/useEffect 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮고, 예시와 함께 설명해달라는 요구에 비해 실제 코드 예시가 부족함. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 성격/말투가 “문제 출제형”이라 자료보관함 퀴즈 생성 기능과 중복됨. 기존 useState/useEffect 데이터와 질문 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 사용법과 차이를 예시로 설명해달라고 했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 React 컴포넌트/useState 데이터와 분야는 같지만 전역 상태 관리 비교 주제라 중복은 아님. 다만 석사 수준 실무 비교치고는 깊이가 부족함. Context API/Redux/Zustand의 상태 규모, 리렌더링 성능, DevTools, 미들웨어, Redux Toolkit, 서버 상태와 클라이언트 상태 구분, 실제 사용 사례를 더 명확히 비교해야 함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Context API/Redux/Zustand 비교 데이터와 질문 주제·핵심 내용이 거의 동일한 유사중복 데이터임. 답변 자체는 큰 오류는 없지만, 비판적 분석형의 츤데레 코치 느낌이 약하고 형식 문장이 반복됨. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Context API/Redux/Zustand 비교 데이터와 질문 주제·핵심 내용이 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입혔을 뿐 새 학습 가치가 낮음. 답변 자체는 큰 오류는 없지만 중복성이 높음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Context API/Redux/Zustand 비교 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형으로 설정됐지만 “서버 컴포넌트 및 Edge 런타임” 문장이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Context API/Redux/Zustand 비교 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 기존 Context API/Redux/Zustand 비교 데이터와 질문 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 비교 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 기존 React 컴포넌트/useState/전역 상태 관리 데이터와는 주제가 달라 중복 아님. 가상 DOM, Diffing, key 기반 최적화, Concurrent 렌더링, startTransition까지 핵심 개념을 포함해 질문 의도를 대체로 충족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 가상 DOM/Concurrent Mode 데이터와 질문 주제가 동일한 중복 데이터임. 비판적 분석형 느낌도 약하고, React 18 Concurrent Mode 설명이 거의 빠져 있어 질문 의도 충족도 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 가상 DOM/Concurrent Mode 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 논리적 탐구형 구조는 맞지만 새 학습 가치가 낮음. 답변 자체는 큰 오류 없음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 React 가상 DOM/Concurrent Mode 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형이지만 “서버 컴포넌트 및 Edge 런타임”이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 학습 제외: 기존 React 가상 DOM/Concurrent Mode 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞고 답변 자체도 큰 오류는 없지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 기존 React 가상 DOM/Concurrent Mode 데이터와 주제·핵심 내용도 동일한 중복 데이터임. 사용자는 이론적 분석을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 기존 React 데이터와 분야는 같지만, SPA 성능 튜닝 주제라 중복은 아님. 핵심 항목은 들어갔지만 “실전 사례”가 구체적이지 않고, 60% 이상 감소 같은 수치도 근거 없이 단정됨. 코드 분할 전후, Lighthouse 지표, CDN 캐시 전략, SEO 대응 예시를 조금만 보완하면 학습 가능. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 대규모 React SPA 성능 튜닝 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 비판적 분석형 느낌도 약하고, “0.3점 이상 개선” 같은 표현은 기준이 애매함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 대규모 React SPA 성능 튜닝 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입혔을 뿐 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | review_notes: 기존 React SPA 성능 튜닝 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형 문장이 형식적이고 “0.3점 개선” 표현도 애매함. 민감정보 없음. 학습 제외 |
| NO_ID |  | rejected | dohyun | review_notes: 기존 React SPA 성능 튜닝 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음 |
| NO_ID |  | rejected | dohyun | review_notes: 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 실전 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | review_notes: 확률 개념을 입문 수준에 맞게 쉽게 설명했고, 동전·날씨 예시도 적절함. 기존 데이터와 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | review_notes: 기존 확률 설명 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약하고 형식 문장이 반복됨. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | review_notes: 기존 확률 설명 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입혔을 뿐 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 확률 설명 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형 문장이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 확률 설명 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 행렬 곱셈의 핵심 설명은 맞지만 “예시 위주” 요구에 비해 실제 계산 예시가 부족함. 간단한 2×2 행렬 곱 예시를 추가하면 학습 가능. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 행렬 곱셈 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약하고 형식 문장이 반복됨. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 행렬 곱셈 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 형식만 입혔을 뿐 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 행렬 곱셈 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 창의적 확장형 문장이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 행렬 곱셈 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 계산 방법과 선형변환 관계 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 경사 하강법의 핵심 원리와 학습률이 수렴에 미치는 영향을 잘 설명함. 학습률이 너무 크거나 작을 때의 문제와 SGD 예시도 포함되어 있어 학습 데이터로 사용 가능함. 기존 데이터와 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 에이전트 설정/질문 부분 없이 assistant 답변만 남아 있어 구조가 불완전함. 기존 경사 하강법 데이터와도 중복됨. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 경사 하강법 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입힌 수준임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 경사 하강법 데이터와 질문·핵심 내용이 거의 동일함. 창의적 확장형 문장이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 거의 동일한 완전 중복 데이터임. 학습 가치 없음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 베이즈 정리와 베이지안 추론의 핵심 개념, 장점, 단점을 잘 설명함. 질문 의도에 맞고 기존 데이터와 주제가 달라 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 베이즈 정리 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 베이즈 정리 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 베이즈 정리 데이터와 핵심 내용이 거의 동일함. 창의적 확장형 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 베이즈 정리 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 이론적 장단점 분석을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | A/B 테스트 설계에서 검정력, 표본 크기, 유의수준, 다중 비교 문제를 실무 관점으로 설명함. 질문 의도에 맞고 기존 데이터와 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 A/B 테스트 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약하고 형식 문장이 반복됨. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 A/B 테스트 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 논리적 탐구형 구조만 입힌 수준임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 A/B 테스트 데이터와 핵심 내용이 거의 동일함. 창의적 확장형 문장이 실제 확장 설명으로 이어지지 않아 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 존 A/B 테스트 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 실무 영향 설명을 요청했는데 객관식 문제로 바뀌어 질문 의도와 맞지 않음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | DNA 개념을 입문 수준에 맞게 쉽게 설명했고, 설계도·알파벳 비유도 적절함. 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 DNA 설명 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 DNA 설명 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 DNA 설명 데이터와 핵심 내용이 중복됨. 창의적 확장형 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 DNA 설명 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음 |
| NO_ID |  | reviewed | dohyun | 유사분열과 감수분열의 핵심 차이, 목적, 염색체 수를 잘 비교함. 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 이전 베이즈 정리 데이터와 거의 동일한 중복 데이터임. 현재 생명과학 흐름에도 섞여 있어 학습 가치 낮음. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 유사분열/감수분열 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 유사분열/감수분열 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 유사분열/감수분열 데이터와 중복됨. 창의적 확장 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 유사분열/감수분열 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 비교 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | CRISPR-Cas9의 원리, 응용 가능성, 기술적 한계를 핵심 중심으로 설명함. 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 CRISPR 설명 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 CRISPR 설명 데이터와 핵심 내용·설명 구조가 중복됨. 에이전트 설정 표기에 괄호 오류도 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 CRISPR 설명 데이터와 중복됨. 창의적 확장형 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 CRISPR 설명 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 원리와 한계 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 현대 종합, 자연선택, 유전자 부동, 소집단 효과를 핵심적으로 설명함. 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 진화론 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 진화론 데이터와 중복됨. 창의적 확장형 문장이 실제 확장으로 이어지지 않음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 진화론 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 에이전트 설정 표기 일부도 깨져 있음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 분석을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 임상 1~3상과 통계 고려사항은 설명했지만, 질문에 있는 FDA/EMA 규제 요건과 개발 전략 영향 설명이 부족함. 보완하면 학습 가능. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 임상 설계 데이터와 질문·핵심 내용이 유사하며, 비판적 분석형 느낌이 약함. EMA 설명도 부족함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 임상 설계 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 존 임상 설계 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 임상 설계 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 실무 영향 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 망각곡선과 간격 반복 설명은 괜찮지만, 구체 수치가 단정적으로 제시되어 있고 비유가 약함. 수치 표현을 완화하고 쉬운 예시를 보완하면 좋음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 망각곡선 데이터와 질문·핵심 내용·설명 구조가 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 망각곡선 데이터와 중복됨. 창의적 확장형 문장이 실제 설명으로 이어지지 않음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 망각곡선 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음 |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 인지 부하 이론의 핵심 개념과 세 가지 부하를 잘 정리함. 학습 설계와의 연결도 있음. 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 인지 부하 이론 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 인지 부하 이론 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 인지 부하 이론 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 인지 부하 이론 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 인지 부하 이론 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 메타인지 개념 설명은 괜찮지만, 질문의 “실증적 효과 분석”이 부족함. 자기주도 학습 효과나 전략 예시를 조금 보완하면 좋음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 메타인지 데이터와 질문·핵심 내용이 유사중복임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 메타인지 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 메타인지 데이터와 중복됨. 창의적 확장형 문장이 형식적으로 붙어 있음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 메타인지 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 에이전트 설정 표기도 일부 깨져 있음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 분석을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | needs_review | dohyun | 플라톤 인식론과 구성주의 개념은 설명했지만, 철학적 연결점과 교육 실천 함의 분석이 부족함. 연결 문장을 보완하면 학습 가능. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 플라톤/구성주의 데이터와 질문·핵심 내용이 유사중복임. 비판적 분석형 느낌도 약함. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 플라톤/구성주의 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 플라톤/구성주의 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 플라톤/구성주의 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 철학적 분석을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 성인 학습 이론, Kirkpatrick 모델, ROI 측정, 실무 도전을 간단히 설명함. 질문 의도에 맞고 중복 아님. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 L&D 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 존 L&D 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 L&D 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 L&D 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 실무 도전 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | StudyBridge PDF 업로드 후 청크 분할, 벡터화, 검색 기반 답변, 요약/퀴즈 활용을 쉽게 설명함. 프로젝트 학습 데이터로 사용 가능. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge PDF 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge PDF 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge PDF 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge PDF 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 에이전트 설정 표기도 일부 깨져 있음. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | StudyBridge RAG 질문-답변 흐름을 임베딩, 유사도 검색, 상위 K개 청크, LLM 답변 생성으로 설명함. 프로젝트 학습 데이터로 사용 가능. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge RAG 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge RAG 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge RAG 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge RAG 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 시스템 동작 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음 |
| NO_ID |  | reviewed | dohyun | Deep Search 파이프라인을 질문 분류, 다중 소스 검색, 답변 생성 흐름으로 설명함. 프로젝트 학습 데이터로 사용 가능. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Deep Search 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Deep Search 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 Deep Search 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 Deep Search 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 파이프라인 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | QLoRA, LoRA, 4비트 양자화, 커스텀 에이전트 예상 효과를 설명함. 프로젝트 학습 데이터로 사용 가능. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 QLoRA 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 QLoRA 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 QLoRA 데이터와 중복됨. 창의적 확장형 문장이 형식적임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 QLoRA 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 간결 요약형 형식은 맞지만 새 학습 가치가 낮음. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 기존 QLoRA 데이터와 주제·핵심 내용도 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | StudyBridge 실서비스 운영 관점에서 PDF 병목, pgvector 스케일링, LLM 비용, 모니터링 지표를 잘 정리함. 프로젝트 운영 학습 데이터로 사용 가능. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge 운영 최적화 데이터와 질문·핵심 내용이 거의 동일한 유사중복 데이터임. 비판적 분석형 느낌도 약함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge 운영 최적화 데이터와 설명 구조만 달라졌고 핵심 내용은 중복임. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge 운영 최적화 데이터와 중복됨. 창의적 확장형 문장이 형식적으로 붙어 있음. 민감정보 없음 |
| NO_ID |  | duplicate | dohyun | 기존 StudyBridge 운영 최적화 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | rejected | dohyun | 문제 출제형이라 자료보관함 퀴즈 기능과 중복됨. 사용자는 운영 전략 설명을 요청했는데 객관식 문제로 바뀜. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | @Transactional의 기본 동작, rollback 조건, readOnly 사용, self-invocation 문제까지 설명해 학습 데이터로 적절함. 중복 아님. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 자료보관함 AI 질문 API 흐름을 MaterialController → AiIntegrationService → FastAPI 순서로 잘 설명함. 코드 근거 기반이라 프로젝트 학습 데이터로 적합함. 민감정보 없음 |
| NO_ID |  | reviewed | dohyun | PDF 근거에 없는 내용을 구분하고, 일반 지식 보완을 별도로 표시함. RAG 답변 품질 기준 학습에 적합함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 RAG 기본 설명 데이터와 질문·핵심 내용이 거의 동일한 중복 데이터임. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 학습일지 수정 시 기존 피드백/요약 삭제 흐름을 코드 근거 기반으로 설명함. 프로젝트 기능 학습 데이터로 적합함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | PDF 업로드 API 처리 흐름을 컨트롤러, 서비스, S3 저장, 비동기 추출 상태까지 잘 설명함. 프로젝트 학습 데이터로 사용 가능. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | AI 질문 기능에서 텍스트가 없을 때 FastAPI 호출 없이 반환하는 흐름을 잘 설명함. Guard clause 개념도 포함되어 학습 데이터로 적절함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | Agent 엔티티 필드와 채팅방 연결 구조, 최대 3개 제한을 잘 설명함. StudyBridge 에이전트 학습 데이터로 적합함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 자료 삭제 시 RAG 청크가 남는 문제와 수정 위치를 명확히 짚음. 코드 리뷰형 학습 데이터로 유용함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | Material 엔티티 구조와 연관 관계, RAG 청크 별도 삭제 필요성을 잘 설명함. 프로젝트 구조 학습 데이터로 적합함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | Spring Boot와 FastAPI 간 AI_SERVER_API_KEY 전달·검증 방식을 보안 관점에서 잘 설명함. 운영 보안 학습 데이터로 적합함. 민감정보 없음 |
| NO_ID |  | reviewed | dohyun | PDF 텍스트 추출 서비스의 비동기 처리, OCR fallback, RAG ingest 연결 위치를 잘 설명함. 프로젝트 파이프라인 학습 데이터로 적합함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | PDF_RAG_CONTEXT에 근거해 데드락 조건을 정확히 답하고, PDF 기반 설명과 참고 요약을 구분함. RAG 답변 예시로 적합함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | Round Robin 스케줄링을 PDF 근거 기반으로 설명하고, 일반 지식 보완도 구분함. 학습 데이터로 사용 가능함. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 유사 청크가 없을 때 PDF에 없는 내용을 단정하지 않고 안내하는 답변임. RAG 실패/무근거 처리 학습 데이터로 적합함. 민감정보 없음. |
| NO_ID |  | duplicate | dohyun | 기존 데드락 조건 RAG 답변과 주제·핵심 내용이 거의 동일한 중복 데이터임. 검증 메모는 좋지만 새 학습 가치는 낮음. 민감정보 없음. |
| NO_ID |  | reviewed | dohyun | 자료 요약이 저장본 우선인지 새 생성인지 코드 근거로 명확히 설명함. 캐시/재생성 흐름 학습 데이터로 적합함. 민감정보 없음. |

## 학습 가능 여부
- reviewed + approved 샘플 수: 53
- pdf_rag 샘플 수: 0
- agent_profile 샘플 수: 0
- failure_case 샘플 수: 0
- java_code 비율: 0.00%
- 결론: NOT_READY
