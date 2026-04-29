import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8080',
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error('API 에러:', err.response || err.message);
    return Promise.reject(err);
  }
);

export const authService = {
  register: async (userData) => {
    try {
      const res = await api.post('/api/users/register', userData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '회원가입 실패' };
    }
  },

  login: async (credentials) => {
    try {
      const res = await api.post('/api/users/login', credentials);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '로그인 실패' };
    }
  },
};

export const todoService = {
  getTodos: async (userId) => {
    const res = await api.get(`/api/users/${userId}/todos`);
    return res.data;
  },

  createTodo: async (userId, todoData) => {
    const res = await api.post(`/api/users/${userId}/todos`, todoData);
    return res.data;
  },

  toggleTodo: async (todoId) => {
    const res = await api.patch(`/api/todos/${todoId}/toggle`);
    return res.data;
  },

  deleteTodo: async (todoId) => {
    const res = await api.delete(`/api/todos/${todoId}`);
    return res.data;
  },
};

export default api;