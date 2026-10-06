export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 16;
export const DISPLAY_NAME_MIN_LENGTH = 2;
export const DISPLAY_NAME_MAX_LENGTH = 10;

const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
const PASSWORD_PATTERN = /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[^a-zA-Z0-9]).+$/;

export const EMPTY_REGISTER_FORM = {
  email: '',
  password: '',
  passwordConfirm: '',
  displayName: '',
  major: '',
};

export function validateRegisterForm({ email, password, passwordConfirm, displayName }) {
  const errors = {};
  const trimmedName = displayName.trim();

  if (!EMAIL_PATTERN.test(email.trim())) {
    errors.email = '올바른 이메일 형식이 아닙니다.';
  }

  if (password.length < PASSWORD_MIN_LENGTH || password.length > PASSWORD_MAX_LENGTH) {
    errors.password = `비밀번호는 ${PASSWORD_MIN_LENGTH}~${PASSWORD_MAX_LENGTH}자여야 합니다.`;
  } else if (!PASSWORD_PATTERN.test(password)) {
    errors.password = '비밀번호는 영문, 숫자, 특수문자를 모두 포함해야 합니다.';
  }

  if (password !== passwordConfirm) {
    errors.passwordConfirm = '비밀번호가 일치하지 않습니다.';
  }

  if (trimmedName.length < DISPLAY_NAME_MIN_LENGTH || trimmedName.length > DISPLAY_NAME_MAX_LENGTH) {
    errors.displayName = `닉네임은 ${DISPLAY_NAME_MIN_LENGTH}~${DISPLAY_NAME_MAX_LENGTH}자여야 합니다.`;
  }

  return errors;
}

export function buildRegisterPayload({ email, password, passwordConfirm, displayName, major }) {
  return {
    email: email.trim(),
    password,
    passwordConfirm,
    displayName: displayName.trim(),
    major: major.trim(),
  };
}
