import React, { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { groupService } from '../../../../services/api';
import { useAsync } from '../../../data/useAsync';
import { FACING_MODE } from '../cameraTrack';
import { isCamStudy } from '../../../../utils/groupStudy.js';
import { isGroupLeader } from '../groupStudyModel';
import { MEDIA_PHASE, describeMediaStatus } from '../mediaJoinModel';
import {
  buildLocalTile,
  buildParticipantTiles,
  countDistinctParticipants,
  indexMemberPhotos,
} from '../participantTileModel';
import { isQuizActive } from '../quizSessionModel';
import { SOCKET_STATE, canRetryManually, describeSocketStatus } from '../socketConnectionModel';
import { useGroupAiChat } from '../useGroupAiChat';
import { useGroupRoom } from '../useGroupRoom';
import ChatPanel from './ChatPanel';
import FullscreenParticipant from './FullscreenParticipant';
import MaterialViewer from './MaterialViewer';
import ParticipantTile from './ParticipantTile';
import ParticipantsPanel from './ParticipantsPanel';
import QuizSessionSheet from './QuizSessionSheet';
import RoomControlBar from './RoomControlBar';
import RoomHeader from './RoomHeader';
import RoomMenu from './RoomMenu';
import RoomSectionBoundary from './RoomSectionBoundary';
import SettingsPanel from './SettingsPanel';
import StudyResourcesPanel from './StudyResourcesPanel';
import { ROOM_PANEL, useRoomOverlay } from './useRoomOverlay';

const PANEL_GROUPS = [
  [ROOM_PANEL.CHAT, ROOM_PANEL.AI],
  [ROOM_PANEL.MATERIALS, ROOM_PANEL.QUIZ, ROOM_PANEL.RANKING],
];

function isSamePanelGroup(currentPanel, requestedPanel) {
  if (currentPanel === requestedPanel) return true;
  return PANEL_GROUPS.some((group) => group.includes(currentPanel) && group.includes(requestedPanel));
}

function useUnreadChat(chatCount, isHistoryLoaded, isChatOpen) {
  const [seenCount, setSeenCount] = useState(null);

  useEffect(() => {
    if (isChatOpen || (seenCount === null && isHistoryLoaded)) setSeenCount(chatCount);
  }, [chatCount, isChatOpen, isHistoryLoaded, seenCount]);

  return seenCount !== null && chatCount > seenCount;
}

function useParticipantTiles({ session, members, userId, displayName, myPhotoUrl }) {
  const memberPhotos = useMemo(() => indexMemberPhotos(members.data), [members.data]);

  const localTile = buildLocalTile({
    userId,
    displayName,
    photoUrl: memberPhotos.get(String(userId)) || myPhotoUrl,
    publisher: session.publisher,
    isCameraOn: session.isCameraOn,
    isMicrophoneOn: session.isMicrophoneOn,
  });

  return buildParticipantTiles({ localTile, remoteParticipants: session.remoteParticipants, memberPhotos });
}

function RoomNotice({ message, tone = 'info', dataAttributes = {}, actionLabel, onAction, onDismiss }) {
  if (!message) return null;

  return (
    <p className={`mobile-room-notice is-${tone}`} role="status" {...dataAttributes}>
      <span>{message}</span>
      {actionLabel && (
        <button type="button" className="mobile-room-notice__action" onClick={onAction}>
          {actionLabel}
        </button>
      )}
      {onDismiss && (
        <button type="button" aria-label="알림 닫기" onClick={onDismiss}>
          <X size={16} />
        </button>
      )}
    </p>
  );
}

function SocketStatusNotice({ room }) {
  if (room.socketState === SOCKET_STATE.CONNECTED || room.socketState === SOCKET_STATE.IDLE) return null;

  return (
    <RoomNotice
      tone={room.socketState === SOCKET_STATE.FAILED ? 'error' : 'info'}
      message={`${describeSocketStatus(room.socketState, room.socketReconnectAttempt)}. 채팅과 퀴즈는 연결되면 다시 동작합니다.`}
      dataAttributes={{ 'data-room-notice': 'socket' }}
      actionLabel={canRetryManually(room.socketState) ? '재연결' : null}
      onAction={room.reconnectSocket}
    />
  );
}

function MediaStatusNotice({ session }) {
  const message = describeMediaStatus(session);
  const isFailed = session.phase === MEDIA_PHASE.FAILED;

  return (
    <RoomNotice
      tone={isFailed ? 'error' : 'info'}
      message={message}
      dataAttributes={{ 'data-room-notice': 'media', 'data-media-phase': session.phase }}
      actionLabel={isFailed ? '화상 다시 연결' : null}
      onAction={session.retry}
    />
  );
}

export default function StudyRoomView({
  groupId,
  group,
  enteredAt,
  session,
  userId,
  displayName,
  myPhotoUrl,
  onLeave,
  onRemoved,
  onDisbanded,
}) {
  const overlay = useRoomOverlay();

  const members = useAsync(() => groupService.getMembers(groupId), [groupId]);
  const materials = useAsync(() => groupService.getGroupMaterials(groupId), [groupId]);
  const quizzes = useAsync(() => groupService.getGroupQuizzes(groupId), [groupId]);

  const room = useGroupRoom(groupId, {
    userId,
    displayName,
    onSelfRemoved: onRemoved,
    onParticipantRemoved: (targetUserId) => {
      session.removeParticipantsByUserId(targetUserId);
      members.reload().catch(() => {});
    },
  });

  const ai = useGroupAiChat(groupId, { displayName, historyMessages: room.aiHistory });

  const participants = useParticipantTiles({ session, members, userId, displayName, myPhotoUrl });
  const onlineUserIds = new Set(participants.map((participant) => String(participant.userId)));
  const focusedParticipant = participants.find(
    (participant) => participant.connectionId === overlay.focusedConnectionId
  );
  const viewerMaterial = (materials.data || []).find(
    (material) => String(material.id) === overlay.viewerMaterialId
  );

  const isParticipantsOpen = overlay.panel === ROOM_PANEL.PARTICIPANTS;
  useEffect(() => {
    if (isParticipantsOpen) members.reload().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isParticipantsOpen]);

  const isChatOpen = overlay.panel === ROOM_PANEL.CHAT;
  const hasUnreadChat = useUnreadChat(room.chatMessages.length, room.history.isSuccess, isChatOpen);
  const isLeader = isGroupLeader(group.data, userId);
  const allowsCamera = isCamStudy(group.data?.studyType);
  const isMirrored = (participant) => participant.isMe && session.facingMode === FACING_MODE.FRONT;
  const showsQuizErrorNotice = Boolean(room.quizError) && !isQuizActive(room.quiz) && overlay.panel !== ROOM_PANEL.QUIZ;

  const togglePanel = (requestedPanel) => {
    if (isSamePanelGroup(overlay.panel, requestedPanel)) {
      overlay.close();
      return;
    }
    overlay.openPanel(requestedPanel);
  };

  const renderPanel = () => {
    switch (overlay.panel) {
      case ROOM_PANEL.MENU:
        return (
          <RoomMenu
            session={session}
            allowsCamera={allowsCamera}
            onOpenPanel={overlay.openPanel}
            onClose={overlay.close}
          />
        );
      case ROOM_PANEL.SETTINGS:
        return (
          <SettingsPanel
            group={group}
            isLeader={isLeader}
            onMembersChanged={() => members.reload().catch(() => {})}
            onDisbanded={onDisbanded}
            onClose={overlay.close}
          />
        );
      case ROOM_PANEL.CHAT:
      case ROOM_PANEL.AI:
        return (
          <ChatPanel
            activeTab={overlay.panel}
            room={room}
            ai={ai}
            userId={userId}
            onChangeTab={overlay.openPanel}
            onClose={overlay.close}
          />
        );
      case ROOM_PANEL.PARTICIPANTS:
        return (
          <ParticipantsPanel
            groupId={groupId}
            group={group.data}
            members={members}
            isLeader={isLeader}
            userId={userId}
            onlineUserIds={onlineUserIds}
            onClose={overlay.close}
          />
        );
      case ROOM_PANEL.MATERIALS:
      case ROOM_PANEL.QUIZ:
      case ROOM_PANEL.RANKING:
        return (
          <StudyResourcesPanel
            groupId={groupId}
            isLeader={isLeader}
            activeTab={overlay.panel}
            room={room}
            materials={materials}
            quizzes={quizzes}
            onChangeTab={overlay.openPanel}
            onOpenViewer={overlay.openViewer}
            onClose={overlay.close}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="mobile-room">
      <RoomHeader
        title={group.data?.title || '그룹스터디'}
        enteredAt={enteredAt}
        participantCount={countDistinctParticipants(participants)}
        socketState={room.socketState}
        onOpenMenu={() => togglePanel(ROOM_PANEL.MENU)}
        onLeave={onLeave}
      />

      <SocketStatusNotice room={room} />
      <MediaStatusNotice session={session} />
      <RoomNotice
        message={session.notice}
        dataAttributes={{ 'data-room-notice': 'media-device' }}
        onDismiss={session.dismissNotice}
      />
      <RoomNotice message={room.chatRecoveryError} tone="error" />
      {showsQuizErrorNotice && <RoomNotice message={room.quizError} onDismiss={room.clearQuizError} />}

      <RoomSectionBoundary sectionName="화상 화면">
        <ul className={participants.length === 1 ? 'mobile-video__grid is-single' : 'mobile-video__grid'}>
          {participants.map((participant) => (
            <ParticipantTile
              key={participant.connectionId}
              participant={participant}
              isMirrored={isMirrored(participant)}
              onExpand={overlay.openFocus}
            />
          ))}
        </ul>
      </RoomSectionBoundary>

      <RoomSectionBoundary key={overlay.panel || 'none'} sectionName="패널">
        {renderPanel()}
      </RoomSectionBoundary>

      <RoomControlBar
        session={session}
        allowsCamera={allowsCamera}
        activePanel={overlay.panel}
        hasUnreadChat={hasUnreadChat}
        onOpenPanel={togglePanel}
      />

      <RoomSectionBoundary sectionName="퀴즈">
        <QuizSessionSheet room={room} userId={userId} />
      </RoomSectionBoundary>

      {overlay.viewerMaterialId && (
        <RoomSectionBoundary sectionName="자료 보기">
          <MaterialViewer
            materialId={overlay.viewerMaterialId}
            title={viewerMaterial?.title || viewerMaterial?.originalFileName}
            onClose={overlay.close}
          />
        </RoomSectionBoundary>
      )}

      {focusedParticipant && (
        <FullscreenParticipant
          participant={focusedParticipant}
          isMirrored={isMirrored(focusedParticipant)}
          onClose={overlay.close}
        />
      )}
    </div>
  );
}
