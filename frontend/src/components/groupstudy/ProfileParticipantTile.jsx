import React, { useEffect, useState } from 'react';
import { Mic, MicOff } from 'lucide-react';
import DefaultAvatar from './DefaultAvatar';
import RemoteAudioSink from './RemoteAudioSink';

// GENERAL(일반 스터디) 참가자 타일: [프로필 이미지] 닉네임 마이크 상태. 카메라 tile/video track 을 만들지 않는다.
//  · 원격 참가자는 RemoteAudioSink 로 음성만 재생한다. 발화 감지는 기존 VideoFeed 와 같은 analyser 방식.
export default function ProfileParticipantTile({ avatar, fallbackUrl = null, displayName, isLocal, isMicOn, stream, streamManager, speakerId, onSpeakingChange }) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [imgFailed, setImgFailed] = useState(false);
  const [fallbackFailed, setFallbackFailed] = useState(false);

  useEffect(() => { setImgFailed(false); setFallbackFailed(false); }, [avatar?.url, fallbackUrl]);

  useEffect(() => {
    if (onSpeakingChange) onSpeakingChange(speakerId, isSpeaking);
  }, [isSpeaking, speakerId, onSpeakingChange]);
  useEffect(() => () => { if (onSpeakingChange) onSpeakingChange(speakerId, false); }, [speakerId, onSpeakingChange]);

  useEffect(() => {
    if (!stream || !isMicOn) { setIsSpeaking(false); return undefined; }
    const audioTracks = typeof stream.getAudioTracks === 'function' ? stream.getAudioTracks() : [];
    if (audioTracks.length === 0) { setIsSpeaking(false); return undefined; }
    let audioContext; let source; let analyser; let intervalId;
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      intervalId = setInterval(() => {
        if (audioTracks[0] && !audioTracks[0].enabled) { setIsSpeaking(false); return; }
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i += 1) sum += dataArray[i];
        setIsSpeaking(sum / dataArray.length > 10);
      }, 120);
    } catch (e) {
      console.warn('Failed to initialize audio speaking detector', e);
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
      if (source) source.disconnect();
      if (analyser) analyser.disconnect();
      if (audioContext && audioContext.state !== 'closed') audioContext.close();
    };
  }, [stream, isMicOn]);

  // 1차 이미지 실패(presigned 만료 등) → fallbackUrl(계정 프로필) → 기본 아바타.
  const imageUrl = (avatar?.kind === 'image' && avatar.url && !imgFailed) ? avatar.url : ((fallbackUrl && !fallbackFailed) ? fallbackUrl : null);
  const showImage = Boolean(imageUrl);
  const ring = isSpeaking ? '0 0 0 3px #22C55E, 0 0 20px rgba(34, 197, 94, 0.6)' : '0 8px 24px rgba(0,0,0,0.4)';

  return (
    <div
      data-testid="profile-participant-tile"
      data-mic-on={isMicOn ? 'true' : 'false'}
      style={{ position: 'relative', backgroundColor: '#1E293B', borderRadius: '16px', overflow: 'hidden', aspectRatio: '16/9', border: `1px solid ${isSpeaking ? '#22C55E' : 'rgba(255,255,255,0.05)'}`, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '10px', padding: '12px', boxSizing: 'border-box', transition: 'all 0.2s ease' }}
    >
      {!isLocal && streamManager && <RemoteAudioSink streamManager={streamManager} stream={stream} />}
      {showImage ? (
        <img
          src={imageUrl}
          alt={displayName}
          onError={() => { if (imageUrl === avatar?.url) setImgFailed(true); else setFallbackFailed(true); }}
          style={{ width: '72px', height: '72px', borderRadius: '50%', objectFit: 'cover', boxShadow: ring, transition: 'box-shadow 0.15s ease' }}
        />
      ) : (
        <DefaultAvatar size={72} dark style={{ boxShadow: ring, transition: 'box-shadow 0.15s ease' }} />
      )}
      <div style={{ color: 'white', fontSize: '14px', fontWeight: '600', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {displayName} {isLocal ? '(나)' : ''}
      </div>
      <div
        data-testid="profile-participant-mic"
        style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 10px', borderRadius: '20px', backgroundColor: 'rgba(15, 23, 42, 0.6)', border: `1px solid ${isMicOn ? 'rgba(34,197,94,0.5)' : 'rgba(248,113,113,0.5)'}`, color: isMicOn ? '#86EFAC' : '#F87171', fontSize: '12px', fontWeight: 700 }}
      >
        {isMicOn ? <Mic size={13} /> : <MicOff size={13} />}
        <span>{isMicOn ? (isSpeaking ? '말하는 중' : 'ON') : 'OFF'}</span>
      </div>
    </div>
  );
}
