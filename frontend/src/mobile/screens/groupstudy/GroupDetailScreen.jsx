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
import { JOIN_ANSWER_MAX_LENGTH, NICKNAME_MAX_LENGTH } from '../../../utils/groupStudy.js';
import {
  DEFAULT_COVER_IMAGE_URL,
  GUEST_JOIN_MODE,
  MEMBERSHIP,
  buildJoinRequest,
  describeGuestJoin,
  resolveMembership,
} from './groupStudyModel';

function serverMessageOf(action) {
  return action.error?.response?.data?.message || action.errorMessage;
}

function GuestActions({ group, onJoined }) {
  const [joinAnswer, setJoinAnswer] = useState('');
  const [nickname, setNickname] = useState('');
  const [inputError, setInputError] = useState(null);
  const guestJoin = describeGuestJoin(group);

  const apply = useSubmit(async (payload) => {
    await groupService.applyGroup(group.id, payload);
    await onJoined();
  });

  if (guestJoin.mode === GUEST_JOIN_MODE.FULL) {
    return (
      <Button fullWidth disabled>
        정원이 마감되었습니다
      </Button>
    );
  }

  if (guestJoin.mode === GUEST_JOIN_MODE.INVITE_ONLY) {
    return <p className="mobile-notice">비공개 스터디는 방장의 초대 링크로만 참여할 수 있습니다.</p>;
  }

  const join = () => {
    const request = buildJoinRequest(group, { joinAnswer, nickname });
    setInputError(request.error || null);
    if (request.error) return;
    apply.submit(request.payload).catch(() => {});
  };

  return (
    <section className="mobile-section">
      {guestJoin.joinQuestion !== null && (
        <>
          <p className="mobile-paragraph">
            <strong>가입 질문</strong> {guestJoin.joinQuestion}
          </p>
          <TextField
            as="textarea"
            label="가입 질문 답변"
            value={joinAnswer}
            maxLength={JOIN_ANSWER_MAX_LENGTH}
            onChange={(event) => setJoinAnswer(event.target.value)}
          />
        </>
      )}
      {guestJoin.nicknameRule !== null && (
        <TextField
          label="그룹 닉네임"
          hint={`닉네임 규칙: ${guestJoin.nicknameRule}`}
          value={nickname}
          maxLength={NICKNAME_MAX_LENGTH}
          onChange={(event) => setNickname(event.target.value)}
        />
      )}
      <Button fullWidth isLoading={apply.isSubmitting} onClick={join}>
        바로 참여하기
      </Button>
      {inputError && <p className="mobile-auth__error">{inputError}</p>}
      {!inputError && apply.error && <p className="mobile-auth__error">{serverMessageOf(apply)}</p>}
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
