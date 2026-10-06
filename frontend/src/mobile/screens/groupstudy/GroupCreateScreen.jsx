import React, { useState } from 'react';
import { Minus, Plus, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import CoverImagePicker, { INITIAL_COVER, resolveCoverUpload } from './CoverImagePicker';
import {
  CAPACITY_MAX,
  CAPACITY_MIN,
  DEFAULT_CAPACITY,
  DESCRIPTION_MAX_LENGTH,
  MAX_HASHTAGS,
  addHashtag,
  countStudyDays,
  defaultStudyPeriod,
  toCreatePayload,
  validateCreateForm,
} from './groupStudyModel';

function createInitialForm() {
  return {
    title: '',
    tags: [],
    description: '',
    capacity: DEFAULT_CAPACITY,
    isPublic: true,
    ...defaultStudyPeriod(new Date()),
  };
}

function VisibilitySection({ isPublic, onChange }) {
  return (
    <section className="mobile-card mobile-section">
      <h2 className="mobile-section__title">공개 설정</h2>
      <div className="mobile-segmented">
        <button type="button" className={isPublic ? 'is-active' : ''} onClick={() => onChange(true)}>
          공개 스터디
        </button>
        <button type="button" className={!isPublic ? 'is-active' : ''} onClick={() => onChange(false)}>
          비공개 스터디
        </button>
      </div>
      <p className="mobile-field__hint">
        {isPublic ? '누구나 검색하여 바로 참여할 수 있습니다.' : '방장의 승인을 받은 사람만 참여할 수 있습니다.'}
        {' '}공개 여부는 만든 후 변경할 수 없습니다.
      </p>
    </section>
  );
}

function TagInput({ tags, onChange }) {
  const [draft, setDraft] = useState('');

  const commitDraft = () => {
    onChange(addHashtag(tags, draft));
    setDraft('');
  };

  const handleKeyDown = (event) => {
    if (event.key !== 'Enter' && event.key !== ',') return;
    event.preventDefault();
    commitDraft();
  };

  return (
    <>
      {tags.length > 0 && (
        <ul className="mobile-chips">
          {tags.map((tag) => (
            <li key={tag} className="mobile-tag-chip">
              #{tag}
              <button type="button" aria-label={`${tag} 태그 삭제`} onClick={() => onChange(tags.filter((item) => item !== tag))}>
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <TextField
        label="태그"
        value={draft}
        placeholder="태그 입력 후 엔터"
        hint={`최대 ${MAX_HASHTAGS}개까지 입력할 수 있습니다.`}
        enterKeyHint="done"
        disabled={tags.length >= MAX_HASHTAGS}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={commitDraft}
      />
    </>
  );
}

function CapacityStepper({ value, error, onChange }) {
  const capacity = parseInt(value, 10) || CAPACITY_MIN;

  return (
    <div className="mobile-stepper">
      <span className="mobile-field__label">스터디 정원</span>
      <div className="mobile-stepper__controls">
        <button type="button" aria-label="정원 줄이기" disabled={capacity <= CAPACITY_MIN} onClick={() => onChange(capacity - 1)}>
          <Minus size={18} />
        </button>
        <span>{capacity}명</span>
        <button type="button" aria-label="정원 늘리기" disabled={capacity >= CAPACITY_MAX} onClick={() => onChange(capacity + 1)}>
          <Plus size={18} />
        </button>
      </div>
      {error ? (
        <p className="mobile-field__error">{error}</p>
      ) : (
        <p className="mobile-field__hint">최소 {CAPACITY_MIN}명 ~ 최대 {CAPACITY_MAX}명 (화상통화 안정 성능 보장)</p>
      )}
    </div>
  );
}

export default function GroupCreateScreen() {
  const navigate = useNavigate();
  const [form, setForm] = useState(createInitialForm);
  const [cover, setCover] = useState(INITIAL_COVER);
  const [errors, setErrors] = useState({});

  const setField = (field, value) => setForm((previous) => ({ ...previous, [field]: value }));
  const updateField = (field) => (event) => setField(field, event.target.value);
  const studyDays = countStudyDays(form.startDate, form.endDate);

  const createGroup = useSubmit(async () => {
    const image = await resolveCoverUpload(cover);
    const created = await groupService.createGroup(toCreatePayload(form, image));
    navigate(created?.id ? `/groupstudy/${created.id}` : '/groupstudy', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    const nextErrors = validateCreateForm(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    createGroup.submit().catch(() => {});
  };

  const serverMessage = createGroup.error?.response?.data?.message || createGroup.errorMessage;

  return (
    <MobileScreen title="새 그룹스터디 만들기" showBackButton>
      <p className="mobile-card__meta">함께 공부할 스터디 방을 간단히 만들어보세요.</p>

      <form onSubmit={handleSubmit} noValidate>
        <VisibilitySection isPublic={form.isPublic} onChange={(isPublic) => setField('isPublic', isPublic)} />

        <section className="mobile-card mobile-section">
          <TextField
            label="스터디 이름"
            value={form.title}
            placeholder="예: 수다하면서 공부하실 분"
            error={errors.title}
            onChange={updateField('title')}
          />
          <TagInput tags={form.tags} onChange={(tags) => setField('tags', tags)} />
        </section>

        <section className="mobile-card mobile-section">
          <h2 className="mobile-section__title">커버 이미지</h2>
          <CoverImagePicker cover={cover} onChange={setCover} />
        </section>

        <section className="mobile-card mobile-section">
          <h2 className="mobile-section__title">운영 기간</h2>
          <TextField label="시작일" type="date" value={form.startDate} onChange={updateField('startDate')} />
          <TextField
            label="종료일"
            type="date"
            value={form.endDate}
            min={form.startDate}
            error={errors.period}
            hint={studyDays ? `${studyDays}일 동안 스터디가 유지됩니다.` : undefined}
            onChange={updateField('endDate')}
          />
          <CapacityStepper value={form.capacity} error={errors.capacity} onChange={(value) => setField('capacity', value)} />
        </section>

        <section className="mobile-card mobile-section">
          <TextField
            as="textarea"
            label="스터디 소개"
            value={form.description}
            maxLength={DESCRIPTION_MAX_LENGTH}
            placeholder="스터디의 목적, 운영 방식, 규칙 등을 상세히 적어주세요."
            hint={`${form.description.length} / ${DESCRIPTION_MAX_LENGTH}`}
            error={errors.description}
            onChange={updateField('description')}
          />
        </section>

        {createGroup.error && <p className="mobile-auth__error">{serverMessage}</p>}

        <Button type="submit" fullWidth isLoading={createGroup.isSubmitting}>
          스터디 만들기
        </Button>
      </form>
    </MobileScreen>
  );
}
