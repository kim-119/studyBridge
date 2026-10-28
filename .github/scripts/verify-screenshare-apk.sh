#!/usr/bin/env bash
# APK 에 네이티브 전체 화면공유(MediaProjection + libwebrtc + OpenVidu SCREEN)가 실제로 들어 있는지 확인한다.
# usage: verify-screenshare-apk.sh <apk> [Gradle 병합 AndroidManifest.xml]   (ANDROID_HOME 의 build-tools aapt2 사용)
#        verify-screenshare-apk.sh --check-manifest-dump <aapt2 dump xmltree 출력>   (SDK 없이 매니페스트 판정만 — 회귀 테스트용)
#        verify-screenshare-apk.sh --check-merged-manifest <Gradle 병합 AndroidManifest.xml>
set -euo pipefail

fail() { echo "FAIL: $*"; exit 1; }

# aapt2 dump xmltree 출력에서 ScreenShareService 의 <service> 요소 속성 줄만 뽑는다. 예:
#   E: service (line=77)
#     A: http://schemas.android.com/apk/res/android:name(0x01010003)="kr.co.studybridge.screenshare.ScreenShareService" (Raw: "…")
#     A: http://schemas.android.com/apk/res/android:foregroundServiceType(0x01010599)=0x00000020
screen_share_service_attributes() {
  awk '
    /^[[:space:]]*E: / {
      if (in_service && is_target) printf "%s", attrs
      in_service = ($0 ~ /E: service([[:space:]]|$)/); is_target = 0; attrs = ""; next
    }
    in_service && /^[[:space:]]*A: / {
      attrs = attrs $0 "\n"
      if ($0 ~ /:name\(0x[0-9a-fA-F]+\)="kr\.co\.studybridge\.screenshare\.ScreenShareService"/) is_target = 1
    }
    END { if (in_service && is_target) printf "%s", attrs }
  ' "$1"
}

# foregroundServiceType 은 flags(TYPE_INT_HEX) 로 컴파일되어 aapt2 가 0x%08x(예: 0x00000020)로 출력한다.
# 10진·16진(자릿수 무관) 값을 읽어 mediaProjection 비트(0x20)를 확인한다. 다른 서비스의 값은 보지 않는다.
check_manifest_dump() {
  local dump="$1" attrs line value permission
  attrs=$(screen_share_service_attributes "$dump")
  [ -n "$attrs" ] || fail "ScreenShareService 선언이 없습니다"
  line=$(printf '%s\n' "$attrs" | grep -E 'foregroundServiceType\(0x[0-9a-fA-F]+\)=' || true)
  [ -n "$line" ] || fail "ScreenShareService 에 foregroundServiceType 이 없습니다"
  value=$(printf '%s\n' "$line" | sed -E 's/.*foregroundServiceType\(0x[0-9a-fA-F]+\)=(\(type 0x[0-9a-fA-F]+\))?//; s/[[:space:]].*$//')
  [[ "$value" =~ ^(0x[0-9a-fA-F]+|[0-9]+)$ ]] || fail "foregroundServiceType 값을 읽지 못했습니다: $line"
  (( (value & 0x20) != 0 )) || fail "ScreenShareService 의 foregroundServiceType 에 mediaProjection(0x20)이 없습니다: $value"
  printf '%s\n' "$attrs" | grep -E ':exported\(0x[0-9a-fA-F]+\)=false' > /dev/null \
    || fail "ScreenShareService 는 exported=false 여야 합니다"
  for permission in FOREGROUND_SERVICE FOREGROUND_SERVICE_MEDIA_PROJECTION POST_NOTIFICATIONS INTERNET; do
    grep -F "\"android.permission.$permission\"" "$dump" > /dev/null || fail "권한 선언이 없습니다: $permission"
  done
  echo "OK manifest(aapt2): ScreenShareService foregroundServiceType=$value(mediaProjection) exported=false + FOREGROUND_SERVICE(_MEDIA_PROJECTION), POST_NOTIFICATIONS, INTERNET"
}

