import React, { useState } from 'react';
import { Eye, EyeOff, ExternalLink, FileText } from 'lucide-react';
import Button from '../../components/Button';
import PdfDocumentViewer from '../../components/PdfDocumentViewer';
import { useSubmit } from '../../data/useAsync';
import { openExternalUrl } from '../../platform/externalLink';

export default function KnowledgePdfAttachment({ url, title, onRefreshUrl }) {
  const [isPreviewing, setPreviewing] = useState(false);

  const openExternally = useSubmit(async () => {
    const freshUrl = await onRefreshUrl();
    await openExternalUrl(freshUrl || url);
  });

  if (!url) return null;

  return (
    <section className="knowledge-pdf" aria-label="첨부 PDF">
      <p className="knowledge-pdf__name">
        <FileText size={18} />
        첨부 PDF
      </p>

      <div className="mobile-card__actions">
        <Button variant="secondary" onClick={() => setPreviewing((current) => !current)}>
          {isPreviewing ? <EyeOff size={16} /> : <Eye size={16} />}
          {isPreviewing ? '미리보기 닫기' : 'PDF 미리보기'}
        </Button>
        <Button
          variant="action"
          isLoading={openExternally.isSubmitting}
          onClick={() => openExternally.submit().catch(() => {})}
        >
          <ExternalLink size={16} />
          외부 앱으로 열기
        </Button>
      </div>

      {openExternally.errorMessage && <p className="mobile-auth__error">{openExternally.errorMessage}</p>}
      {isPreviewing && <PdfDocumentViewer url={url} title={title} onRefreshUrl={onRefreshUrl} />}
    </section>
  );
}
