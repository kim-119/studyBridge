import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { authService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';

const STEP = {
  REQUEST_CODE: 'request-code',
  VERIFY_CODE: 'verify-code',
  RESET: 'reset',
};

const STEP_ACTION_LABEL = {
  [STEP.REQUEST_CODE]: '인증 코드 받기',
  [STEP.VERIFY_CODE]: '코드 확인',
  [STEP.RESET]: '비밀번호 변경',
};

export default function ForgotPasswordScreen() {
  const navigate = useNavigate();
  const [step, setStep] = useState(STEP.REQUEST_CODE);
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');

  const requestCode = useSubmit(async () => {
    await authService.sendPasswordResetCode(email.trim());
    setStep(STEP.VERIFY_CODE);
  });

  const verifyCode = useSubmit(async () => {
    await authService.verifyPasswordResetCode(email.trim(), code.trim());
    setStep(STEP.RESET);
  });

  const resetPassword = useSubmit(async () => {
    await authService.resetPassword(email.trim(), password, passwordConfirm);
    navigate('/login', { replace: true });
  });

  const stepAction = {
    [STEP.REQUEST_CODE]: requestCode,
    [STEP.VERIFY_CODE]: verifyCode,
    [STEP.RESET]: resetPassword,
  }[step];

  const handleSubmit = (event) => {
    event.preventDefault();
    stepAction.submit().catch(() => {});
  };

  return (
    <MobileScreen title="비밀번호 찾기" showBackButton>
      <form onSubmit={handleSubmit}>
        <TextField
          label="이메일"
          type="email"
          inputMode="email"
          autoCapitalize="none"
          value={email}
          disabled={step !== STEP.REQUEST_CODE}
          onChange={(event) => setEmail(event.target.value)}
        />

        {step === STEP.VERIFY_CODE && (
          <TextField
            label="인증 코드"
            inputMode="numeric"
            value={code}
            hint="이메일로 전송된 코드를 입력하세요"
            onChange={(event) => setCode(event.target.value)}
          />
        )}

        {step === STEP.RESET && (
          <>
            <TextField
              label="새 비밀번호"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <TextField
              label="새 비밀번호 확인"
              type="password"
              value={passwordConfirm}
              onChange={(event) => setPasswordConfirm(event.target.value)}
            />
          </>
        )}

        {stepAction.errorMessage && <p className="mobile-auth__error">{stepAction.errorMessage}</p>}

        <Button type="submit" fullWidth isLoading={stepAction.isSubmitting}>
          {STEP_ACTION_LABEL[step]}
        </Button>
      </form>
    </MobileScreen>
  );
}
