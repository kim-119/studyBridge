import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';

const DEFAULT_CAPACITY = 10;

export default function GroupCreateScreen() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: '',
    hashtags: '',
    description: '',
    startDate: '',
    endDate: '',
    capacity: DEFAULT_CAPACITY,
  });
  const [isPublic, setPublic] = useState(true);

  const updateField = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const createGroup = useSubmit(async () => {
    const created = await groupService.createGroup({
      title: form.title.trim(),
      description: form.description.trim(),
      hashtags: form.hashtags.trim(),
      startDate: form.startDate || null,
      endDate: form.endDate || null,
      capacity: Number(form.capacity) || DEFAULT_CAPACITY,
      isPublic,
    });

    navigate(created?.id ? `/groupstudy/${created.id}` : '/groupstudy', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    createGroup.submit().catch(() => {});
  };

  return (
    <MobileScreen title="새 그룹스터디" showBackButton>
      <form onSubmit={handleSubmit}>
        <div className="mobile-segmented">
          <button
            type="button"
            className={isPublic ? 'is-active' : ''}
            onClick={() => setPublic(true)}
          >
            공개 스터디
          </button>
          <button
            type="button"
            className={!isPublic ? 'is-active' : ''}
            onClick={() => setPublic(false)}
          >
            비공개 스터디
          </button>
        </div>

        <p className="mobile-field__hint">
          {isPublic ? '누구나 검색하여 참여할 수 있습니다.' : '초대받은 사람만 참여할 수 있습니다.'}
        </p>

        <TextField
          label="스터디 이름"
          value={form.title}
          placeholder="예: 정보처리산업기사 함께 준비해요"
          onChange={updateField('title')}
        />

        <TextField
          label="태그"
          value={form.hashtags}
          hint="쉼표로 구분해 입력하세요"
          onChange={updateField('hashtags')}
        />

        <TextField label="시작일" type="date" value={form.startDate} onChange={updateField('startDate')} />
        <TextField label="종료일" type="date" value={form.endDate} onChange={updateField('endDate')} />

        <TextField
          label="정원"
          type="number"
          inputMode="numeric"
          min="2"
          max="50"
          value={form.capacity}
          onChange={updateField('capacity')}
        />

        <TextField
          as="textarea"
          label="스터디 소개"
          value={form.description}
          placeholder="스터디의 목적, 운영 방식, 규칙 등을 적어주세요"
          error={createGroup.errorMessage}
          onChange={updateField('description')}
        />

        <Button
          type="submit"
          fullWidth
          isLoading={createGroup.isSubmitting}
          disabled={!form.title.trim()}
        >
          스터디 만들기
        </Button>
      </form>
    </MobileScreen>
  );
}
