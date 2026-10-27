export const LOCAL_TILE_ID = 'local';

// OpenVidu 구독 스트림은 typeOfVideo('CAMERA'|'SCREEN'|'CUSTOM'|'IPCAM')를 전파한다(openvidu-browser 2.30).
// PC 화면공유는 getDisplayMedia 로 송출되어 typeOfVideo='SCREEN' 으로 수신된다.
export const VIDEO_KIND = Object.freeze({ CAMERA: 'CAMERA', SCREEN: 'SCREEN' });

export function resolveVideoKind(stream) {
  return String(stream?.typeOfVideo || '').toUpperCase() === VIDEO_KIND.SCREEN
    ? VIDEO_KIND.SCREEN
    : VIDEO_KIND.CAMERA;
}

export function describeStreamMedia(stream) {
  if (!stream) {
    return { cameraOn: false, micOn: false, screenOn: false, videoKind: VIDEO_KIND.CAMERA, streamId: null };
  }

  const videoKind = resolveVideoKind(stream);
  const videoActive = Boolean(stream.hasVideo !== false && stream.videoActive);
  const isScreen = videoKind === VIDEO_KIND.SCREEN;

  return {
    videoKind,
    streamId: stream.streamId || null,
    // 카메라와 화면공유를 분리한다: 같은 사용자라도 서로 다른 Connection 이므로 한 타일이 다른 타일을 덮어쓰지 않는다.
    cameraOn: !isScreen && videoActive,
    screenOn: isScreen && videoActive,
    micOn: Boolean(stream.hasAudio !== false && stream.audioActive),
  };
}

export function indexMemberPhotos(members) {
  const photos = new Map();
  (Array.isArray(members) ? members : []).forEach((member) => {
    if (member?.userId != null && member.photoUrl) photos.set(String(member.userId), member.photoUrl);
  });
  return photos;
}

export function buildLocalTile({ userId, displayName, photoUrl, publisher, isCameraOn, isMicrophoneOn }) {
  const media = describeStreamMedia(publisher?.stream);
  return {
    connectionId: LOCAL_TILE_ID,
    userId,
    name: displayName,
    isMe: true,
    isScreenShare: false,
    videoKind: VIDEO_KIND.CAMERA,
    streamId: media.streamId,
    photoUrl: photoUrl || null,
    streamManager: publisher || null,
    cameraOn: Boolean(publisher && isCameraOn && media.cameraOn),
    screenOn: false,
    micOn: Boolean(publisher && isMicrophoneOn && media.micOn),
  };
}

export function buildParticipantTiles({ localTile, remoteParticipants, memberPhotos }) {
  const remoteTiles = (remoteParticipants || []).map((participant) => {
    const isScreenShare = participant.videoKind === VIDEO_KIND.SCREEN;
    return {
      ...participant,
      isMe: false,
      isScreenShare,
      photoUrl: memberPhotos.get(String(participant.userId)) || null,
      // 화면공유 타일은 카메라 상태와 독립적으로 영상 활성 여부(screenOn)만으로 표시한다.
      cameraOn: Boolean(participant.streamManager && participant.cameraOn && !isScreenShare),
      screenOn: Boolean(participant.streamManager && participant.screenOn && isScreenShare),
      micOn: Boolean(participant.streamManager && participant.micOn),
    };
  });

  return [localTile, ...remoteTiles];
}

export function countDistinctParticipants(participants) {
  const identities = new Set();
  (participants || []).forEach((participant) => {
    // 화면공유(SCREEN) 연결은 같은 사용자의 추가 Connection 이므로 인원 수에 포함하지 않는다.
    if (participant.isScreenShare) return;
    const hasUserId = participant.userId !== undefined && participant.userId !== null;
    identities.add(hasUserId ? `user:${participant.userId}` : `connection:${participant.connectionId}`);
  });
  return identities.size;
}
