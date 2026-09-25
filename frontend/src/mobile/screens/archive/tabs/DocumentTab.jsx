import React from 'react';
import { FileText } from 'lucide-react';
import Button from '../../../components/Button';
import { EmptyState } from '../../../components/ScreenState';
import { openExternalUrl } from '../../../platform/externalLink';

const EXTRACTION_LABEL = {
  PENDING: '텍스트 추출 대기 중',
  RUNNING: '텍스트 추출 중',
  SUCCESS: '텍스트 추출 완료',
  FAILED: '텍스트 추출 실패',
};

export default function DocumentTab({ material }) {
  if (!material?.s3PresignedUrl) {
    return <EmptyState message="이 자료에는 열람할 수 있는 문서 파일이 없습니다." />;
  }

  return (
    <section className="mobile-card">
      <p className="mobile-card__meta">
        <FileText size={16} />
        {material.originalFileName || material.title}
      </p>

      {material.extractionStatus && (
        <p className="mobile-card__meta">{EXTRACTION_LABEL[material.extractionStatus] || material.extractionStatus}</p>
      )}

      <Button fullWidth onClick={() => openExternalUrl(material.s3PresignedUrl)}>
        문서 열기
      </Button>
    </section>
  );
}
