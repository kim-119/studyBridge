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

  getProfile: async (userId) => {
    try {
      const res = await api.get(`/api/users/${userId}/profile`);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '프로필 조회 실패' };
    }
  },

  updateProfile: async (userId, profileData) => {
    try {
      const res = await api.put(`/api/users/${userId}/profile`, profileData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '프로필 업데이트 실패' };
    }
  },

  updatePassword: async (passwordData) => {
    try {
      const res = await api.put('/api/users/password', passwordData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '비밀번호 변경 실패' };
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

export const roomService = {
  getRooms: async (userId) => {
    const res = await api.get(`/api/users/${userId}/agent-rooms`);
    return res.data;
  },
  createRoom: async (userId, roomData) => {
    const res = await api.post(`/api/users/${userId}/agent-rooms`, roomData);
    return res.data;
  },
  sendMessage: async (userId, roomId, message) => {
    const res = await api.post(`/api/users/${userId}/chat/rooms/${roomId}`, { message });
    return res.data;
  },
  getChatHistory: async (userId, roomId) => {
    const res = await api.get(`/api/users/${userId}/chat/rooms/${roomId}/history`);
    return res.data;
  }
};

export const timerService = {
  startTimer: async (userId, startTime) => {
    const res = await api.post(`/api/users/${userId}/timers/start`, { userId: Number(userId), startTime });
    return res.data;
  },
  endTimer: async (userId, endTime, durationMinutes) => {
    const res = await api.post(`/api/users/${userId}/timers/end`, { userId: Number(userId), endTime, durationMinutes });
    return res.data;
  },
  getCurrentSession: async (userId) => {
    const res = await api.get(`/api/users/${userId}/timers/current`);
    return res.data;
  },
  getTimerHistory: async (userId) => {
    const res = await api.get(`/api/users/${userId}/timers`);
    return res.data;
  }
};

export default api;