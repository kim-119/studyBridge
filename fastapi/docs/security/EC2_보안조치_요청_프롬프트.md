EC2 보안 조치 요청 (P0) — EC2 Claude Code 에 그대로 전달할 프롬프트
작성 2026-10-28, 작성 위치 ai07(읽기 전용 점검 결과 기반). 이 문서의 명령은 ai07 에서 실행하지 않았다.


1. 프롬프트 본문 (아래 줄부터 "프롬프트 끝" 까지 복사)

너는 StudyBridge EC2(43.202.211.123, ubuntu) 운영 서버의 보안 담당 엔지니어다. 아래 P0 문제를 기존 운영 연결을 끊지 않고 막아라.
작업 원칙: 먼저 읽기 전용으로 현재 상태를 다시 확인하고, 변경 전 계획과 롤백 명령을 사용자에게 보여 준 뒤 승인을 받고 한 단계씩 적용한다. Spring/React/FastAPI 소스 코드, docker compose 정의, 운영 .env 는 수정하지 않는다. docker compose 전체 재기동, 서버 재부팅, sshd 의 22번 포트 설정 변경은 하지 않는다. 각 단계 뒤에 아래 3절의 검증을 실행하고, 실패하면 즉시 그 단계의 롤백을 실행한다.

배경(2026-10-28 ai07 에서 확인한 사실):
가) 인터넷에서 TCP 접속이 되는 포트: 22, 80, 443, 4443, 3478, 8000, 8001, 18080, 18081.
나) 8000 = studybridge-fastapi.service(Secondary FastAPI, uvicorn hotfix_main --host 0.0.0.0). 외부에서 /health, /openapi.json 이 200. 라우트 75개 중 50개는 인증 의존성이 없고, 그중 멀티챗·퀴즈·요약·fetch-stream 등 LLM 을 호출하는 POST 가 약 40개다. 이 프로세스는 OLLAMA_BASE_URL=http://localhost:11434 로 ai07 의 GPU Ollama 에 SSH 역터널(127.0.0.1:11434)로 접속하고 OPENAI_API_KEY, TAVILY_API_KEY 도 갖고 있다. 즉 인증 없는 외부 요청이 ai07 GPU 와 유료 API 를 쓸 수 있다.
다) 8001 = systemd 밖에서 20일째 실행 중인 python /tmp/addon-ai-candidate.py (/home/ubuntu/studyBridge-addon-integration/fastapi 의 hotfix_main 을 0.0.0.0:8001 로 실행, studyBridge/fastapi/.env 를 그대로 로드). 같은 문제(무인증, ai07 GPU, OpenAI 키)를 가진 두 번째 공개 진입점이다. 컨테이너 studybridge-addon-candidate(-v2) 의 FASTAPI_PRIMARY_BASE_URL=http://host.docker.internal:8001 가 이 프로세스를 쓴다.
라) 18080, 18081 = 빌드 산출물/이전 세션 scratchpad 에서 실행한 java -jar backend-0.0.1-SNAPSHOT.jar 두 개(*: 바인딩, 14~15일째). /health 는 401 이지만 운영 DB 에 붙는 관리되지 않는 Spring 인스턴스가 공개돼 있다.
마) ufw 비활성, iptables INPUT 정책 ACCEPT. 현재 보호막은 AWS 보안그룹뿐인데 그 보안그룹이 위 포트를 허용하고 있다.
바) sshd GatewayPorts=clientspecified. 지금 ai07 의 역터널은 127.0.0.1 에만 바인딩되어 있지만 클라이언트 설정만으로 공개 바인딩이 가능한 상태다.
사) capstone-coturn 컨테이너가 host 네트워크 모드라 127.0.0.1:11434(ai07 GPU Ollama 역터널)에 접근할 수 있다(정보 공유, 이번 조치 대상 아님).
아) 정상 호출자(7일 접근 기록): 8000 에는 172.18.0.x(Spring 계열 컨테이너)와 127.0.0.1(CD/ops 헬스체크)만 있고, 외부 IP 는 스캐너뿐이다. 공인 주소로 8000/8001 을 부르는 설정은 찾지 못했다.

