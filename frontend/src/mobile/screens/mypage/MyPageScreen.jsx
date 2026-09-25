import React, { useEffect, useState } from 'react';
import Button from '../../components/Button';
import SubTabs from '../../components/SubTabs';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { authService, inquiryService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useSubmit } from '../../data/useAsync';

const TABS = [
  { key: 'profile', label: '기본 프로필' },
  { key: 'security', label: '비밀번호/보안' },
  { key: 'inquiry', label: '1:1 문의' },
];

function ProfileTab() {
  const { user, userId, updateUser } = useAuth();
  const [form, setForm] = useState({ displayName: '', major: '', email: '' });

  useEffect(() => {
    setForm({
      displayName: user?.displayName || '',
      major: user?.major || '',
      email: user?.email || '',
    });
  }, [user]);

  const updateField = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const saveProfile = useSubmit(async () => {
    const updated = await authService.updateProfile(userId, {
      displayName: form.displayName.trim(),
      major: form.major.trim(),
      email: form.email.trim(),
    });
    updateUser(updated);
  });

  return (
    <section>
      <TextField label="이름" value={form.displayName} onChange={updateField('displayName')} />
      <TextField label="전공" value={form.major} onChange={updateField('major')} />
      <TextField
        label="이메일"
        type="email"
        value={form.email}
        error={saveProfile.errorMessage}
        onChange={updateField('email')}
      />

      <Button fullWidth isLoading={saveProfile.isSubmitting} onClick={() => saveProfile.submit().catch(() => {})}>
        프로필 수정
      </Button>
    </section>
  );
}

function SecurityTab() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  const [mismatch, setMismatch] = useState(null);

  const changePassword = useSubmit(async () => {
    await authService.updatePassword({ currentPassword, newPassword, newPasswordConfirm });
    setCurrentPassword('');
    setNewPassword('');
    setNewPasswordConfirm('');
  });

  const handleSubmit = () => {
    if (newPassword !== newPasswordConfirm) {
      setMismatch('새 비밀번호가 일치하지 않습니다.');
      return;
    }

    setMismatch(null);
    changePassword.submit().catch(() => {});
  };

  return (
    <section>
      <TextField
        label="현재 비밀번호"
        type="password"
        value={currentPassword}
        onChange={(event) => setCurrentPassword(event.target.value)}
      />
      <TextField
        label="새 비밀번호"
        type="password"
        value={newPassword}
        onChange={(event) => setNewPassword(event.target.value)}
      />
      <TextField
        label="새 비밀번호 확인"
        type="password"
        value={newPasswordConfirm}
        error={mismatch || changePassword.errorMessage}
        onChange={(event) => setNewPasswordConfirm(event.target.value)}
      />

      <Button
        fullWidth
        isLoading={changePassword.isSubmitting}
        disabled={!currentPassword || !newPassword}
        onClick={handleSubmit}
      >
        비밀번호 변경
      </Button>
    </section>
  );
}

function InquiryTab() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [isSent, setSent] = useState(false);

  const submitInquiry = useSubmit(async () => {
    await inquiryService.submitInquiry({ title: title.trim(), content: content.trim() });
    setTitle('');
    setContent('');
    setSent(true);
  });

  return (
    <section>
      <TextField label="제목" value={title} onChange={(event) => setTitle(event.target.value)} />
      <TextField
        as="textarea"
        label="문의 내용"
        value={content}
        error={submitInquiry.errorMessage}
        onChange={(event) => setContent(event.target.value)}
      />

      <Button
        fullWidth
        isLoading={submitInquiry.isSubmitting}
        disabled={!title.trim() || !content.trim()}
        onClick={() => submitInquiry.submit().catch(() => {})}
      >
        {isSent ? '접수되었습니다' : '문의 보내기'}
      </Button>
    </section>
  );
}

export default function MyPageScreen() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState(TABS[0].key);

  return (
    <MobileScreen title="계정" showBackButton>
      <section className="mobile-profile-card">
        <span className="mobile-profile-card__avatar">
          {user?.photoUrl ? <img src={user.photoUrl} alt="" /> : null}
        </span>

        <span className="mobile-profile-card__body">
          <strong>{user?.displayName || '학습자'}</strong>
          <span>{user?.major || '전공 미설정'}</span>
          <span>{user?.email}</span>
        </span>
      </section>

      <SubTabs tabs={TABS} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === 'profile' && <ProfileTab />}
      {activeTab === 'security' && <SecurityTab />}
      {activeTab === 'inquiry' && <InquiryTab />}
    </MobileScreen>
  );
}
