import React from 'react';
import { AlertTriangle, Shield, Settings } from 'lucide-react';
import { NAV_ICON_SIZE } from './prejoinUi';

// 입장 준비 하단 내비(정보 / 방장 관리 / 장치 설정) — GENERAL/CAM 공통(기존 위치·크기 유지).
export default function PreJoinNav({ isLeader, showInfo, showSettings, showLeaderConsole, onInfo, onLeaderConsole, onSettings, settingsLabel = '장치 설정' }) {
  const btn = (active, color) => ({ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', background: 'none', border: 'none', cursor: 'pointer', color: active ? color : '#6B7280', flex: 1 });
  return (
    <div data-testid="prejoin-nav" style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center', padding: '16px', backgroundColor: 'white', borderTop: '1px solid #E5E7EB' }}>
      <button type="button" style={btn(showInfo, '#3B82F6')} onClick={onInfo}>
        <AlertTriangle size={NAV_ICON_SIZE} />
        <span style={{ fontSize: '12px', fontWeight: '500' }}>정보</span>
      </button>
      {isLeader && (
        <button type="button" style={btn(showLeaderConsole, '#10B981')} onClick={onLeaderConsole} data-testid="prejoin-leader-console-button">
          <Shield size={NAV_ICON_SIZE} />
          <span style={{ fontSize: '12px', fontWeight: '500' }}>방장 관리</span>
        </button>
      )}
      <button type="button" style={btn(showSettings, '#3B82F6')} onClick={onSettings} data-testid="prejoin-settings-button">
        <Settings size={NAV_ICON_SIZE} />
        <span style={{ fontSize: '12px', fontWeight: '500' }}>{settingsLabel}</span>
      </button>
    </div>
  );
}
