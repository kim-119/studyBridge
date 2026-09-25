import React, { useCallback, useEffect, useState } from 'react';
import { bannerService } from '../services/api';
import { getNetworkStatus } from './platform/connectivity';
import { hideSplashScreen } from './platform/nativeShell';
import { restoreSessionFromDevice } from './platform/tokenStore';

const STATUS = {
  CHECKING: 'checking',
  READY: 'ready',
  OFFLINE: 'offline',
  UNREACHABLE: 'unreachable',
};

const FAILURE_MESSAGE = {
  [STATUS.OFFLINE]: [
    '네트워크에 연결되어 있지 않습니다.',
    '연결 상태를 확인한 뒤 다시 시도해주세요.',
  ],
  [STATUS.UNREACHABLE]: [
    '서버에 연결할 수 없습니다.',
    '잠시 후 다시 시도해주세요.',
  ],
};

export default function MobileBoot({ children }) {
  const [status, setStatus] = useState(STATUS.CHECKING);

  const bootstrap = useCallback(async () => {
    setStatus(STATUS.CHECKING);

    try {
      await restoreSessionFromDevice();
      await bannerService.getMainBanner();
      setStatus(STATUS.READY);
    } catch (error) {
      console.warn('StudyBridge 서버에 연결하지 못했습니다.', error);
      const network = await getNetworkStatus();
      setStatus(network.connected ? STATUS.UNREACHABLE : STATUS.OFFLINE);
    } finally {
      await hideSplashScreen();
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  if (status === STATUS.CHECKING) {
    return (
      <div className="mobile-boot">
        <span className="mobile-boot__brand">StudyBridge</span>
        <p className="mobile-boot__message">학습을 하나로 잇다</p>
      </div>
    );
  }

  if (status !== STATUS.READY) {
    return (
      <div className="mobile-boot">
        <span className="mobile-boot__brand">StudyBridge</span>
        <p className="mobile-boot__message">
          {FAILURE_MESSAGE[status].map((line) => (
            <span key={line}>{line}</span>
          ))}
        </p>
        <button type="button" className="mobile-boot__retry" onClick={bootstrap}>
          다시 시도
        </button>
      </div>
    );
  }

  return children;
}
