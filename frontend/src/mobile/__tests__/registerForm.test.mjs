import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_REGISTER_FORM,
  buildRegisterPayload,
  validateRegisterForm,
} from '../screens/auth/registerForm.js';

const VALID_FORM = {
  email: ' mobile.signup@studybridge.test ',
  password: 'Sbtest#2026a',
  passwordConfirm: 'Sbtest#2026a',
  displayName: ' 모바일가입 ',
  major: ' 컴퓨터공학 ',
};

const BACKEND_REGISTER_REQUEST_FIELDS = ['displayName', 'email', 'major', 'password', 'passwordConfirm'];

test('회원가입 요청 본문은 백엔드 RegisterRequest 필드를 모두 담는다', () => {
  const payload = buildRegisterPayload(VALID_FORM);

  assert.deepEqual(Object.keys(payload).sort(), BACKEND_REGISTER_REQUEST_FIELDS);
  assert.equal(payload.passwordConfirm, VALID_FORM.passwordConfirm);
  assert.equal(payload.email, 'mobile.signup@studybridge.test');
  assert.equal(payload.displayName, '모바일가입');
  assert.equal(payload.major, '컴퓨터공학');
});

test('올바른 입력은 검증 오류가 없다', () => {
  assert.deepEqual(validateRegisterForm(VALID_FORM), {});
});

test('빈 폼은 이메일·비밀번호·닉네임 오류를 모두 보여준다', () => {
  const errors = validateRegisterForm(EMPTY_REGISTER_FORM);

  assert.ok(errors.email);
  assert.ok(errors.password);
  assert.ok(errors.displayName);
});

test('비밀번호는 백엔드와 같은 8~16자 범위를 지킨다', () => {
  const tooShort = 'Ab1!xyz';
  const tooLong = 'Ab1!xyzAb1!xyzAb1';

  assert.match(validateRegisterForm({ ...VALID_FORM, password: tooShort, passwordConfirm: tooShort }).password, /8~16자/);
  assert.match(validateRegisterForm({ ...VALID_FORM, password: tooLong, passwordConfirm: tooLong }).password, /8~16자/);
});

test('비밀번호는 웹과 같은 영문·숫자·특수문자 조합을 요구한다', () => {
  const lettersAndDigitsOnly = 'Sbtest2026';

  assert.match(
    validateRegisterForm({ ...VALID_FORM, password: lettersAndDigitsOnly, passwordConfirm: lettersAndDigitsOnly }).password,
    /특수문자/
  );
});

test('비밀번호 확인이 다르면 오류를 보여준다', () => {
  assert.ok(validateRegisterForm({ ...VALID_FORM, passwordConfirm: 'Sbtest#2026b' }).passwordConfirm);
});

test('닉네임은 백엔드와 같은 2~10자 범위를 지킨다', () => {
  assert.ok(validateRegisterForm({ ...VALID_FORM, displayName: '가' }).displayName);
  assert.ok(validateRegisterForm({ ...VALID_FORM, displayName: '가나다라마바사아자차카' }).displayName);
  assert.equal(validateRegisterForm({ ...VALID_FORM, displayName: '가나' }).displayName, undefined);
});
