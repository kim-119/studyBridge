import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { groupService } from '../../../services/api';
import {
  forceSecureWebSocketTransport,
  parseConnectionMetadata,
  resolveIceServers,
} from '../../../utils/webrtc/iceServers';
import { describeApiError } from '../../data/useAsync';
import { registerAppStateChange } from '../../platform/nativeShell';
import {
  requestMediaPermissions,
  setSpeakerphone,
  startVoiceSession,
  stopVoiceSession,
} from '../../platform/mediaSession';
import { FACING_MODE, acquireCameraTrack, describeDeviceError, oppositeFacingMode } from './cameraTrack';
import { buildConnectionData, describeConnection } from './groupStudyModel';
import {
  DEVICE_TOGGLE,
  INITIAL_MEDIA_STATE,
  MEDIA_ACTION,
  MEDIA_PHASE,
  mediaSessionReducer,
  planDeviceToggle,
  planLocalMedia,
  publishAttempts,
  resolvePermissionGrants,
  withoutCamera,
} from './mediaJoinModel';
import { describeStreamMedia } from './participantTileModel';
import { planReconnect } from './socketConnectionModel';

const VIDEO_RECONNECT_POLICY = { baseDelayMs: 2000, maxDelayMs: 8000, maxAttempts: 3 };
const CAMERA_OPEN_FAILED = '카메라를 열지 못했습니다.';
const MEDIA_NOT_READY_NOTICE = '화상 연결이 완료되면 카메라와 마이크를 켤 수 있습니다.';
const DISCONNECTED_MESSAGE = '화상 연결이 끊어졌습니다.';

function describeSessionError(error) {
  return describeDeviceError(error) || describeApiError(error);
}

function stopPublisherTracks(publisher) {
  publisher?.stream?.getMediaStream?.()?.getTracks?.().forEach((track) => track.stop());
}

function disconnectQuietly(session) {
  try {
    session?.disconnect();
  } catch (error) {
    console.warn('화상 세션을 정리하지 못했습니다.', error);
  }
}

function stopTrack(track) {
  if (track && track.readyState !== 'ended') track.stop();
}

async function resolveCameraTrack(handoffTrack, facingMode) {
  if (handoffTrack && handoffTrack.readyState === 'live') return handoffTrack;
  return acquireCameraTrack(facingMode);
}

async function requestGrants(wantsAnyDevice) {
  if (!wantsAnyDevice) return { camera: false, microphone: false };

  try {
    return resolvePermissionGrants(await requestMediaPermissions());
  } catch (error) {
    console.warn('카메라·마이크 권한을 확인하지 못했습니다.', error);
    return { camera: false, microphone: false };
  }
}

function remoteIdentity(connection) {
  const identity = describeConnection(parseConnectionMetadata(connection));
  return { userId: identity.userId, name: identity.name || '참여자' };
}

async function initPublisher(openVidu, attempt, cameraTrack) {
  return openVidu.initPublisherAsync(undefined, {
    audioSource: attempt.useMicrophone ? undefined : false,
    videoSource: attempt.useCamera ? cameraTrack : false,
    publishAudio: attempt.useMicrophone,
    publishVideo: attempt.useCamera,
    resolution: '480x640',
    frameRate: 24,
    mirror: false,
  });
}

async function startAudioRouting() {
  try {
    const audioState = await startVoiceSession({ speakerphone: true });
    return Boolean(audioState.speakerphone);
  } catch (error) {
    console.warn('통화 오디오 경로를 설정하지 못했습니다.', error);
    return true;
  }
}

function useRemoteParticipants() {
  const [participants, setParticipants] = useState({});

  const upsert = useCallback((connectionId, patch) => {
    setParticipants((previous) => ({
      ...previous,
      [connectionId]: { ...(previous[connectionId] || {}), connectionId, ...patch },
    }));
  }, []);

  const remove = useCallback((connectionId) => {
    setParticipants((previous) => {
      const next = { ...previous };
      delete next[connectionId];
      return next;
    });
  }, []);

  const removeByUserId = useCallback((targetUserId) => {
    setParticipants((previous) =>
      Object.fromEntries(
        Object.entries(previous).filter(([, participant]) => String(participant.userId) !== String(targetUserId))
      )
    );
  }, []);

  const clear = useCallback(() => setParticipants({}), []);

  return { list: Object.values(participants), upsert, remove, removeByUserId, clear };
}

