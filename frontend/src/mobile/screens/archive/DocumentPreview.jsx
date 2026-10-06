import React from 'react';
import { ExternalLink, FileText } from 'lucide-react';
import Button from '../../components/Button';
import PdfDocumentViewer from '../../components/PdfDocumentViewer';
import { useSubmit } from '../../data/useAsync';
import { openExternalUrl } from '../../platform/externalLink';
import { formatDate } from './archiveDomain';
import { isDocxMaterial } from './archiveNavigation';

function DocxNotice({ material, onRefreshUrl }) {
  const openDocument = useSubmit(async () => {
    const freshUrl = await onRefreshUrl();
    await openExternalUrl(freshUrl || material.s3PresignedUrl);
  });

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">
        <FileText size={16} />
        DOCX 문서
      </p>
      <p className="mobile-paragraph">{material.originalFileName || material.title}</p>
      <p className="mobile-card__meta mobile-archive-gap">업로드일 {formatDate(material.uploadedAt) || '-'}</p>
      <p className="mobile-state__text">
        워드(.docx) 문서는 미리보기를 제공하지 않습니다. AI 요약·퀴즈·로드맵·메모·AI 질문은 아래 탭에서 확인하세요.
      </p>

      {material.s3PresignedUrl && (
        <Button
          fullWidth
          variant="secondary"
          isLoading={openDocument.isSubmitting}
          onClick={() => openDocument.submit().catch(() => {})}
        >
          <ExternalLink size={16} />
          외부 앱으로 열기
        </Button>
      )}
      {openDocument.errorMessage && <p className="mobile-auth__error mobile-archive-gap">{openDocument.errorMessage}</p>}
    </section>
  );
}

export default function DocumentPreview({ material, onRefreshUrl }) {
  if (isDocxMaterial(material)) return <DocxNotice material={material} onRefreshUrl={onRefreshUrl} />;

  if (!material.s3PresignedUrl) {
    return <p className="mobile-notice mobile-section">첨부된 PDF 파일이 없어 미리보기를 표시할 수 없습니다.</p>;
  }

  return <PdfDocumentViewer url={material.s3PresignedUrl} title={material.title} onRefreshUrl={onRefreshUrl} />;
}
