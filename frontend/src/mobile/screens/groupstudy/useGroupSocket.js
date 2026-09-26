import { useCallback, useEffect, useRef, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const RECONNECT_DELAY_MS = 4000;

export const SOCKET_STATE = {
  IDLE: 'idle',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
};

/**
 * 그룹스터디 STOMP 연결. 채팅·퀴즈 토픽을 한 연결로 공유한다.
 * Capacitor WebView 의 origin 은 https://localhost 라서 SockJS 엔드포인트를
 * 상대경로가 아니라 운영 도메인 절대경로로 지정해야 한다.
 */
export function useGroupSocket(groupId, subscriptions) {
  const [state, setState] = useState(SOCKET_STATE.IDLE);
  const clientRef = useRef(null);
  const handlersRef = useRef(subscriptions);
  handlersRef.current = subscriptions;

  useEffect(() => {
    let isMounted = true;
    let client = null;

    const connect = async () => {
      setState(SOCKET_STATE.CONNECTING);

      const [{ Client }, sockJsModule] = await Promise.all([
        import('@stomp/stompjs'),
        import('sockjs-client'),
      ]);
      const SockJS = sockJsModule.default || sockJsModule;

      if (!isMounted) return;

      client = new Client({
        webSocketFactory: () => new SockJS(`${API_BASE_URL}/ws-group`, null, { credentials: false }),
        reconnectDelay: RECONNECT_DELAY_MS,
        onConnect: () => {
          if (!isMounted) return;
          setState(SOCKET_STATE.CONNECTED);

          Object.entries(handlersRef.current || {}).forEach(([topic, handler]) => {
            client.subscribe(`/topic/group/${groupId}/${topic}`, (message) => {
              try {
                handler(JSON.parse(message.body));
              } catch {
                handler(message.body);
              }
            });
          });
        },
        onWebSocketClose: () => {
          if (isMounted) setState(SOCKET_STATE.DISCONNECTED);
        },
        onStompError: () => {
          if (isMounted) setState(SOCKET_STATE.DISCONNECTED);
        },
      });

      clientRef.current = client;
      client.activate();
    };

    connect().catch((error) => {
      console.warn('그룹 소켓 연결에 실패했습니다.', error);
      if (isMounted) setState(SOCKET_STATE.DISCONNECTED);
    });

    return () => {
      isMounted = false;
      clientRef.current?.deactivate();
      clientRef.current = null;
    };
  }, [groupId]);

  const publish = useCallback((destination, body) => {
    const client = clientRef.current;
    if (!client?.connected) return false;

    client.publish({
      destination: `/pub/group/${groupId}/${destination}`,
      body: JSON.stringify(body),
    });
    return true;
  }, [groupId]);

  return { state, publish, isConnected: state === SOCKET_STATE.CONNECTED };
}
