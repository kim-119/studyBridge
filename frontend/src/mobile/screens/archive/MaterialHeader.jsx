import React, { useState } from 'react';
import { Trash2 } from 'lucide-react';
import Button from '../../components/Button';
import { formatDate, formatFileSize } from './archiveDomain';
import { MATERIAL_KIND } from './archiveNavigation';

const KIND_LABEL = {
  [MATERIAL_KIND.DOCUMENT]: '학습자료',
  [MATERIAL_KIND.PLANNER]: '플래너',
  [MATERIAL_KIND.STUDY_JOURNAL]: '학습일지',
  [MATERIAL_KIND.MINDMAP]: '마인드맵',
  [MATERIAL_KIND.REVIEW_NOTE]: '오답노트',
};

function keywordsOf(material) {
  const raw = Array.isArray(material.keywords) ? material.keywords : String(material.keywords || '').split(',');
  return [...new Set(raw.map((keyword) => String(keyword).trim()).filter(Boolean))];
}

export default function MaterialHeader({ material, kind, isDeleting, deleteError, onDelete }) {
  const [isConfirmingDelete, setConfirmingDelete] = useState(false);
  const keywords = keywordsOf(material);
  const meta = [
    formatDate(material.studyDate || material.uploadedAt),
    formatFileSize(material.fileSize),
    KIND_LABEL[kind],
  ].filter(Boolean);

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">{meta.join(' · ')}</p>

      {keywords.length > 0 && (
        <ul className="mobile-chips">
          {keywords.map((keyword) => (
            <li key={keyword}>#{keyword}</li>
          ))}
        </ul>
      )}

      <div className="mobile-card__actions">
        {isConfirmingDelete ? (
          <>
            <Button variant="danger" isLoading={isDeleting} onClick={onDelete}>
              삭제 확인
            </Button>
            <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
              취소
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={() => setConfirmingDelete(true)}>
            <Trash2 size={16} />
            삭제
          </Button>
        )}
      </div>

      {isConfirmingDelete && !deleteError && (
        <p className="mobile-card__meta mobile-archive-gap">삭제한 자료는 복구할 수 없습니다.</p>
      )}
      {deleteError && <p className="mobile-auth__error mobile-archive-gap">{deleteError}</p>}
    </section>
  );
}
