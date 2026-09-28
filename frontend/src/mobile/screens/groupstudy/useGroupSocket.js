import { useCallback, useEffect, useRef, useState } from 'react';
import { refreshAccessToken } from '../../../services/api';
import { getNetworkStatus, onNetworkStatusChange } from '../../platform/connectivity';
import { registerAppStateChange } from '../../platform/nativeShell';
import { createGroupSocketController } from './groupSocketController';
import { SOCKET_STATE, isTokenExpiring } from './socketConnectionModel';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const GROUP_SOCKET_URL = `${API_BASE_URL}/ws-group`;

async function loadStompLibraries() {
  const { Client } = await import('@stomp/stompjs');
  return { Client };
}

async function currentAccessToken() {
  const token = localStorage.getItem('token');
  if (!isTokenExpiring(token, Date.now())) return token;

  try {
    return await refreshAccessToken();
  } catch (error) {
    console.warn('그룹 소켓 재연결 전 토큰 갱신에 실패했습니다.', error);
    return localStorage.getItem('token');
  }
}

function watchNetwork(controller) {
  getNetworkStatus()
    .then((status) => {
      if (!status.connected) controller.handleNetworkChange(false);
    })
    .catch((error) => console.warn('네트워크 상태를 확인하지 못했습니다.', error));

  return onNetworkStatusChange((status) => controller.handleNetworkChange(status.connected));
}

export function useGroupSocket(groupId, { subscriptions, onReconnected }) {
  const [status, setStatus] = useState({ state: SOCKET_STATE.IDLE, reconnectAttempt: 0 });
  const controllerRef = useRef(null);
  const handlersRef = useRef(subscriptions);
  const onReconnectedRef = useRef(onReconnected);
  handlersRef.current = subscriptions;
  onReconnectedRef.current = onReconnected;

  useEffect(() => {
    const controller = createGroupSocketController({
      groupId,
      endpointUrl: GROUP_SOCKET_URL,
      getHandlers: () => handlersRef.current || {},
      onStatusChange: setStatus,
      onReconnected: () => onReconnectedRef.current?.(),
      loadLibraries: loadStompLibraries,
      getToken: currentAccessToken,
    });

    controllerRef.current = controller;
    controller.start();

    const stopWatchingAppState = registerAppStateChange(({ isActive }) => {
      if (isActive) controller.handleResume();
    });
    const stopWatchingNetwork = watchNetwork(controller);

    return () => {
      stopWatchingAppState();
      stopWatchingNetwork();
      controller.stop();
      controllerRef.current = null;
    };
  }, [groupId]);

  const publish = useCallback((destination, body) => controllerRef.current?.publish(destination, body) ?? false, []);
  const reconnect = useCallback(() => controllerRef.current?.reconnectNow(), []);

  return {
    state: status.state,
    reconnectAttempt: status.reconnectAttempt,
    isConnected: status.state === SOCKET_STATE.CONNECTED,
    publish,
    reconnect,
  };
}