조치 1 (최우선, 서비스 영향 없음) — AWS 보안그룹 인바운드 정리
인스턴스에 붙은 보안그룹의 인바운드에서 8000, 8001, 18080, 18081 을 제거한다. 22 는 관리자 CIDR 로만 제한하는 것을 권장한다. 80, 443, 4443, 3478(TCP/UDP)과 OpenVidu/coturn 미디어 포트 범위는 유지한다.
보안그룹은 호스트 외부 트래픽만 거르므로, 컨테이너→호스트(172.17.0.1/172.18.0.1) 경로와 127.0.0.1 경로에는 영향이 없다.
AWS 권한이 없으면 이 조치는 사용자에게 콘솔 작업으로 넘기고 조치 2 를 진행한다. AWS CLI 를 쓸 수 있으면 먼저 describe 로 현재 규칙을 출력해 보여 준다:
  aws ec2 describe-instances --instance-ids <인스턴스ID> --query "Reservations[].Instances[].SecurityGroups"
  aws ec2 describe-security-groups --group-ids <sg-id> --query "SecurityGroups[].IpPermissions"
  (승인 후) aws ec2 revoke-security-group-ingress --group-id <sg-id> --protocol tcp --port 8000 --cidr 0.0.0.0/0   8001, 18080, 18081 도 같은 방식. IPv6(::/0) 규칙이 있으면 --ip-permissions 로 함께 제거.
롤백: authorize-security-group-ingress 로 같은 규칙을 다시 추가.

조치 2 (보안그룹 작업이 늦어지는 경우의 즉시 차단, 호스트 방화벽) — 해당 포트를 loopback 과 도커 사설망에서만 허용
  for p in 8000 8001 18080 18081; do
    sudo iptables -I INPUT -p tcp --dport $p -j DROP
    sudo iptables -I INPUT -p tcp --dport $p -s 172.16.0.0/12 -j ACCEPT
    sudo iptables -I INPUT -p tcp --dport $p -s 127.0.0.0/8 -j ACCEPT
  done
  sudo iptables -S INPUT
-I 는 맨 위에 넣으므로 실제 순서는 127 허용 → 172.16/12 허용 → DROP 이 된다. Docker 가 관리하는 DOCKER/DOCKER-USER 체인은 건드리지 않는다(이 포트들은 컨테이너 게시 포트가 아니라 호스트 프로세스다).
영구 적용은 netfilter-persistent 가 설치돼 있을 때만 sudo netfilter-persistent save 로 한다. 설치돼 있지 않으면 재부팅 전까지만 유효하다는 것을 사용자에게 알리고 설치 여부를 묻는다.
롤백: 같은 규칙을 -D 로 지운다(for p in ...; do sudo iptables -D INPUT -p tcp --dport $p -s 127.0.0.0/8 -j ACCEPT; sudo iptables -D INPUT -p tcp --dport $p -s 172.16.0.0/12 -j ACCEPT; sudo iptables -D INPUT -p tcp --dport $p -j DROP; done).

조치 3 — 관리되지 않는 공개 프로세스 정리(사용자 확인 후)
8001(addon-ai-candidate), 18080, 18081 이 지금 무엇에 쓰이는지 먼저 확인한다:
  sudo ss -tnp state established "( sport = :8001 or sport = :18080 or sport = :18081 )"
  sudo docker inspect -f '{{.Name}} {{range .Config.Env}}{{println .}}{{end}}' studybridge-addon-candidate studybridge-addon-candidate-v2 | grep -E "8001|18080|18081"
  grep -rn "18080\|18081\|8001" /etc/nginx/ 2>/dev/null
