import React from 'react';
import { UserRound } from 'lucide-react';
import ScreenState from '../../../components/ScreenState';
import { groupService } from '../../../../services/api';
import { useSubmit } from '../../../data/useAsync';
import ConfirmAction from '../ConfirmAction';
import RoomPanel from './RoomPanel';
import { buildParticipantRoster } from './participantRoster';
import './groupRoom.css';

function ParticipantCard({ entry }) {
  return (
    <div className="mobile-row mobile-participant__card">
      <span className="mobile-row__icon">
        <UserRound size={20} />
      </span>

      <span className="mobile-row__body">
        <span className="mobile-participant__name-line">
          <span className="mobile-row__title mobile-participant__name">{entry.name}</span>
          {entry.isMe && <span className="mobile-participant__me">(나)</span>}
          <span className={entry.isLeader ? 'mobile-group-badge' : 'mobile-group-badge is-private'}>
            {entry.isLeader ? '방장' : '멤버'}
          </span>
        </span>
        <span className="mobile-row__subtitle">획득 점수: {entry.points.toLocaleString('ko-KR')}점</span>
      </span>

      <span className={entry.isOnline ? 'mobile-participant__presence is-online' : 'mobile-participant__presence'}>
        {entry.isOnline ? '온라인' : '오프라인'}
      </span>
    </div>
  );
}

export default function ParticipantsPanel({ groupId, group, members, isLeader, userId, onlineUserIds, onClose }) {
  const kick = useSubmit(async (memberUserId) => {
    await groupService.kickMember(groupId, memberUserId);
    await members.reload();
  });

  const roster = buildParticipantRoster({
    members: members.data,
    leaderId: group?.leaderId,
    userId,
    onlineUserIds,
  });

  const canKick = (entry) => isLeader && !entry.isLeader && !entry.isMe;

  return (
    <RoomPanel title="참여자" onClose={onClose}>
      <ScreenState
        query={members}
        loadingLabel="참여자를 불러오는 중입니다"
        emptyWhen={(value) => !value || value.length === 0}
        emptyMessage="참여 멤버가 없습니다."
      >
        <ul className="mobile-list">
          {roster.map((entry) => (
            <li key={entry.userId} className="mobile-participant" data-member-id={String(entry.userId)}>
              <ParticipantCard entry={entry} />
              {canKick(entry) && (
                <div className="mobile-participant__actions">
                  <ConfirmAction
                    label="강제 퇴장"
                    confirmMessage={`${entry.name} 멤버를 강제 퇴장시키겠습니까?`}
                    confirmLabel="퇴장시키기"
                    isLoading={kick.isSubmitting}
                    onConfirm={() => kick.submit(entry.userId).catch(() => {})}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      </ScreenState>
      {kick.errorMessage && <p className="mobile-auth__error">{kick.errorMessage}</p>}
    </RoomPanel>
  );
}
