#!/usr/bin/env python3
"""
StudyBridge Android APK 배포 스크립트 (EC2 측, 서버 재배포 없이 S3 만 갱신)

GitHub Actions(android-release.yml)가 서명·검증을 마친 APK + release-manifest.json 을 EC2 로 전송한 뒤
이 스크립트를 SSH 로 실행한다. AWS 자격증명은 EC2 의 기존 .env(AWS_ACCESS_KEY_ID/SECRET/REGION/S3_BUCKET)만 쓴다
(GitHub 에 AWS 키를 두지 않는다). 출력에 비밀값은 찍지 않는다.

S3 레이아웃 ({prefix} 기본 android/):
  {prefix}releases/StudyBridge-{versionName}.apk    버전 고정 APK — immutable, Cache-Control public max-age=1y
  {prefix}releases/StudyBridge-{versionName}.json   버전별 매니페스트(최종 version.json 과 동일 내용)
  {prefix}latest/StudyBridge-latest.apk             최신 APK — Cache-Control no-cache
  {prefix}latest/version.json                       최신 메타데이터 — 반드시 "가장 마지막" 에 갱신

장애 안전 순서(사용자가 업로드 중인 APK 를 참조하는 race 방지):
  1 APK 로컬 검증(sha256/zip/서명 블록/패키지명)  2 기존 latest 규칙 검사(versionCode 증가·버전 고정 키 불변)
  3 버전 고정 APK 업로드 + HEAD 검증  4 버전 매니페스트 업로드  5 latest APK 서버측 복사 + HEAD 검증  6 version.json 갱신(마지막)

사용 예:
  python3 ops/android/publish-android-release.py --incoming /home/ubuntu/studybridge-android-releases/incoming/<run_id> --verify-public
  python3 ops/android/publish-android-release.py --incoming <dir> --dry-run
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile

APK_CONTENT_TYPE = "application/vnd.android.package-archive"
VERSION_NAME_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_ENV_FILE = "/home/ubuntu/studyBridge/.env"
DEFAULT_RECORD_DIR = "/home/ubuntu/studybridge-android-releases/published"
LATEST_APK_NAME = "StudyBridge-latest.apk"


class PublishError(Exception):
    pass


def log(msg):
    print(f"[android-release] {msg}", flush=True)


def load_env_file(path):
    """KEY=VALUE 파일을 os.environ 에 주입(이미 있는 값은 유지). 값은 출력하지 않는다."""
    if not path or not os.path.isfile(path):
        return []
    loaded = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v
                loaded.append(k)
    return loaded


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_b64(data):
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


def validate_apk(apk_path, manifest, expected_package):
    """CI 가 apksigner 로 서명을 검증했더라도 EC2 에서 독립적으로 무결성/정체성을 재확인한다."""
    if not os.path.isfile(apk_path):
        raise PublishError(f"APK 파일이 없습니다: {apk_path}")
    size = os.path.getsize(apk_path)
    if size <= 0:
        raise PublishError("APK 크기가 0 입니다")
    if int(manifest["fileSize"]) != size:
        raise PublishError(f"fileSize 불일치: manifest={manifest['fileSize']} actual={size}")
    digest = sha256_file(apk_path)
    if digest != manifest["sha256"]:
        raise PublishError(f"sha256 불일치: manifest={manifest['sha256']} actual={digest}")
    try:
        with zipfile.ZipFile(apk_path) as z:
            bad = z.testzip()
            if bad is not None:
                raise PublishError(f"zip 손상 엔트리: {bad}")
            names = set(z.namelist())
            for required in ("AndroidManifest.xml", "classes.dex"):
                if required not in names:
                    raise PublishError(f"APK 필수 엔트리 누락: {required}")
            axml = z.read("AndroidManifest.xml")
    except zipfile.BadZipFile as e:
        raise PublishError(f"APK 가 zip 형식이 아닙니다: {e}")
    pkg_utf16 = expected_package.encode("utf-16-le")
    if pkg_utf16 not in axml and expected_package.encode("utf-8") not in axml:
        raise PublishError(f"AndroidManifest.xml 에 패키지명 {expected_package} 이 없습니다")
    with open(apk_path, "rb") as f:
        data = f.read()
    if b"APK Sig Block 42" not in data:
        raise PublishError("APK Signature Scheme v2/v3 서명 블록이 없습니다(미서명 APK)")
    return digest, size, data


def parse_manifest(path, args):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    for key in ("packageName", "versionCode", "versionName", "sha256", "fileSize"):
        if key not in m:
            raise PublishError(f"manifest 필수 필드 누락: {key}")
    if m["packageName"] != args.expected_package:
        raise PublishError(f"packageName 불일치: manifest={m['packageName']} expected={args.expected_package}")
    try:
        m["versionCode"] = int(m["versionCode"])
        m["fileSize"] = int(m["fileSize"])
    except (TypeError, ValueError):
        raise PublishError("versionCode/fileSize 는 정수여야 합니다")
    if m["versionCode"] <= 0:
        raise PublishError("versionCode 는 1 이상이어야 합니다")
    m["versionName"] = str(m["versionName"]).strip()
    if not VERSION_NAME_RE.match(m["versionName"]):
        raise PublishError(f"versionName 형식 오류(숫자.숫자[.숫자]): {m['versionName']}")
    m["sha256"] = str(m["sha256"]).lower()
    if not SHA256_RE.match(m["sha256"]):
        raise PublishError("sha256 은 64자리 hex 여야 합니다")
    notes = m.get("releaseNotes") or []
    if isinstance(notes, str):
        notes = [notes]
    m["releaseNotes"] = [str(n).strip() for n in notes if str(n).strip()]
    if args.release_notes_file:
        with open(args.release_notes_file, encoding="utf-8") as f:
            m["releaseNotes"] = [ln.strip().lstrip("-• ").strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    if not m.get("releaseDate"):
        m["releaseDate"] = dt.datetime.now(KST).replace(microsecond=0).isoformat()
    m["forceUpdate"] = bool(args.force_update or m.get("forceUpdate", False))
    if args.expected_signer_sha256:
        signer = str(m.get("signerCertSha256", "")).replace(":", "").lower()
        if signer != args.expected_signer_sha256.replace(":", "").lower():
            raise PublishError("서명 인증서 SHA-256 이 기대값과 다릅니다(릴리즈 키스토어 아님)")
    return m


def s3_head(s3, bucket, key):
    from botocore.exceptions import ClientError
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def s3_get_json(s3, bucket, key):
    from botocore.exceptions import ClientError
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    try:
        return json.loads(body.decode("utf-8"))
    except Exception as e:
        log(f"WARN 기존 version.json 파싱 실패({e}); 규칙 검사에서 무시합니다")
        return None


def build_metadata(m, args, min_supported):
    base = args.public_base_url.rstrip("/")
    return {
        "platform": "android",
        "packageName": m["packageName"],
        "versionCode": m["versionCode"],
        "versionName": m["versionName"],
        "downloadUrl": f"{base}/downloads/android/{LATEST_APK_NAME}",
        "versionedDownloadUrl": f"{base}/downloads/android/StudyBridge-{m['versionName']}.apk",
        "releaseDate": m["releaseDate"],
        "releaseNotes": m["releaseNotes"],
        "forceUpdate": m["forceUpdate"],
        "minimumSupportedVersionCode": min_supported,
        "sha256": m["sha256"],
        "fileSize": m["fileSize"],
        "gitSha": m.get("gitSha"),
        "runId": m.get("runId"),
        "signerCertSha256": m.get("signerCertSha256"),
        "publishedAt": dt.datetime.now(KST).replace(microsecond=0).isoformat(),
    }


def verify_public(args, metadata):
    """운영 공개 URL 로 최종 확인: /api/app/version 의 versionCode 와 latest 다운로드(302→200, MIME, sha256)."""
    base = args.public_base_url.rstrip("/")
    with urllib.request.urlopen(f"{base}/api/app/version", timeout=20) as r:
        body = json.loads(r.read().decode("utf-8"))
    if int(body.get("versionCode", -1)) != metadata["versionCode"]:
        raise PublishError(f"공개 /api/app/version versionCode={body.get('versionCode')} ≠ {metadata['versionCode']} (캐시 TTL 내일 수 있음)")
    log(f"public /api/app/version OK versionCode={body['versionCode']} versionName={body['versionName']}")
    req = urllib.request.Request(metadata["downloadUrl"], method="GET")
    with urllib.request.urlopen(req, timeout=120) as r:  # 302 자동 추적
        ctype = r.headers.get("Content-Type", "")
        h = hashlib.sha256()
        total = 0
        for chunk in iter(lambda: r.read(1024 * 1024), b""):
            h.update(chunk)
            total += len(chunk)
    if h.hexdigest() != metadata["sha256"]:
        raise PublishError("공개 URL 다운로드 sha256 불일치")
    if APK_CONTENT_TYPE not in ctype:
        raise PublishError(f"공개 URL Content-Type 이상: {ctype}")
    log(f"public download OK bytes={total} content-type={ctype} sha256=match")


def main():
    ap = argparse.ArgumentParser(description="StudyBridge Android APK → S3 배포")
    ap.add_argument("--incoming", required=True, help="APK 와 release-manifest.json 이 있는 디렉터리")
    ap.add_argument("--apk", default=None, help="APK 파일명(기본: manifest.apkFileName 또는 app-release.apk)")
    ap.add_argument("--manifest", default="release-manifest.json")
    ap.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="AWS_* 를 읽을 .env (값은 출력하지 않음)")
    ap.add_argument("--bucket", default=None, help="기본: AWS_S3_BUCKET")
    ap.add_argument("--region", default=None, help="기본: AWS_REGION")
    ap.add_argument("--s3-prefix", default=os.environ.get("ANDROID_RELEASE_S3_PREFIX", "android/"))
    ap.add_argument("--public-base-url", default=os.environ.get("ANDROID_RELEASE_PUBLIC_BASE_URL", "https://studybridge.co.kr"))
    ap.add_argument("--expected-package", default="kr.co.studybridge.app")
    ap.add_argument("--expected-signer-sha256", default=os.environ.get("ANDROID_RELEASE_SIGNER_SHA256", ""),
                    help="릴리즈 키스토어 인증서 SHA-256(선택). 지정 시 manifest.signerCertSha256 과 일치해야 한다")
    ap.add_argument("--force-update", action="store_true")
    ap.add_argument("--min-supported-version-code", type=int, default=None,
                    help="기본: manifest 값 → 기존 latest 값 → 1 (새 versionCode 이하여야 함)")
    ap.add_argument("--release-notes-file", default=None, help="한 줄당 한 항목(manifest.releaseNotes 대체)")
    ap.add_argument("--allow-same-version", action="store_true",
                    help="동일 versionCode·동일 sha256 재실행(멱등 재배포) 허용")
    ap.add_argument("--record-dir", default=DEFAULT_RECORD_DIR, help="배포 기록 사본 디렉터리('' 이면 생략)")
    ap.add_argument("--verify-public", action="store_true", help="배포 후 운영 공개 URL 로 최종 검증")
    ap.add_argument("--dry-run", action="store_true", help="검증·계획만 출력하고 S3 쓰기 없음")
    args = ap.parse_args()

    loaded = load_env_file(args.env_file)
    if loaded:
        log(f"env-file 로드: {len(loaded)} keys ({args.env_file})")
    bucket = args.bucket or os.environ.get("AWS_S3_BUCKET")
    region = args.region or os.environ.get("AWS_REGION")
    if not bucket:
        raise PublishError("버킷 미지정(--bucket 또는 AWS_S3_BUCKET)")
    if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        raise PublishError("AWS 자격증명 없음(.env 의 AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)")

    prefix = args.s3_prefix.strip("/")
    prefix = f"{prefix}/" if prefix else ""
    manifest_path = os.path.join(args.incoming, args.manifest)
    if not os.path.isfile(manifest_path):
        raise PublishError(f"manifest 가 없습니다: {manifest_path}")
    m = parse_manifest(manifest_path, args)
    apk_name = args.apk or m.get("apkFileName") or "app-release.apk"
    apk_path = os.path.join(args.incoming, apk_name)
    digest, size, data = validate_apk(apk_path, m, args.expected_package)
    log(f"APK OK name={apk_name} size={size} sha256={digest} package={m['packageName']} "
        f"versionCode={m['versionCode']} versionName={m['versionName']}")

    import boto3
    s3 = boto3.client("s3", region_name=region)

    versioned_apk_key = f"{prefix}releases/StudyBridge-{m['versionName']}.apk"
    versioned_json_key = f"{prefix}releases/StudyBridge-{m['versionName']}.json"
    latest_apk_key = f"{prefix}latest/{LATEST_APK_NAME}"
    latest_json_key = f"{prefix}latest/version.json"

    current = s3_get_json(s3, bucket, latest_json_key)
    if current:
        log(f"현재 latest: versionCode={current.get('versionCode')} versionName={current.get('versionName')}")
        cur_code = int(current.get("versionCode") or 0)
        same_rerun = (m["versionCode"] == cur_code and current.get("sha256") == digest)
        if m["versionCode"] < cur_code or (m["versionCode"] == cur_code and not same_rerun):
            raise PublishError(f"versionCode 는 증가해야 합니다: new={m['versionCode']} current={cur_code} (동일 버전 다른 파일 금지)")
        if same_rerun and not args.allow_same_version:
            raise PublishError("동일 versionCode·동일 APK 가 이미 latest 입니다(재실행하려면 --allow-same-version)")
    else:
        log("현재 latest 없음(첫 릴리즈)")

    existing = s3_head(s3, bucket, versioned_apk_key)
    skip_versioned_upload = False
    if existing:
        ex_sha = (existing.get("Metadata") or {}).get("sha256")
        if ex_sha == digest and existing.get("ContentLength") == size:
            log(f"버전 고정 APK 이미 존재(동일 sha256) → 업로드 생략: {versioned_apk_key}")
            skip_versioned_upload = True
        else:
            raise PublishError(f"버전 고정 APK 가 이미 존재하며 내용이 다릅니다(불변 위반): {versioned_apk_key}")

    if args.min_supported_version_code is not None:
        min_supported = args.min_supported_version_code
    elif m.get("minimumSupportedVersionCode"):
        min_supported = int(m["minimumSupportedVersionCode"])
    elif current and current.get("minimumSupportedVersionCode"):
        min_supported = int(current["minimumSupportedVersionCode"])
    else:
        min_supported = 1
    if min_supported < 1 or min_supported > m["versionCode"]:
        raise PublishError(f"minimumSupportedVersionCode={min_supported} 는 1..{m['versionCode']} 범위여야 합니다")

    metadata = build_metadata(m, args, min_supported)
    meta_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    obj_meta = {"sha256": digest, "versioncode": str(m["versionCode"]), "versionname": m["versionName"],
                "package": m["packageName"]}

    plan = [
        f"1 PUT  s3://{bucket}/{versioned_apk_key} (immutable, 1y)" + (" [skip: exists]" if skip_versioned_upload else ""),
        f"2 HEAD s3://{bucket}/{versioned_apk_key}",
        f"3 PUT  s3://{bucket}/{versioned_json_key}",
        f"4 COPY → s3://{bucket}/{latest_apk_key} (no-cache)",
        f"5 HEAD s3://{bucket}/{latest_apk_key}",
        f"6 PUT  s3://{bucket}/{latest_json_key} (no-store, LAST)",
    ]
    for p in plan:
        log(("PLAN " if args.dry_run else "STEP ") + p)
    if args.dry_run:
        print(json.dumps({"dryRun": True, "metadata": metadata, "plan": plan}, ensure_ascii=False, indent=2))
        return 0

    if not skip_versioned_upload:
        s3.put_object(Bucket=bucket, Key=versioned_apk_key, Body=data, ContentType=APK_CONTENT_TYPE,
                      ContentMD5=md5_b64(data), CacheControl="public, max-age=31536000, immutable",
                      ContentDisposition=f'attachment; filename="StudyBridge-{m["versionName"]}.apk"', Metadata=obj_meta)
    head = s3_head(s3, bucket, versioned_apk_key)
    if not head or head.get("ContentLength") != size or (head.get("Metadata") or {}).get("sha256") != digest:
        raise PublishError("버전 고정 APK HEAD 검증 실패(크기/sha256 메타 불일치)")
    log(f"versioned OK {versioned_apk_key} bytes={head['ContentLength']}")

    s3.put_object(Bucket=bucket, Key=versioned_json_key, Body=meta_bytes, ContentType="application/json; charset=utf-8",
                  CacheControl="public, max-age=300")
    log(f"versioned manifest OK {versioned_json_key}")

    s3.copy_object(Bucket=bucket, Key=latest_apk_key, CopySource={"Bucket": bucket, "Key": versioned_apk_key},
                   MetadataDirective="REPLACE", ContentType=APK_CONTENT_TYPE,
                   CacheControl="no-cache, max-age=0, must-revalidate",
                   ContentDisposition=f'attachment; filename="StudyBridge-{m["versionName"]}.apk"', Metadata=obj_meta)
    head = s3_head(s3, bucket, latest_apk_key)
    if not head or head.get("ContentLength") != size or (head.get("Metadata") or {}).get("sha256") != digest:
        raise PublishError("latest APK HEAD 검증 실패 — version.json 은 갱신하지 않았습니다(이전 버전 유지)")
    log(f"latest OK {latest_apk_key} bytes={head['ContentLength']}")

    s3.put_object(Bucket=bucket, Key=latest_json_key, Body=meta_bytes, ContentType="application/json; charset=utf-8",
                  CacheControl="no-store, max-age=0")
    log(f"metadata OK {latest_json_key} (LAST)")

    if args.record_dir:
        try:
            os.makedirs(args.record_dir, exist_ok=True)
            rec = os.path.join(args.record_dir, f"StudyBridge-{m['versionName']}.json")
            with open(rec, "wb") as f:
                f.write(meta_bytes)
            shutil.copyfile(manifest_path, os.path.join(args.record_dir, f"StudyBridge-{m['versionName']}.manifest.json"))
            log(f"record {rec}")
        except OSError as e:
            log(f"WARN 기록 사본 저장 실패: {e}")

    if args.verify_public:
        verify_public(args, metadata)

    print(json.dumps({"published": True, "bucket": bucket, "versionedKey": versioned_apk_key, "latestKey": latest_apk_key,
                      "metadataKey": latest_json_key, "metadata": metadata}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PublishError as e:
        log(f"FAIL {e}")
        sys.exit(2)
