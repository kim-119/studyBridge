import React, { useState } from 'react';
import { DoorOpen, LogOut } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import ConfirmAction from './ConfirmAction';
import GroupInfoCard from './GroupInfoCard';
import LeaderConsole from './LeaderConsole';
import StudyTimerCard from './StudyTimerCard';
import { DEFAULT_COVER_IMAGE_URL, MEMBERSHIP, resolveMembership } from './groupStudyModel';

const PRIVATE_APPLY_DEFAULT_MESSAGE = '안녕하세요! 가입 신청합니다.';
const PUBLIC_JOIN_MESSAGE = '공개 스터디 바로 참가';

function serverMessageOf(action) {
  return action.error?.response?.data?.message || action.errorMessage;
}

function GuestActions({ group, onJoined }) {
  const [introduction, setIntroduction] = useState('');
  const [hasApplied, setApplied] = useState(false);
  const isFull = Number(group.currentCount) >= Number(group.capacity);

  const apply = useSubmit(async () => {
    if (group.isPublic) {
      await groupService.applyGroup(group.id, { introduction: PUBLIC_JOIN_MESSAGE });
      await onJoined();
      return;
    }

    await groupService.applyGroup(group.id, {
      introduction: introduction.trim() || PRIVATE_APPLY_DEFAULT_MESSAGE,
    });
    setApplied(true);
  });

  if (hasApplied) {
    return (
      <p className="mobile-notice">신청 완료! 방장의 승인을 기다려주세요. 승인되면 스터디룸에 입장할 수 있습니다.</p>
    );
  }

  if (isFull) {
    return (
      <Button fullWidth disabled>
        정원이 마감되었습니다
      </Button>
    );
  }

  return (
    <section className="mobile-section">
      {!group.isPublic && (
        <TextField
          as="textarea"
          label="방장에게 보낼 참가 신청 메시지 (선택)"
          value={introduction}
          placeholder="자기소개나 각오 등 방장에게 어필할 메시지를 남겨보세요!"
          onChange={(event) => setIntroduction(event.target.value)}
        />
      )}
      <Button fullWidth isLoading={apply.isSubmitting} onClick={() => apply.submit().catch(() => {})}>
        {group.isPublic ? '바로 참여하기' : '참가 신청'}
      </Button>
      {apply.error && <p className="mobile-auth__error">{serverMessageOf(apply)}</p>}
    </section>
  );
}

function MemberActions({ groupId, membership, onEnter, onLeft }) {
  const leave = useSubmit(async () => {
    await groupService.leaveGroup(groupId);
    onLeft();
  });

  return (
    <section className="mobile-section">
      <Button fullWidth onClick={onEnter}>
        <DoorOpen size={18} />
        스터디룸 입장
      </Button>

      {membership === MEMBERSHIP.MEMBER && (
        <div className="mobile-group-detail__leave">
          <ConfirmAction
            label={
              <>
                <LogOut size={16} />
                스터디 나가기
              </>
            }
            confirmMessage="이 스터디에서 탈퇴하시겠습니까? 다시 참여하려면 새로 신청해야 합니다."
            confirmLabel="나가기"
            isLoading={leave.isSubmitting}
            onConfirm={() => leave.submit().catch(() => {})}
          />
          {leave.error && <p className="mobile-auth__error">{serverMessageOf(leave)}</p>}
        </div>
      )}
    </section>
  );
}

export default function GroupDetailScreen() {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

  const group = useAsync(() => groupService.getGroupDetail(groupId), [groupId]);
  const members = useAsync(() => groupService.getMembers(groupId), [groupId]);
  const membership = resolveMembership(group.data, members.data, userId);
  const isJoined = membership !== MEMBERSHIP.GUEST;

  const reloadGroup = async () => {
    await Promise.all([group.reload(), members.reload()]);
  };

  const backToList = () => navigate('/groupstudy', { replace: true });

  return (
    <MobileScreen title={group.data?.title || '그룹스터디'} showBackButton>
      <ScreenState query={group} loadingLabel="스터디 정보를 불러오는 중입니다">
        {group.data && (
          <>
            <img
              className="mobile-group-detail__cover"
              src={group.data.coverImageUrl || DEFAULT_COVER_IMAGE_URL}
              alt=""
            />

            <GroupInfoCard group={group.data} />

            <ScreenState query={members} loadingLabel="참여 정보를 확인하는 중입니다">
              {isJoined ? (
                <MemberActions
                  groupId={groupId}
                  membership={membership}
                  onEnter={() => navigate(`/groupstudy/${groupId}/video`)}
                  onLeft={backToList}
                />
              ) : (
                <GuestActions group={group.data} onJoined={reloadGroup} />
              )}
            </ScreenState>

            {isJoined && <StudyTimerCard groupId={groupId} />}

            {membership === MEMBERSHIP.LEADER && (
              <LeaderConsole
                groupId={groupId}
                onChanged={() => reloadGroup().catch(() => {})}
                onDisbanded={backToList}
              />
            )}
          </>
        )}
      </ScreenState>
    </MobileScreen>
  );
}
