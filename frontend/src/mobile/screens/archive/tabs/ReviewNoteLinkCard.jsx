import React, { useMemo } from 'react';
import { BookMarked } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ListRow from '../../../components/ListRow';
import { reviewNoteService } from '../../../../services/api';
import { useAsync } from '../../../data/useAsync';

/**
 * 이 자료에서 파생된 오답노트를 상세 화면에 연결한다.
 * ReviewNoteDTO.sourceMaterialId / archiveMaterialId 가 자료 id 와 일치하는 항목을 고른다.
 */
export default function ReviewNoteLinkCard({ materialId }) {
  const navigate = useNavigate();
  const notes = useAsync(() => reviewNoteService.listReviewNotes(), []);

  const linked = useMemo(() => {
    const list = Array.isArray(notes.data) ? notes.data : [];
    const target = String(materialId);

    return list.filter(
      (note) =>
        String(note.sourceMaterialId ?? '') === target ||
        String(note.archiveMaterialId ?? '') === target
    );
  }, [notes.data, materialId]);

  if (notes.isLoading || linked.length === 0) return null;

  return (
    <section className="mobile-section">
      <h3 className="mobile-section__title">이 자료의 오답노트</h3>

      <ul className="mobile-list">
        {linked.map((note) => (
          <li key={note.id}>
            <ListRow
              icon={<BookMarked size={20} />}
              title={note.title || note.sourceName}
              subtitle={`오답 ${note.wrongCount ?? 0} · 미응답 ${note.unansweredCount ?? 0}`}
              meta={note.reviewNeeded ? '복습 필요' : undefined}
              onClick={() => navigate(`/review-notes/${note.id}`)}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
