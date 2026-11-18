import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import ScreenState, { LoadingState } from '../../components/ScreenState';
import { isCamStudy } from '../../../utils/groupStudy.js';
import { resolveMyDisplayName } from './groupStudyModel';
import { enterRoomClock } from './roomClock';
import StudyRoomView from './room/StudyRoomView';
import { useVideoSession } from './useVideoSession';
import VideoPreJoin from './VideoPreJoin';

const GENERAL_ENTRY_MEDIA = Object.freeze({ cameraOn: false, micOn: false });

export default function VideoSessionScreen() {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const { userId, user } = useAuth();
  const displayName = resolveMyDisplayName(user, userId);
  const [hasEnteredRoom, setEnteredRoom] = useState(false);
  const [roomClock, setRoomClock] = useState(null);
  const hasRequestedGeneralEntry = useRef(false);

  const group = useAsync(() => groupService.getGroupDetail(groupId), [groupId]);
  const session = useVideoSession(groupId, { userId, displayName });

  const enterRoom = (mediaOptions) => {
    setEnteredRoom(true);
    setRoomClock((clock) => enterRoomClock(clock, Date.now()));
    session.join(mediaOptions);
  };

  const isGroupLoaded = Boolean(group.data);
  const isCamRoom = isGroupLoaded && isCamStudy(group.data.studyType);

  useEffect(() => {
    if (!isGroupLoaded || isCamRoom || hasRequestedGeneralEntry.current) return;
    hasRequestedGeneralEntry.current = true;
    enterRoom({ ...GENERAL_ENTRY_MEDIA });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGroupLoaded, isCamRoom]);

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

  if (!isGroupLoaded) {
    return (
      <div className="mobile-room-entry">
        <ScreenState query={group} loadingLabel="스터디 정보를 불러오는 중입니다">
          {null}
        </ScreenState>
      </div>
    );
  }

  if (!hasEnteredRoom && isCamRoom) {
    return <VideoPreJoin groupTitle={group.data.title} onJoin={enterRoom} />;
  }

  if (!hasEnteredRoom) {
    return (
      <div className="mobile-room-entry">
        <LoadingState label="스터디룸에 입장하는 중입니다" />
      </div>
    );
  }

  return (
    <StudyRoomView
      groupId={groupId}
      group={group}
      enteredAt={roomClock?.enteredAt}
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
