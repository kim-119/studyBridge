import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react';
import Button from '../../../components/Button';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import TextField from '../../../components/TextField';
import { materialService } from '../../../../services/api';
import { describeApiError, useAsync, useSubmit } from '../../../data/useAsync';
import { formatDate } from '../archiveDomain';

const VALIDATION_REJECTED_STATUS = 422;

function rejectionOf(error) {
  if (error?.response?.status !== VALIDATION_REJECTED_STATUS) return null;
  const body = error.response.data || {};
  return {
    isBlocked: body.decision === 'BLOCK',
    reason: body.reason || 'PDF 학습 자료와 연결되는 개념이나 질문이 부족합니다.',
    suggestion: body.suggestion || '',
  };
}

function SaveFeedback({ error }) {
  if (!error) return null;

  const rejection = rejectionOf(error);
  if (!rejection) return <p className="mobile-auth__error">{describeApiError(error)}</p>;

  return (
    <div className="mobile-auth__error" role="alert">
      <strong>{rejection.isBlocked ? '저장할 수 없는 메모입니다.' : '메모를 보완해주세요.'}</strong>
      <p className="mobile-archive-text">{rejection.reason}</p>
      {rejection.suggestion && <p className="mobile-archive-text">제안: {rejection.suggestion}</p>}
    </div>
  );
}

function JournalItem({ materialId, journal, onDeleted }) {
  const [isExpanded, setExpanded] = useState(false);
  const [isConfirmingDelete, setConfirmingDelete] = useState(false);

  const detail = useAsync(
    () => materialService.getStudyJournal(materialId, journal.id),
    [materialId, journal.id],
    { immediate: isExpanded }
  );

  const removeJournal = useSubmit(async () => {
    await materialService.deleteStudyJournal(materialId, journal.id);
    await onDeleted();
  });

  return (
    <li className="mobile-card">
      <button
        type="button"
        className="mobile-card__header-link"
        aria-expanded={isExpanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="mobile-card__meta">
          {[formatDate(journal.createdAt), journal.relationType].filter(Boolean).join(' · ') || '메모'}
        </span>
        {isExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>

      {journal.relationPath && <p className="mobile-card__meta">{journal.relationPath}</p>}

      {isExpanded && (
        <ScreenState query={detail} loadingLabel="메모를 불러오는 중입니다">
          <p className="mobile-paragraph">{detail.data?.content || ''}</p>
        </ScreenState>
      )}

      <div className="mobile-card__actions">
        {isConfirmingDelete ? (
          <>
            <Button
              variant="danger"
              isLoading={removeJournal.isSubmitting}
              onClick={() => removeJournal.submit().catch(() => {})}
            >
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

      {removeJournal.errorMessage && <p className="mobile-auth__error mobile-archive-gap">{removeJournal.errorMessage}</p>}
    </li>
  );
}

function journalLogContent(material, memo) {
  return [`자료 제목: ${material.title || material.originalFileName || '자료'}`, `원문 보기: /archive/${material.materialId}`, '', memo].join('\n');
}

export default function MemoTab({ material }) {
  const materialId = material.materialId;
  const journals = useAsync(() => materialService.listStudyJournals(materialId), [materialId]);
  const [content, setContent] = useState('');
  const [isSavedToLog, setSavedToLog] = useState(false);

  const saveMemo = useSubmit(async () => {
    await materialService.createStudyJournal(materialId, content.trim());
    setContent('');
    await journals.reload();
  });

  const saveToStudyLog = useSubmit(async () => {
    await materialService.createStudyLog({
      title: `${material.title || '자료'} 학습일지`,
      keywords: '',
      studyDate: new Date().toISOString().split('T')[0],
      learningContent: journalLogContent(material, content.trim()),
      nextPlan: '',
    });
    setSavedToLog(true);
  });

  const list = Array.isArray(journals.data) ? journals.data : [];
  const hasContent = content.trim().length > 0;

  return (
    <section>
      <TextField
        as="textarea"
        label="메모"
        value={content}
        placeholder="이 자료에서 배운 개념이나 궁금한 점을 남겨보세요"
        onChange={(event) => {
          setContent(event.target.value);
          setSavedToLog(false);
        }}
      />

      <SaveFeedback error={saveMemo.error} />

      <div className="mobile-archive-stack mobile-section">
        <Button
          fullWidth
          isLoading={saveMemo.isSubmitting}
          disabled={!hasContent}
          onClick={() => saveMemo.submit().catch(() => {})}
        >
          메모 저장
        </Button>
        <Button
          fullWidth
          variant="secondary"
          isLoading={saveToStudyLog.isSubmitting}
          disabled={!hasContent || isSavedToLog}
          onClick={() => saveToStudyLog.submit().catch(() => {})}
        >
          {isSavedToLog ? '학습일지에 저장됨' : '학습일지로 저장'}
        </Button>
        {saveToStudyLog.errorMessage && <p className="mobile-auth__error">{saveToStudyLog.errorMessage}</p>}
      </div>

      <h3 className="mobile-section__title">저장된 메모</h3>
      <ScreenState query={journals} loadingLabel="메모 목록을 불러오는 중입니다">
        {list.length === 0 ? (
          <EmptyState message="아직 저장된 메모가 없습니다." />
        ) : (
          <ul className="mobile-list">
            {list.map((journal) => (
              <JournalItem key={journal.id} materialId={materialId} journal={journal} onDeleted={journals.reload} />
            ))}
          </ul>
        )}
      </ScreenState>
    </section>
  );
}