쓰는 곳이 없으면 사용자 승인 후 프로세스를 종료한다(kill <PID>, pkill -f 패턴은 쓰지 않는다 — 자기 셸을 죽일 수 있다). 8001 을 계속 써야 하면 --host 를 172.17.0.1 로 바꿔 다시 띄우는 방안을 사용자에게 제안한다(127.0.0.1 로 바꾸면 컨테이너에서 host.docker.internal 로 접근할 수 없다).

조치 4 (권장) — sshd GatewayPorts no
/etc/ssh/sshd_config.d/ 에 GatewayPorts no 를 추가하고 sudo sshd -t 로 문법 확인 후 sudo systemctl reload ssh. 기존 세션은 끊기지 않는다. ai07 의 역터널(-R 127.0.0.1:18000, -R 11434)은 loopback 바인딩이라 영향이 없어야 하지만, reload 뒤 ss -ltn | grep -E "18000|11434" 로 127.0.0.1 바인딩이 그대로인지 확인한다.
롤백: 추가한 파일을 지우고 reload.

조치 5 — ai07 코드 배포 후 확인할 것(정보)
feature/ai-gateway-scheduler 가 LLM-clean 에 반영되면 CD 가 Secondary 를 재배포하고, FastAPI 의 출발지 네트워크 가드(AI_NETWORK_GUARD=enforce 기본)가 loopback·사설망 밖의 요청에 403 AI_NETWORK_FORBIDDEN 을 돌려준다(GET /health 예외). 보안그룹·방화벽 조치가 1차 방어, 이 가드가 2차 방어다. 8001 프로세스는 다른 디렉터리의 코드라 CD 로 갱신되지 않는다.
프롬프트 끝.


2. 이 프롬프트가 지키는 운영 연결

Spring 컨테이너 → host.docker.internal:8000(Secondary), :18000(socat → ai07 Primary 역터널): 사설망 출발지라 조치 1·2 의 영향 없음.
CD 헬스체크와 ops 스크립트 → 127.0.0.1:8000: 영향 없음.
ai07 역터널(18000, 11434, 22207): 조치 4 이후에도 loopback 바인딩 유지.
nginx(80/443) → Spring(127.0.0.1:8080): 변경 없음.


3. 검증 명령

외부(AWS 밖, 예: ai07)에서 — 조치 뒤 모두 closed 여야 한다:
  H=43.202.211.123; for p in 8000 8001 18080 18081 11434 18000; do timeout 3 bash -c "exec 3<>/dev/tcp/$H/$p" 2>/dev/null && echo "$p OPEN" || echo "$p closed"; done
  curl -s -o /dev/null -w "%{http_code}\n" https://www.studybridge.co.kr/       (200, 웹 정상)
  curl -s -o /dev/null -w "%{http_code}\n" https://www.studybridge.co.kr/api/health   (Spring 경로, 기존과 같은 코드)
EC2 내부에서 — 정상 연결 유지 확인:
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health        (200)
  sudo docker exec capstone-spring sh -c 'wget -qO- -T 5 http://host.docker.internal:8000/health || curl -s -m 5 http://host.docker.internal:8000/health'   (응답 있음)
  sudo docker exec capstone-spring sh -c 'wget -qO- -T 5 http://host.docker.internal:18000/health || curl -s -m 5 http://host.docker.internal:18000/health'  (ai07 Primary 응답)
  sudo journalctl -u studybridge-fastapi --since "-10min" --no-pager | tail -20      (오류 없음)
  ss -ltn | grep -E ":(18000|11434|22207) "                                           (127.0.0.1 바인딩)
ai07 코드 배포 후(조치 5) 외부에서 — 포트가 아직 열려 있다면 가드가 막는지(추론을 일으키지 않는 GET 으로 확인):
  curl -s -m 5 http://43.202.211.123:8000/openapi.json | head -c 120   (AI_NETWORK_FORBIDDEN)
