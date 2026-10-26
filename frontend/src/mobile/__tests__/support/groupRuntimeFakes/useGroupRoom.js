import { INITIAL_QUIZ_STATE } from '../../../screens/groupstudy/quizSessionModel.js';

const fakeRoom = {
  socketState: 'connected',
  socketReconnectAttempt: 0,
  isSocketConnected: true,
  reconnectSocket: () => {},
  history: { data: [], isSuccess: true, isLoading: false, isError: false },
  chatMessages: [],
  chatRecoveryError: null,
  aiHistory: [],
  sendChat: () => true,
  quiz: INITIAL_QUIZ_STATE,
  quizRemainingSeconds: 0,
  canAnswerQuiz: false,
  quizError: null,
  clearQuizError: () => {},
  startQuiz: () => {},
  submitAnswer: () => {},
  dismissQuiz: () => {},
};

export function useGroupRoom() {
  return fakeRoom;
}
