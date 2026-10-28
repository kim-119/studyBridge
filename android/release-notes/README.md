# Android 릴리스 노트

APK 를 배포할 때마다 **배포될 versionName** 이름의 파일이 있어야 합니다. 예: 공개 버전이 1.3 이면 다음 APK 는 1.4 이므로 `android/release-notes/1.4.txt`.

- 파일이 없거나, 비었거나, 다운로드 페이지(`/app`)에서 숨겨지는 문장이 하나라도 있으면 `android-release.yml` 이 **빌드 전에 배포를 중단**합니다. 커밋 제목으로 대신 채우지 않습니다.
- 검증은 웹 다운로드 페이지가 쓰는 함수(LLM-clean `frontend/src/utils/appRelease.js` 의 `toUserReleaseNotes`)를 그대로 받아 실행하므로, 통과한 문장은 화면에 그대로 보입니다.

## 작성 규칙

- 한 줄에 한 항목, 최대 8개. `#` 로 시작하는 줄과 빈 줄은 무시합니다.
- `제목: 설명` 형식(제목 30자 이하)을 권장합니다. 예: `화면공유 개선: PC에서 공유한 화면을 앱에서 볼 수 있습니다.`
- 한국어로, 사용자가 실제로 느끼는 변화만 적습니다. 기능 플래그로 숨겨진 기능은 적지 않습니다.
- 앞에 `-`, `•`, `1.` 같은 기호·번호를 붙이지 않습니다(화면이 번호를 매기고, 앞 숫자는 잘려 보입니다).
- `feat:`·`fix:`·`Merge pull request`·커밋 해시·CI 용어는 화면에서 숨겨지므로 차단됩니다.
- 사용자에게 보이는 변화가 없으면 없는 기능을 만들지 말고 그대로 적습니다. 예: `기능 변경 없음: 1.3과 앱 화면과 사용 방법이 같은 유지보수 업데이트입니다.`
- 이전 버전 파일이나 현재 공개 버전과 똑같은 내용은 차단됩니다.

로컬 확인:

```bash
git show origin/LLM-clean:frontend/src/utils/appRelease.js > /tmp/appRelease.mjs
node .github/scripts/validate-release-notes.mjs --version 1.4 --dir android/release-notes --filter /tmp/appRelease.mjs
```
