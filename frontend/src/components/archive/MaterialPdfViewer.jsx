import React from 'react';

export default function MaterialPdfViewer({
  fileUrl,
  title = 'PDF 문서',
  missingTitle = 'PDF 미리보기를 표시할 수 없습니다.',
  missingMessage = '첨부된 PDF 파일이 없어 미리보기를 표시할 수 없습니다.',
}) {
  if (fileUrl) {
    return (
      <div style={{ width: '100%', height: '100%', backgroundColor: 'white', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ flex: 1, position: 'relative' }}>
          <iframe src={fileUrl} style={{ width: '100%', height: '100%', border: 'none' }} title={title} />
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', padding: '40px' }}>
      <div style={{ padding: '40px', backgroundColor: '#F3F4F6', borderRadius: '8px', marginBottom: '24px' }}>
        <span style={{ fontSize: '48px', color: '#9CA3AF' }}>PDF</span>
      </div>
      <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)', textAlign: 'center' }}>{missingTitle}</h3>
      <p style={{ color: 'var(--color-text-muted)', margin: 0, textAlign: 'center' }}>{missingMessage}</p>
    </div>
  );
}
