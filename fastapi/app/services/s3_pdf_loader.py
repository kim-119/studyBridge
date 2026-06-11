"""
S3 PDF/파일 로더.

AWS 자격증명 우선순위:
  1. IAM Role / EC2 Task Role (환경변수 미설정 시 boto3가 자동 사용)
  2. 환경변수 AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (로컬 개발용)
  3. 둘 다 없으면 RuntimeError → fallback 반환

키/버킷 이름은 로그에 최소한으로 출력한다.
S3 실패가 FastAPI 서버 전체를 죽이지 않도록 예외를 caller에게 RuntimeError로만 전달한다.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_s3_client(bucket: Optional[str] = None):
    """
    boto3 S3 클라이언트를 반환한다.
    IAM Role이 설정된 환경(EC2, ECS Task Role)에서는 자격증명을 명시하지 않아도 된다.
    """
    from app.core.config import (
        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET,
    )

    _bucket = bucket or AWS_S3_BUCKET
    if not _bucket:
        raise RuntimeError("AWS_S3_BUCKET 환경변수가 설정되지 않았습니다.")

    try:
        import boto3
    except ImportError:
        raise RuntimeError("boto3가 설치되지 않았습니다: pip install boto3")

    # IAM Role 우선: 자격증명 명시 없이 boto3가 알아서 처리한다.
    # 로컬 개발: .env에 AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY 설정.
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )
    else:
        # IAM Role / EC2 Instance Profile / ECS Task Role 사용
        client = boto3.client("s3", region_name=AWS_REGION)

    return client, _bucket


def load_pdf_bytes_from_s3(s3_key: str, bucket: Optional[str] = None) -> bytes:
    """
    S3에서 PDF bytes를 로드한다.

    Args:
        s3_key: S3 오브젝트 키 (예: materials/user_42/file.pdf)
        bucket: S3 버킷명 (None이면 AWS_S3_BUCKET 환경변수 사용)

    Returns:
        PDF raw bytes

    Raises:
        RuntimeError: AWS 미설정, S3 접근 실패 등
    """
    if not s3_key or not s3_key.strip():
        raise RuntimeError("s3_key가 비어 있습니다.")

    try:
        s3_client, _bucket = _get_s3_client(bucket)
        response = s3_client.get_object(Bucket=_bucket, Key=s3_key)
        pdf_bytes = response["Body"].read()
        logger.info("S3 PDF 로드 완료: key=...%s (%d bytes)", s3_key[-20:], len(pdf_bytes))
        return pdf_bytes
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("S3 접근 실패: %s", type(e).__name__)
        raise RuntimeError(f"S3에서 PDF를 로드할 수 없습니다: {type(e).__name__}") from e


def load_text_from_s3_pdf(s3_key: str, file_name: str = "", bucket: Optional[str] = None) -> str:
    """
    S3 PDF를 로드하고 텍스트를 추출하여 반환한다.

    Args:
        s3_key:    S3 오브젝트 키
        file_name: 원본 파일명 (로깅용)
        bucket:    S3 버킷명 (None이면 환경변수 사용)

    Returns:
        추출된 텍스트 문자열 (추출 실패 시 빈 문자열)

    Raises:
        RuntimeError: S3 접근 실패
    """
    pdf_bytes = load_pdf_bytes_from_s3(s3_key, bucket)

    best = ""
    try:
        import fitz  # PyMuPDF
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            best = "\n".join(page.get_text() for page in doc)
    except ImportError:
        logger.warning("PyMuPDF(fitz) 없음. pypdf로 fallback.")
    except Exception as e:
        logger.warning("PDF 텍스트 추출 실패 (fitz): %s", e)

    if len(best.strip()) < 50:
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pypdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if len(pypdf_text.strip()) > len(best.strip()):
                best = pypdf_text
        except Exception as e2:
            logger.warning("PDF 텍스트 추출 실패 (pypdf): %s", e2)

    if len(best.strip()) < 50:
        try:
            from app.services.ocr_service import extract_pdf_ocr_from_bytes
            ocr = extract_pdf_ocr_from_bytes(pdf_bytes, min_chars=50)
            if len((ocr.text or "").strip()) > len(best.strip()):
                best = ocr.text
            logger.info("S3 PDF OCR fallback attempted file=%s engine=%s chars=%s reason=%s", file_name, ocr.engine, len(ocr.text or ""), ocr.reason)
        except Exception as e3:
            logger.warning("S3 PDF OCR fallback exception: %s", e3)

    if len(best.strip()) < 50:
        logger.warning("PDF 텍스트가 너무 짧습니다 (%d자): %s", len(best.strip()), file_name)
    return best


def is_aws_configured() -> bool:
    """AWS S3 사용 가능 여부 (IAM Role 환경은 버킷만 있으면 가능)."""
    from app.core.config import AWS_S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
    # 버킷 설정만 있으면 IAM Role로 동작 가능
    return bool(AWS_S3_BUCKET)


# 하위 호환 alias
load_pdf_from_s3 = load_pdf_bytes_from_s3
