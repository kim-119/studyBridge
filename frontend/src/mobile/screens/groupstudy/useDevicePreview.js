import { useCallback, useEffect, useRef, useState } from 'react';
import { checkMediaPermissions, requestMediaPermissions } from '../../platform/mediaSession';
import { acquireCameraStream, describeDeviceError, hasMediaDevices, stopStream } from './cameraTrack';

export const DEVICE_STATUS = {
  OFF: 'off',
  CHECKING: 'checking',
  READY: 'ready',
  ERROR: 'error',
};

export const PERMISSION_STATUS = {
  CHECKING: 'checking',
  GRANTED: 'granted',
  NOT_GRANTED: 'not-granted',
  ERROR: 'error',
};

const UNSUPPORTED_MESSAGE = '이 기기에서는 카메라와 마이크를 사용할 수 없습니다.';
const LEVEL_SCALE = 60;

function toPermissionStatus(result) {
  return result?.granted ? PERMISSION_STATUS.GRANTED : PERMISSION_STATUS.NOT_GRANTED;
}

export function useMediaPermission() {
  const [status, setStatus] = useState(PERMISSION_STATUS.CHECKING);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    let isMounted = true;

    checkMediaPermissions()
      .then((result) => {
        if (isMounted) setStatus(toPermissionStatus(result));
      })
      .catch((error) => {
        if (!isMounted) return;
        setErrorMessage(error?.message || '권한 상태를 확인하지 못했습니다.');
        setStatus(PERMISSION_STATUS.ERROR);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const request = useCallback(async () => {
    setErrorMessage(null);
    try {
      setStatus(toPermissionStatus(await requestMediaPermissions()));
    } catch (error) {
      setErrorMessage(error?.message || '권한을 요청하지 못했습니다.');
      setStatus(PERMISSION_STATUS.ERROR);
    }
  }, []);

  return { status, errorMessage, request };
}

export function useCameraPreview({ isEnabled, facingMode }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [status, setStatus] = useState(DEVICE_STATUS.OFF);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    if (!isEnabled) {
      setStatus(DEVICE_STATUS.OFF);
      setErrorMessage(null);
      return undefined;
    }

    if (!hasMediaDevices()) {
      setStatus(DEVICE_STATUS.ERROR);
      setErrorMessage(UNSUPPORTED_MESSAGE);
      return undefined;
    }

    let isMounted = true;
    let stream = null;
    setStatus(DEVICE_STATUS.CHECKING);
    setErrorMessage(null);

    acquireCameraStream(facingMode)
      .then((acquired) => {
        if (!isMounted) {
          stopStream(acquired);
          return;
        }
        stream = acquired;
        streamRef.current = acquired;
        if (videoRef.current) videoRef.current.srcObject = acquired;
        setStatus(DEVICE_STATUS.READY);
      })
      .catch((error) => {
        if (!isMounted) return;
        setStatus(DEVICE_STATUS.ERROR);
        setErrorMessage(describeDeviceError(error) || '카메라를 불러오지 못했습니다.');
      });

    return () => {
      isMounted = false;
      stopStream(stream);
      if (streamRef.current === stream) streamRef.current = null;
    };
  }, [facingMode, isEnabled]);

  return { videoRef, streamRef, status, errorMessage };
}

function averageLevel(analyser, buffer) {
  analyser.getByteFrequencyData(buffer);
  const sum = buffer.reduce((total, value) => total + value, 0);
  return Math.min(100, Math.round((sum / buffer.length / LEVEL_SCALE) * 100));
}

export function useMicrophoneLevel({ isEnabled }) {
  const [status, setStatus] = useState(DEVICE_STATUS.OFF);
  const [level, setLevel] = useState(0);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    setLevel(0);

    if (!isEnabled) {
      setStatus(DEVICE_STATUS.OFF);
      setErrorMessage(null);
      return undefined;
    }

    if (!hasMediaDevices()) {
      setStatus(DEVICE_STATUS.ERROR);
      setErrorMessage(UNSUPPORTED_MESSAGE);
      return undefined;
    }

    let isMounted = true;
    let stream = null;
    let audioContext = null;
    let frameId = null;
    setStatus(DEVICE_STATUS.CHECKING);
    setErrorMessage(null);

    navigator.mediaDevices
      .getUserMedia({ audio: true, video: false })
      .then((acquired) => {
        if (!isMounted) {
          stopStream(acquired);
          return;
        }
        stream = acquired;
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        audioContext.createMediaStreamSource(acquired).connect(analyser);
        const buffer = new Uint8Array(analyser.frequencyBinCount);
        setStatus(DEVICE_STATUS.READY);

        const tick = () => {
          if (!isMounted) return;
          setLevel(averageLevel(analyser, buffer));
          frameId = requestAnimationFrame(tick);
        };
        tick();
      })
      .catch((error) => {
        if (!isMounted) return;
        setStatus(DEVICE_STATUS.ERROR);
        setErrorMessage(describeDeviceError(error) || '마이크를 불러오지 못했습니다.');
      });

    return () => {
      isMounted = false;
      if (frameId) cancelAnimationFrame(frameId);
      if (audioContext && audioContext.state !== 'closed') audioContext.close();
      stopStream(stream);
    };
  }, [isEnabled]);

  return { status, level, errorMessage };
}
