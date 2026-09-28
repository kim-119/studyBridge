import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import { resolveMyDisplayName } from './groupStudyModel';
import StudyRoomView from './room/StudyRoomView';
import { useVideoSession } from './useVideoSession';
import VideoPreJoin from './VideoPreJoin';

export default function VideoSessionScreen() {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const { userId, user } = useAuth();
  const displayName = resolveMyDisplayName(user, userId);
  const [hasEnteredRoom, setEnteredRoom] = useState(false);

  const group = useAsync(() => groupService.getGroupDetail(groupId), [groupId]);
  const session = useVideoSession(groupId, { userId, displayName });

  const enterRoom = (mediaOptions) => {
    setEnteredRoom(true);
    session.join(mediaOptions);
  };

  const leaveRoom = async () => {
    await session.leave();
    navigate(`/groupstudy/${groupId}`, { replace: true });
  };

  const handleRemoved = async (message) => {
    await session.leave();
    window.alert(message);
    navigate('/groupstudy', { replace: true });
  };

  const handleDisbanded = async () => {
    await session.leave();
    navigate('/groupstudy', { replace: true });
  };

  if (!hasEnteredRoom) {
    return <VideoPreJoin groupTitle={group.data?.title} onJoin={enterRoom} />;
  }

  return (
    <StudyRoomView
      groupId={groupId}
      group={group}
      session={session}
      userId={userId}
      displayName={displayName}
      myPhotoUrl={user?.photoUrl || null}
      onLeave={leaveRoom}
      onRemoved={handleRemoved}
      onDisbanded={handleDisbanded}
    />
  );
}