# Gradle 병합 매니페스트(텍스트 XML) — 라이브러리 매니페스트가 앱에 병합됐는지 빌드 산출물에서도 확인한다.
check_merged_manifest() {
  local merged="$1" tag
  test -f "$merged" || fail "Gradle 병합 매니페스트가 없습니다: $merged"
  tag=$(tr '\n' ' ' < "$merged" | grep -oE '<service[^>]*>' | grep -F 'kr.co.studybridge.screenshare.ScreenShareService' || true)
  [ -n "$tag" ] || fail "Gradle 병합 매니페스트에 ScreenShareService 가 없습니다: $merged"
  printf '%s\n' "$tag" | grep -E 'android:foregroundServiceType="[^"]*mediaProjection' > /dev/null \
    || fail "Gradle 병합 매니페스트의 ScreenShareService 에 foregroundServiceType=mediaProjection 이 없습니다"
  echo "OK merged manifest(Gradle): $merged"
}

case "${1:-}" in
  --check-manifest-dump) check_manifest_dump "${2:?aapt2 dump 파일이 필요합니다}"; exit 0 ;;
  --check-merged-manifest) check_merged_manifest "${2:?병합 매니페스트 파일이 필요합니다}"; exit 0 ;;
esac

APK="${1:?APK 경로가 필요합니다}"
MERGED_MANIFEST="${2:-}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

test -f "$APK" || fail "APK 가 없습니다: $APK"
AAPT2=$(ls "$ANDROID_HOME"/build-tools/*/aapt2 2>/dev/null | sort -V | tail -1)
test -x "$AAPT2" || fail "aapt2 를 찾지 못했습니다(ANDROID_HOME=$ANDROID_HOME)"

unzip -l "$APK" > "$WORK/entries.txt"
for abi in arm64-v8a armeabi-v7a x86_64 x86; do
  grep -F "lib/$abi/libjingle_peerconnection_so.so" "$WORK/entries.txt" > /dev/null \
    || fail "libwebrtc 네이티브 라이브러리가 없습니다: lib/$abi/libjingle_peerconnection_so.so"
done
echo "OK libwebrtc .so: arm64-v8a armeabi-v7a x86_64 x86"

if [ -n "$MERGED_MANIFEST" ]; then check_merged_manifest "$MERGED_MANIFEST"; fi

# 최종 APK 의 binary AndroidManifest.xml 은 SDK 도구(aapt2)로 풀어서 본다.
"$AAPT2" dump xmltree --file AndroidManifest.xml "$APK" > "$WORK/manifest.txt"
screen_share_service_attributes "$WORK/manifest.txt" | sed 's/^/  aapt2> /'
check_manifest_dump "$WORK/manifest.txt"

mkdir -p "$WORK/dex"
unzip -q -o "$APK" 'classes*.dex' -d "$WORK/dex"
cat "$WORK"/dex/classes*.dex > "$WORK/all.dex"
for symbol in \
  "Lkr/co/studybridge/screenshare/ScreenShareService;" \
  "Lkr/co/studybridge/screenshare/ScreenSharePlugin;" \
  "Lkr/co/studybridge/screenshare/DisplayCapturer;" \
  "Lkr/co/studybridge/screenshare/ScreenPublisher;" \
  "Lorg/webrtc/PeerConnectionFactory;" \
  "Lorg/webrtc/SurfaceTextureHelper;" \
  "Landroid/media/projection/MediaProjection;" \
  "Lokhttp3/WebSocket;" \
  "StudyBridgeScreenShare"; do
  grep -a -F "$symbol" "$WORK/all.dex" > /dev/null || fail "dex 에 필수 클래스/이름이 없습니다: $symbol"
done
echo "OK dex: 화면공유 서비스·플러그인·캡처·송출 + libwebrtc + MediaProjection + OkHttp WebSocket"

echo "PASS: $APK 에 네이티브 전체 화면공유가 포함되어 있습니다 ($(stat -c %s "$APK") bytes)"