export function useVideoSession(groupId, { userId, displayName }) {
  const [media, dispatch] = useReducer(mediaSessionReducer, INITIAL_MEDIA_STATE);
  const [publisher, setPublisher] = useState(null);
  const [isCameraOn, setCameraOn] = useState(false);
  const [isMicrophoneOn, setMicrophoneOn] = useState(false);
  const [isSpeakerphoneOn, setSpeakerphoneOn] = useState(true);
  const [facingMode, setFacingMode] = useState(FACING_MODE.FRONT);
  const [isSwitchingCamera, setSwitchingCamera] = useState(false);
  const [isUpdatingDevices, setUpdatingDevices] = useState(false);
  const {
    list: remoteParticipants,
    upsert: upsertRemote,
    remove: removeRemote,
    removeByUserId: removeRemotesByUserId,
    clear: clearRemotes,
  } = useRemoteParticipants();

  const openViduRef = useRef(null);
  const sessionRef = useRef(null);
  const publisherRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const isLeavingRef = useRef(false);
  const joinRef = useRef(null);
  const joinOptionsRef = useRef({ cameraOn: false, micOn: false, facingMode: FACING_MODE.FRONT });
  const cameraBeforeBackgroundRef = useRef(false);

  const setNotice = useCallback((message) => dispatch({ type: MEDIA_ACTION.NOTICE_CHANGED, message }), []);

  const rememberDeviceState = useCallback((patch) => {
    joinOptionsRef.current = { ...joinOptionsRef.current, ...patch };
  }, []);

  const releasePublisher = useCallback(() => {
    const current = publisherRef.current;
    if (!current) return;

    try {
      sessionRef.current?.unpublish(current);
    } catch (error) {
      console.warn('송출을 정리하지 못했습니다.', error);
    }
    stopPublisherTracks(current);
    publisherRef.current = null;
    setPublisher(null);
  }, []);

  const teardownSession = useCallback(() => {
    clearTimeout(reconnectTimerRef.current);
    stopPublisherTracks(publisherRef.current);
    publisherRef.current = null;
    setPublisher(null);
    disconnectQuietly(sessionRef.current);
    sessionRef.current = null;
    openViduRef.current = null;
    clearRemotes();
  }, [clearRemotes]);

  const scheduleReconnect = useCallback(() => {
    if (isLeavingRef.current) return;

    const plan = planReconnect(reconnectAttemptRef.current, VIDEO_RECONNECT_POLICY);
    if (plan.kind === 'give-up') {
      dispatch({ type: MEDIA_ACTION.CONNECT_FAILED, message: DISCONNECTED_MESSAGE });
      return;
    }

    reconnectAttemptRef.current = plan.nextAttempt;
    dispatch({ type: MEDIA_ACTION.RECONNECT_SCHEDULED, attempt: plan.nextAttempt });
    reconnectTimerRef.current = setTimeout(() => {
      joinRef.current?.({ ...joinOptionsRef.current, isReconnect: true });
    }, plan.delayMs);
  }, []);

  const registerSessionEvents = useCallback(
    (session) => {
      const isOwnConnection = (connectionId) => connectionId === session.connection?.connectionId;

      session.on('connectionCreated', (event) => {
        const connectionId = event.connection?.connectionId;
        if (!connectionId || isOwnConnection(connectionId)) return;
        upsertRemote(connectionId, { ...remoteIdentity(event.connection), streamManager: null, cameraOn: false, micOn: false });
      });

      session.on('streamCreated', (event) => {
        const subscriber = session.subscribe(event.stream, undefined);
        upsertRemote(event.stream.connection.connectionId, {
          ...remoteIdentity(event.stream.connection),
          ...describeStreamMedia(event.stream),
          streamManager: subscriber,
        });
      });

      session.on('streamPropertyChanged', (event) => {
        const connectionId = event.stream?.connection?.connectionId;
        if (!connectionId || isOwnConnection(connectionId)) return;
        upsertRemote(connectionId, describeStreamMedia(event.stream));
      });

      session.on('streamDestroyed', (event) => {
        upsertRemote(event.stream.connection.connectionId, { streamManager: null, cameraOn: false, micOn: false });
      });

      session.on('connectionDestroyed', (event) => {
        removeRemote(event.connection.connectionId);
      });

      session.on('sessionDisconnected', (event) => {
        if (isLeavingRef.current || event?.reason === 'disconnect') return;
        teardownSession();
        scheduleReconnect();
      });

      session.on('reconnecting', () => dispatch({ type: MEDIA_ACTION.CONNECT_STARTED, isReconnect: true }));
      session.on('reconnected', () => dispatch({ type: MEDIA_ACTION.CONNECTED }));
    },
    [removeRemote, scheduleReconnect, teardownSession, upsertRemote]
  );

  const publishWithFallback = useCallback(async (plan, cameraTrack) => {
    let lastError = null;

    for (const attempt of publishAttempts(plan)) {
      try {
        const nextPublisher = await initPublisher(openViduRef.current, attempt, cameraTrack);
        await sessionRef.current.publish(nextPublisher);
        return { publisher: nextPublisher, attempt };
      } catch (error) {
        lastError = error;
        console.warn('송출 시도에 실패했습니다.', attempt, error);
      }
    }

    throw lastError;
  }, []);

  const publishLocalMedia = useCallback(
    async ({ wantsCamera, wantsMicrophone, handoffTrack, cameraFacing }) => {
      if (!sessionRef.current || !openViduRef.current) {
        stopTrack(handoffTrack);
        return;
      }

      const grants = await requestGrants(wantsCamera || wantsMicrophone);
      let plan = planLocalMedia({ wantsCamera, wantsMicrophone, grants });
      let cameraTrack = null;

      if (plan.useCamera) {
        try {
          cameraTrack = await resolveCameraTrack(handoffTrack, cameraFacing);
        } catch (error) {
          console.warn('카메라 트랙을 가져오지 못했습니다.', error);
          plan = withoutCamera(plan, describeDeviceError(error) || CAMERA_OPEN_FAILED);
        }
      } else {
        stopTrack(handoffTrack);
      }

      setNotice(plan.notice);

      if (!plan.shouldPublish) {
        setCameraOn(false);
        setMicrophoneOn(false);
        return;
      }

      try {
        const published = await publishWithFallback(plan, cameraTrack);
        if (!published.attempt.useCamera) stopTrack(cameraTrack);
        publisherRef.current = published.publisher;
        setPublisher(published.publisher);
        setCameraOn(published.attempt.useCamera);
        setMicrophoneOn(published.attempt.useMicrophone);
        rememberDeviceState({ cameraOn: published.attempt.useCamera, micOn: published.attempt.useMicrophone });
      } catch (error) {
        stopTrack(cameraTrack);
        setCameraOn(false);
        setMicrophoneOn(false);
        setNotice(`카메라·마이크 송출을 시작하지 못했습니다. ${describeSessionError(error)} 다른 참여자의 화면은 계속 볼 수 있습니다.`);
      }
    },
    [publishWithFallback, rememberDeviceState, setNotice]
  );

  const connectSession = useCallback(async () => {
    const { OpenVidu } = await import('openvidu-browser');
    const tokenResponse = await groupService.getVideoToken(groupId);
    if (isLeavingRef.current) return false;

    const openVidu = new OpenVidu();
    forceSecureWebSocketTransport(openVidu);
    openVidu.setAdvancedConfiguration({ iceServers: resolveIceServers(tokenResponse) });

    const session = openVidu.initSession();
    openViduRef.current = openVidu;
    sessionRef.current = session;
    registerSessionEvents(session);

    await session.connect(tokenResponse.token, buildConnectionData(userId, displayName));
    return !isLeavingRef.current;
  }, [displayName, groupId, registerSessionEvents, userId]);

  const join = useCallback(
    async ({ isReconnect = false, cameraOn = false, micOn = false, facingMode: requestedFacing, videoTrack } = {}) => {
      const cameraFacing = requestedFacing || FACING_MODE.FRONT;
      joinOptionsRef.current = { cameraOn, micOn, facingMode: cameraFacing };
      isLeavingRef.current = false;
      setFacingMode(cameraFacing);
      if (!isReconnect) reconnectAttemptRef.current = 0;
      dispatch({ type: MEDIA_ACTION.CONNECT_STARTED, isReconnect });

      try {
        teardownSession();
        const isConnected = await connectSession();
        if (!isConnected) {
          stopTrack(videoTrack);
          teardownSession();
          return;
        }
      } catch (error) {
        console.warn('화상 스터디 연결에 실패했습니다.', error);
        stopTrack(videoTrack);
        teardownSession();

        if (isReconnect) {
          scheduleReconnect();
          return;
        }

        dispatch({ type: MEDIA_ACTION.CONNECT_FAILED, message: describeSessionError(error) });
        return;
      }

      reconnectAttemptRef.current = 0;
      dispatch({ type: MEDIA_ACTION.CONNECTED });
      await publishLocalMedia({ wantsCamera: cameraOn, wantsMicrophone: micOn, handoffTrack: videoTrack, cameraFacing });
      setSpeakerphoneOn(await startAudioRouting());
    },
    [connectSession, publishLocalMedia, scheduleReconnect, teardownSession]
  );

  joinRef.current = join;

  const retry = useCallback(() => {
    reconnectAttemptRef.current = 0;
    join({ ...joinOptionsRef.current });
  }, [join]);

  const leave = useCallback(async () => {
    isLeavingRef.current = true;
    teardownSession();
    dispatch({ type: MEDIA_ACTION.LEFT });
    try {
      await stopVoiceSession();
    } catch (error) {
      console.warn('통화 오디오 경로를 정리하지 못했습니다.', error);
    }
  }, [teardownSession]);

  const setDeviceEnabled = useCallback(
    async (device, enable) => {
      const current = publisherRef.current;
      const isCamera = device === 'camera';
      const hasTrack = Boolean(isCamera ? current?.stream?.hasVideo : current?.stream?.hasAudio);
      const setEnabled = isCamera ? setCameraOn : setMicrophoneOn;
      const action = planDeviceToggle({ enable, hasPublisher: Boolean(current), hasTrack });

      if (action === DEVICE_TOGGLE.NONE) {
        setEnabled(false);
        rememberDeviceState(isCamera ? { cameraOn: false } : { micOn: false });
        return;
      }

      if (action !== DEVICE_TOGGLE.REPUBLISH) {
        if (isCamera) current.publishVideo(enable);
        else current.publishAudio(enable);
        setEnabled(enable);
        rememberDeviceState(isCamera ? { cameraOn: enable } : { micOn: enable });
        return;
      }

      if (media.phase !== MEDIA_PHASE.CONNECTED) {
        setNotice(MEDIA_NOT_READY_NOTICE);
        return;
      }

      setUpdatingDevices(true);
      releasePublisher();
      await publishLocalMedia({
        wantsCamera: isCamera ? true : isCameraOn,
        wantsMicrophone: isCamera ? isMicrophoneOn : true,
        cameraFacing: facingMode,
      });
      setUpdatingDevices(false);
    },
    [facingMode, isCameraOn, isMicrophoneOn, media.phase, publishLocalMedia, releasePublisher, rememberDeviceState, setNotice]
  );

  const toggleCamera = useCallback(() => setDeviceEnabled('camera', !isCameraOn), [isCameraOn, setDeviceEnabled]);
  const toggleMicrophone = useCallback(
    () => setDeviceEnabled('microphone', !isMicrophoneOn),
    [isMicrophoneOn, setDeviceEnabled]
  );

  const toggleSpeakerphone = useCallback(async () => {
    const next = !isSpeakerphoneOn;
    const audioState = await setSpeakerphone(next);
    setSpeakerphoneOn(Boolean(audioState.speakerphone ?? next));
  }, [isSpeakerphoneOn]);

  const switchCamera = useCallback(async () => {
    const current = publisherRef.current;
    if (!current || !isCameraOn || isSwitchingCamera) return;

    const nextFacing = oppositeFacingMode(facingMode);
    const previousTrack = current.stream?.getMediaStream?.()?.getVideoTracks?.()[0];
    setSwitchingCamera(true);

    try {
      const nextTrack = await acquireCameraTrack(nextFacing);
      await current.replaceTrack(nextTrack);
      previousTrack?.stop();
      setFacingMode(nextFacing);
      rememberDeviceState({ facingMode: nextFacing });
    } catch (error) {
      console.warn('카메라 전환에 실패했습니다.', error);
      setNotice(describeDeviceError(error) || '카메라를 전환하지 못했습니다.');
    } finally {
      setSwitchingCamera(false);
    }
  }, [facingMode, isCameraOn, isSwitchingCamera, rememberDeviceState, setNotice]);

  useEffect(() => {
    return registerAppStateChange(({ isActive }) => {
      const current = publisherRef.current;
      if (!current?.stream?.hasVideo) return;

      if (!isActive) {
        cameraBeforeBackgroundRef.current = isCameraOn;
        current.publishVideo(false);
        setCameraOn(false);
        return;
      }

      if (cameraBeforeBackgroundRef.current) {
        current.publishVideo(true);
        setCameraOn(true);
      }
    });
  }, [isCameraOn]);

  useEffect(() => {
    return () => {
      isLeavingRef.current = true;
      clearTimeout(reconnectTimerRef.current);
      stopPublisherTracks(publisherRef.current);
      disconnectQuietly(sessionRef.current);
      stopVoiceSession().catch(() => {});
    };
  }, []);

  return {
    phase: media.phase,
    errorMessage: media.errorMessage,
    notice: media.notice,
    reconnectAttempt: media.reconnectAttempt,
    remoteParticipants,
    publisher,
    isCameraOn,
    isMicrophoneOn,
    isSpeakerphoneOn,
    facingMode,
    isSwitchingCamera,
    isUpdatingDevices,
    join,
    retry,
    leave,
    dismissNotice: () => setNotice(null),
    toggleCamera,
    toggleMicrophone,
    toggleSpeakerphone,
    switchCamera,
    removeParticipantsByUserId: removeRemotesByUserId,
  };
}
