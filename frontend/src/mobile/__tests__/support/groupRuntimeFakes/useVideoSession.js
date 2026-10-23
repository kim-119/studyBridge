export const videoSessionCalls = { join: [], leave: 0, toggleCamera: 0, toggleMicrophone: 0 };

const fakeSession = {
  phase: 'connected',
  errorMessage: null,
  notice: null,
  reconnectAttempt: 0,
  remoteParticipants: [{ connectionId: 'remote-1', userId: 2, name: '민지', streamManager: null, cameraOn: false, micOn: false }],
  publisher: null,
  isCameraOn: false,
  isMicrophoneOn: false,
  isSpeakerphoneOn: true,
  facingMode: 'user',
  isSwitchingCamera: false,
  isUpdatingDevices: false,
  join: (options) => videoSessionCalls.join.push(options),
  retry: () => {},
  leave: async () => {
    videoSessionCalls.leave += 1;
  },
  dismissNotice: () => {},
  toggleCamera: () => {
    videoSessionCalls.toggleCamera += 1;
  },
  toggleMicrophone: () => {
    videoSessionCalls.toggleMicrophone += 1;
  },
  toggleSpeakerphone: () => {},
  switchCamera: () => {},
  removeParticipantsByUserId: () => {},
};

export function useVideoSession() {
  return fakeSession;
}
