"""
PDF bytes에서 텍스트를 추출하는 서비스.
PyMuPDF(fitz) 우선, 실패 시 pypdf fallback.
"""
import logging
from typing import Optional

from app.services.ocr_service import extract_pdf_ocr_from_bytes, should_attempt_ocr

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 50


def extract_text_from_bytes(pdf_bytes: bytes) -> str:
    """
    PDF bytes에서 텍스트를 추출한다.

    Args:
        pdf_bytes: PDF 파일의 raw bytes

    Returns:
        추출된 텍스트 문자열

    Raises:
        RuntimeError: 텍스트 추출 완전 실패 시
    """
    text = _try_pymupdf(pdf_bytes)
    if text and len(text.strip()) >= _MIN_TEXT_LENGTH:
        logger.info("PyMuPDF로 텍스트 추출 완료 (%d자)", len(text))
        return text.strip()

    logger.warning("PyMuPDF 추출 결과 부족, pypdf로 fallback합니다.")
    text = _try_pypdf(pdf_bytes)
    if text and len(text.strip()) >= _MIN_TEXT_LENGTH:
        logger.info("pypdf로 텍스트 추출 완료 (%d자)", len(text))
        return text.strip()

    best = (text or "").strip()
    if should_attempt_ocr(best, _MIN_TEXT_LENGTH):
        ocr = extract_pdf_ocr_from_bytes(pdf_bytes, min_chars=_MIN_TEXT_LENGTH)
        if ocr.text and len(ocr.text.strip()) >= _MIN_TEXT_LENGTH:
            logger.info("OCR로 텍스트 추출 완료 (%d자)", len(ocr.text))
            return ocr.text.strip()
        logger.warning("OCR fallback 실패/부족: engine=%s reason=%s chars=%s", ocr.engine, ocr.reason, len(ocr.text or ""))

    if best:
        logger.warning("텍스트가 너무 짧습니다 (%d자). 이미지 PDF일 수 있습니다.", len(best))
        return best

    raise RuntimeError(
        "PDF에서 텍스트를 추출할 수 없습니다. "
        "이미지 기반 PDF이거나 암호화된 파일일 수 있습니다."
    )


def _try_pymupdf(pdf_bytes: bytes) -> Optional[str]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    except ImportError:
        logger.debug("PyMuPDF(fitz)가 설치되지 않았습니다.")
        return None
    except Exception as e:
        logger.warning("PyMuPDF 텍스트 추출 실패: %s", e)
        return None


def _try_pypdf(pdf_bytes: bytes) -> Optional[str]:
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except ImportError:
        logger.debug("pypdf가 설치되지 않았습니다.")
        return None
    except Exception as e:
        logger.warning("pypdf 텍스트 추출 실패: %s", e)
        return None


def is_text_sufficient(text: str, min_length: int = _MIN_TEXT_LENGTH) -> bool:
    """텍스트가 퀴즈 생성에 충분한지 확인한다."""
    return len(text.strip()) >= min_length
