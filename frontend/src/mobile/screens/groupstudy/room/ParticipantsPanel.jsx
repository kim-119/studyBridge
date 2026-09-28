import React from 'react';
import { UserRound } from 'lucide-react';
import ListRow from '../../../components/ListRow';
import ScreenState from '../../../components/ScreenState';
import { groupService } from '../../../../services/api';
import { useSubmit } from '../../../data/useAsync';
import ConfirmAction from '../ConfirmAction';
import RoomPanel from './RoomPanel';

function describeMember(member, onlineUserIds) {
  const isOnline = onlineUserIds.has(String(member.userId));
  return [member.role === 'LEADER' ? '방장' : '멤버', isOnline ? '접속 중' : null].filter(Boolean).join(' · ');
}

export default function ParticipantsPanel({ groupId, members, isLeader, userId, onlineUserIds, onClose }) {
  const kick = useSubmit(async (memberUserId) => {
    await groupService.kickMember(groupId, memberUserId);
    await members.reload();
  });

  const canKick = (member) => isLeader && member.role !== 'LEADER' && String(member.userId) !== String(userId);

  return (
    <RoomPanel title="참여자" onClose={onClose}>
      <ScreenState
        query={members}
        loadingLabel="참여자를 불러오는 중입니다"
        emptyWhen={(value) => !value || value.length === 0}
        emptyMessage="참여 멤버가 없습니다."
      >
        <ul className="mobile-list">
          {(members.data || []).map((member) => (
            <li key={member.userId}>
              <ListRow
                icon={<UserRound size={20} />}
                title={String(member.userId) === String(userId) ? `${member.displayName} (나)` : member.displayName}
                subtitle={describeMember(member, onlineUserIds)}
              />
              {canKick(member) && (
                <ConfirmAction
                  label="강제 퇴장"
                  confirmMessage={`${member.displayName} 멤버를 강제 퇴장시키겠습니까?`}
                  confirmLabel="퇴장시키기"
                  isLoading={kick.isSubmitting}
                  onConfirm={() => kick.submit(member.userId).catch(() => {})}
                />
              )}
            </li>
          ))}
        </ul>
      </ScreenState>
      {kick.errorMessage && <p className="mobile-auth__error">{kick.errorMessage}</p>}
    </RoomPanel>
  );
}
