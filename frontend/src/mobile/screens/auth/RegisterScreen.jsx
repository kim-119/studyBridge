import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { authService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';

const PASSWORD_MIN_LENGTH = 8;

function validate({ email, password, passwordConfirm, displayName }) {
  const errors = {};

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
    errors.email = '올바른 이메일 형식이 아닙니다.';
  }

  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.password = '비밀번호는 8자 이상이어야 합니다.';
  }

  if (password !== passwordConfirm) {
    errors.passwordConfirm = '비밀번호가 일치하지 않습니다.';
  }

  if (!displayName.trim()) {
    errors.displayName = '이름을 입력해주세요.';
  }

  return errors;
}

export default function RegisterScreen() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    email: '',
    password: '',
    passwordConfirm: '',
    displayName: '',
    major: '',
  });
  const [errors, setErrors] = useState({});
  const [hasAgreed, setAgreed] = useState(false);

  const updateField = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const { submit, isSubmitting, errorMessage } = useSubmit(async () => {
    await authService.register({
      email: form.email.trim(),
      password: form.password,
      displayName: form.displayName.trim(),
      major: form.major.trim(),
    });
    navigate('/login', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();

    const validationErrors = validate(form);
    setErrors(validationErrors);

    if (Object.keys(validationErrors).length > 0) return;

    submit().catch(() => {});
  };

  return (
    <MobileScreen title="회원가입" showBackButton>
      <form onSubmit={handleSubmit}>
        <TextField
          label="이메일"
          type="email"
          inputMode="email"
          autoCapitalize="none"
          value={form.email}
          error={errors.email}
          onChange={updateField('email')}
        />

        <TextField
          label="비밀번호"
          type="password"
          value={form.password}
          hint="8자 이상 입력해주세요"
          error={errors.password}
          onChange={updateField('password')}
        />

        <TextField
          label="비밀번호 확인"
          type="password"
          value={form.passwordConfirm}
          error={errors.passwordConfirm}
          onChange={updateField('passwordConfirm')}
        />

        <TextField
          label="이름"
          value={form.displayName}
          error={errors.displayName}
          onChange={updateField('displayName')}
        />

        <TextField label="전공" value={form.major} hint="선택 입력" onChange={updateField('major')} />

        <label className="mobile-checkbox">
          <input
            type="checkbox"
            checked={hasAgreed}
            onChange={(event) => setAgreed(event.target.checked)}
          />
          <span>서비스 이용약관 및 개인정보 처리방침에 동의합니다. (필수)</span>
        </label>

        {errorMessage && <p className="mobile-auth__error">{errorMessage}</p>}

        <Button type="submit" fullWidth isLoading={isSubmitting} disabled={!hasAgreed}>
          가입하기
        </Button>
      </form>
    </MobileScreen>
  );
}
