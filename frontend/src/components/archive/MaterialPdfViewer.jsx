import React from 'react';
import { ExternalLink } from 'lucide-react';
import { useIsMobile } from '../../hooks/useIsMobile';

export default function MaterialPdfViewer({
  fileUrl,
  title = 'PDF 문서',
  missingTitle = 'PDF 미리보기를 표시할 수 없습니다.',
  missingMessage = '첨부된 PDF 파일이 없어 미리보기를 표시할 수 없습니다.',
}) {
  // 모바일 웹: Android Chrome 은 iframe/object 로 PDF 를 인라인 렌더하지 못해 58vh 짜리 빈 흰 박스만 보였다(MW10-6).
  //  · <object type="application/pdf"> 는 인라인 렌더가 불가능한 브라우저에서 자식(fallback) 을 그려 준다 → 안내 + '새 탭에서 열기'.
  //  · iOS Safari 는 object 안에 첫 페이지를 그리지만 스크롤이 안 되므로 상단에 '새 탭에서 열기' 를 항상 노출한다.
  //  · 데스크톱(>768px)은 기존 iframe 그대로(불변).
  const isMobile = useIsMobile();

  if (fileUrl) {
    if (isMobile) {
      return (
        <div className="pdf-viewer-mobile" style={{ width: '100%', height: '100%', backgroundColor: 'white', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '8px 10px', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>
            <span style={{ flex: '1 1 auto', fontSize: '13px', color: 'var(--color-text-muted)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
            <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="btn-outline" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 12px', fontSize: '13px', textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0 }}>
              <ExternalLink size={14} /> 새 탭에서 열기
            </a>
          </div>
          <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
            <object data={fileUrl} type="application/pdf" style={{ width: '100%', height: '100%', border: 'none', display: 'block' }} aria-label={title}>
              <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px', padding: '24px', textAlign: 'center', backgroundColor: '#F9FAFB' }}>
                <div style={{ padding: '18px 22px', backgroundColor: '#F3F4F6', borderRadius: '8px' }}>
                  <span style={{ fontSize: '28px', fontWeight: 800, color: '#9CA3AF' }}>PDF</span>
                </div>
                <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)', lineHeight: 1.6 }}>이 브라우저는 PDF 를 화면 안에서 바로 표시하지 못합니다.<br />새 탭에서 열어 확인하세요.</p>
                <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '10px 16px', fontSize: '14px', textDecoration: 'none', width: 'auto' }}>
                  <ExternalLink size={16} /> PDF 새 탭에서 열기
                </a>
              </div>
            </object>
          </div>
        </div>
      );
    }
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
