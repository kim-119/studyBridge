import React from 'react';
import { BookMarked } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ListRow from '../../components/ListRow';
import ScreenState from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { reviewNoteService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';

const DIFFICULTY_LABEL = {
  easy: '쉬움',
  medium: '보통',
  hard: '어려움',
};

export default function ReviewNotesScreen() {
  const navigate = useNavigate();
  const notes = useAsync(() => reviewNoteService.listReviewNotes(), []);

  return (
    <MobileScreen title="오답노트" showBackButton>
      <ScreenState
        query={notes}
        loadingLabel="오답노트를 불러오는 중입니다"
        emptyWhen={(value) => !value || value.length === 0}
        emptyMessage="아직 생성된 오답노트가 없습니다. 퀴즈를 풀면 자동으로 만들어집니다."
      >
        <ul className="mobile-list">
          {(notes.data || []).map((note) => (
            <li key={note.id}>
              <ListRow
                icon={<BookMarked size={20} />}
                title={note.title || note.sourceName}
                subtitle={[
                  `오답 ${note.wrongCount ?? 0}`,
                  `미응답 ${note.unansweredCount ?? 0}`,
                  DIFFICULTY_LABEL[note.difficulty] || note.difficulty,
                ]
                  .filter(Boolean)
                  .join(' · ')}
                meta={note.reviewNeeded ? '복습 필요' : undefined}
                onClick={() => navigate(`/review-notes/${note.id}`)}
              />
            </li>
          ))}
        </ul>
      </ScreenState>
    </MobileScreen>
  );
}
