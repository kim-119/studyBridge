import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import { authService } from '../../../services/api';
import { normalizeUser, useAuth } from '../../../hooks/useAuth';
import { useSubmit } from '../../data/useAsync';

export default function LoginScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isPasswordVisible, setPasswordVisible] = useState(false);

  const { submit, isSubmitting, errorMessage } = useSubmit(
    async () => {
      const response = await authService.login({ email: email.trim(), password });
      login(normalizeUser(response));
      navigate(location.state?.from || '/', { replace: true });
    },
    { errorMessages: { 401: '이메일 또는 비밀번호가 올바르지 않습니다.', 400: '이메일 또는 비밀번호가 올바르지 않습니다.' } }
  );

  const handleSubmit = (event) => {
    event.preventDefault();
    submit().catch(() => {});
  };

  const canSubmit = email.trim().length > 0 && password.length > 0;

  return (
    <main className="mobile-auth">
      <header className="mobile-auth__header">
        <span className="mobile-auth__brand">StudyBridge</span>
        <p className="mobile-auth__tagline">학습을 하나로 잇다</p>
      </header>

      <form className="mobile-auth__form" onSubmit={handleSubmit}>
        <TextField
          label="이메일"
          type="email"
          inputMode="email"
          autoComplete="username"
          autoCapitalize="none"
          value={email}
          placeholder="studybridge@example.com"
          onChange={(event) => setEmail(event.target.value)}
        />

        <div className="mobile-auth__password">
          <TextField
            label="비밀번호"
            type={isPasswordVisible ? 'text' : 'password'}
            autoComplete="current-password"
            value={password}
            placeholder="비밀번호를 입력하세요"
            onChange={(event) => setPassword(event.target.value)}
          />
          <button
            type="button"
            className="mobile-auth__reveal"
            aria-label={isPasswordVisible ? '비밀번호 숨기기' : '비밀번호 표시'}
            onClick={() => setPasswordVisible((visible) => !visible)}
          >
            {isPasswordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>

        {errorMessage && <p className="mobile-auth__error">{errorMessage}</p>}

        <Button type="submit" fullWidth isLoading={isSubmitting} disabled={!canSubmit}>
          로그인
        </Button>
      </form>

      <div className="mobile-auth__links">
        <button type="button" onClick={() => navigate('/register')}>
          회원가입
        </button>
        <button type="button" onClick={() => navigate('/forgot-password')}>
          비밀번호 찾기
        </button>
      </div>
    </main>
  );
}
