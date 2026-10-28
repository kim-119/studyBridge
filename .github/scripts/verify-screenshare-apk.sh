#!/usr/bin/env bash
# APK 에 네이티브 전체 화면공유(MediaProjection + libwebrtc + OpenVidu SCREEN)가 실제로 들어 있는지 확인한다.
# usage: verify-screenshare-apk.sh <apk>   (ANDROID_HOME 의 build-tools aapt2 사용)
set -euo pipefail

APK="${1:?APK 경로가 필요합니다}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

test -f "$APK" || fail "APK 가 없습니다: $APK"
AAPT2=$(ls "$ANDROID_HOME"/build-tools/*/aapt2 2>/dev/null | sort -V | tail -1)
test -x "$AAPT2" || fail "aapt2 를 찾지 못했습니다(ANDROID_HOME=$ANDROID_HOME)"

unzip -l "$APK" > "$WORK/entries.txt"
for abi in arm64-v8a armeabi-v7a x86_64 x86; do
  grep -F "lib/$abi/libjingle_peerconnection_so.so" "$WORK/entries.txt" > /dev/null \
    || fail "libwebrtc 네이티브 라이브러리가 없습니다: lib/$abi/libjingle_peerconnection_so.so"
done
echo "OK libwebrtc .so: arm64-v8a armeabi-v7a x86_64 x86"

"$AAPT2" dump xmltree --file AndroidManifest.xml "$APK" > "$WORK/manifest.txt"
grep -F "kr.co.studybridge.screenshare.ScreenShareService" "$WORK/manifest.txt" > /dev/null \
  || fail "ScreenShareService 선언이 없습니다"
# foregroundServiceType mediaProjection = 0x20
grep -E "foregroundServiceType\(0x[0-9a-f]+\)=(32|0x20|mediaProjection)" "$WORK/manifest.txt" > /dev/null \
  || fail "foregroundServiceType=mediaProjection 선언이 없습니다"
for permission in FOREGROUND_SERVICE FOREGROUND_SERVICE_MEDIA_PROJECTION POST_NOTIFICATIONS INTERNET; do
  grep -F "\"android.permission.$permission\"" "$WORK/manifest.txt" > /dev/null || fail "권한 선언이 없습니다: $permission"
done
echo "OK manifest: ScreenShareService(mediaProjection) + FOREGROUND_SERVICE(_MEDIA_PROJECTION), POST_NOTIFICATIONS"

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
