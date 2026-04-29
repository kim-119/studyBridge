import axios from 'axios';

// 공통 API 설정 (백엔드 서버 주소)
const api = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

// 응답 에러 공통 처리
api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error('API 에러:', err.response || err.message);
    return Promise.reject(err);
  }
);

// 인증 관련 API
export const authService = {
  // 회원가입
  register: async (userData) => {
    try {
      const res = await api.post('/api/users/register', userData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '회원가입 실패' };
    }
  },


  // 로그인
login: async (credentials) => {
  // 백엔드 로그인 API 완성 전까지 사용하는 임시 로그인
  return {
    email: credentials.email,
  };
}
};

export default api;