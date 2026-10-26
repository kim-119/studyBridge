import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { authService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import {
  EMPTY_REGISTER_FORM,
  buildRegisterPayload,
  validateRegisterForm,
} from './registerForm';

export default function RegisterScreen() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY_REGISTER_FORM);
  const [errors, setErrors] = useState({});
  const [hasAgreed, setAgreed] = useState(false);

  const updateField = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const { submit, isSubmitting, errorMessage, clearError } = useSubmit(async () => {
    await authService.register(buildRegisterPayload(form));
    navigate('/login', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    clearError();

    const validationErrors = validateRegisterForm(form);
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
          hint="영문, 숫자, 특수문자 포함 8~16자"
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
          label="닉네임"
          hint="2~10자"
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
