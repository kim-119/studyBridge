import React, { useCallback } from 'react';
import { X } from 'lucide-react';
import PdfDocumentViewer from '../../../components/PdfDocumentViewer';
import { ErrorState, LoadingState } from '../../../components/ScreenState';
import { groupService } from '../../../../services/api';
import { useAsync } from '../../../data/useAsync';
import { extractDownloadUrl } from '../../../platform/downloadUrl';

async function fetchMaterialUrl(materialId) {
  const url = extractDownloadUrl(await groupService.getGroupMaterialDownloadUrl(materialId));
  if (!url) throw new Error('자료 URL을 발급받지 못했습니다.');
  return url;
}

export default function MaterialViewer({ materialId, title, onClose }) {
  const download = useAsync(() => fetchMaterialUrl(materialId), [materialId]);
  const { setData } = download;

  const refreshUrl = useCallback(async () => {
    const url = await fetchMaterialUrl(materialId);
    setData(url);
    return url;
  }, [materialId, setData]);

  return (
    <div className="mobile-room-viewer" role="dialog" aria-label={title || '학습자료'}>
      <header className="mobile-room-panel__header">
        <h2 className="mobile-sheet__title">{title || '학습자료'}</h2>
        <button type="button" className="mobile-sheet__close" aria-label="닫기" onClick={onClose}>
          <X size={20} />
        </button>
      </header>

      <div className="mobile-room-viewer__body">
        {download.isLoading && !download.data && <LoadingState label="자료를 여는 중입니다" />}
        {download.isError && <ErrorState message={download.errorMessage} onRetry={download.reload} />}
        {download.data && <PdfDocumentViewer url={download.data} title={title} onRefreshUrl={refreshUrl} />}
      </div>
    </div>
  );
}
