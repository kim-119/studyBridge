import React, { useEffect, useRef, useState } from 'react';
import { Camera, UserRound } from 'lucide-react';
import Button from '../../components/Button';
import SubTabs from '../../components/SubTabs';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { authService, inquiryService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import ScreenState from '../../components/ScreenState';

const TABS = [
  { key: 'profile', label: '기본 프로필' },
  { key: 'security', label: '비밀번호/보안' },
  { key: 'inquiry', label: '1:1 문의' },
];

function ProfileTab() {
  const { user, userId, updateUser } = useAuth();
  const imageInput = useRef(null);
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

  const uploadImage = useSubmit(async (file) => {
    const updated = await authService.uploadProfileImage(file);
    updateUser(updated);
  });

  const handleImageSelected = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) uploadImage.submit(file).catch(() => {});
  };

  return (
    <section>
      <div className="mobile-avatar-edit">
        <span className="mobile-profile-card__avatar">
          {user?.photoUrl ? <img src={user.photoUrl} alt="" /> : <UserRound size={24} />}
        </span>

        <Button
          variant="secondary"
          isLoading={uploadImage.isSubmitting}
          onClick={() => imageInput.current?.click()}
        >
          <Camera size={16} />
          프로필 사진 변경
        </Button>

        <input ref={imageInput} type="file" accept="image/*" hidden onChange={handleImageSelected} />
      </div>

      {uploadImage.errorMessage && <p className="mobile-auth__error">{uploadImage.errorMessage}</p>}

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

  const history = useAsync(() => inquiryService.getInquiries(), []);

  const submitInquiry = useSubmit(async () => {
    await inquiryService.submitInquiry({ title: title.trim(), content: content.trim() });
    setTitle('');
    setContent('');
    setSent(true);
    await history.reload();
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

      <section className="mobile-section">
        <h3 className="mobile-section__title">문의 내역</h3>

        <ScreenState
          query={history}
          loadingLabel="문의 내역을 불러오는 중입니다"
          emptyWhen={(value) => !value || value.length === 0}
          emptyMessage="접수한 문의가 없습니다."
        >
          <ul className="mobile-list">
            {(history.data || []).map((inquiry) => (
              <li key={inquiry.id ?? inquiry.inquiryId} className="mobile-card">
                <p className="mobile-card__meta">
                  {[String(inquiry.createdAt || '').slice(0, 10), inquiry.status || inquiry.answerStatus]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                <p className="mobile-qa__question">{inquiry.title}</p>
                <p className="mobile-paragraph">{inquiry.content}</p>
                {inquiry.reply && (
                  <p className="mobile-quiz__explanation">답변 · {inquiry.reply}</p>
                )}
              </li>
            ))}
          </ul>
        </ScreenState>
      </section>
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
