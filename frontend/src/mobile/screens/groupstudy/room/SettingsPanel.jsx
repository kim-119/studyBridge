import React from 'react';
import ScreenState from '../../../components/ScreenState';
import GroupInfoCard from '../GroupInfoCard';
import LeaderConsole from '../LeaderConsole';
import RoomPanel from './RoomPanel';

export default function SettingsPanel({ group, isLeader, onMembersChanged, onDisbanded, onClose }) {
  return (
    <RoomPanel title="그룹스터디 설정" onClose={onClose}>
      <ScreenState query={group} loadingLabel="스터디 정보를 불러오는 중입니다">
        <>
          {group.data && <GroupInfoCard group={group.data} />}
          {isLeader && group.data && (
            <LeaderConsole
              groupId={group.data.id}
              onChanged={() => {
                group.reload().catch(() => {});
                onMembersChanged();
              }}
              onDisbanded={onDisbanded}
            />
          )}
        </>
      </ScreenState>
    </RoomPanel>
  );
}
