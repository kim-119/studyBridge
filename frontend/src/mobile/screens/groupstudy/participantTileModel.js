export const LOCAL_TILE_ID = 'local';

export function describeStreamMedia(stream) {
  if (!stream) return { cameraOn: false, micOn: false };
  return {
    cameraOn: Boolean(stream.hasVideo !== false && stream.videoActive),
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
    photoUrl: photoUrl || null,
    streamManager: publisher || null,
    cameraOn: Boolean(publisher && isCameraOn && media.cameraOn),
    micOn: Boolean(publisher && isMicrophoneOn && media.micOn),
  };
}

export function buildParticipantTiles({ localTile, remoteParticipants, memberPhotos }) {
  const remoteTiles = (remoteParticipants || []).map((participant) => ({
    ...participant,
    isMe: false,
    photoUrl: memberPhotos.get(String(participant.userId)) || null,
    cameraOn: Boolean(participant.streamManager && participant.cameraOn),
    micOn: Boolean(participant.streamManager && participant.micOn),
  }));

  return [localTile, ...remoteTiles];
}
