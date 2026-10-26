import React from 'react';
import { Check, UserRound, X } from 'lucide-react';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import { groupService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import ConfirmAction from './ConfirmAction';

function formatAppliedDate(createdAt) {
  return createdAt ? String(createdAt).split('T')[0] : '';
}

function ApplicationCard({ application, decision, onApprove, onReject }) {
  return (
    <li className="mobile-card mobile-application">
      <p className="mobile-application__header">
        <UserRound size={16} />
        <span className="mobile-application__name">{application.applicantName}</span>
        <span className="mobile-card__meta">{formatAppliedDate(application.createdAt)}</span>
      </p>
      <p className="mobile-paragraph">{application.introduction || '(메시지 없음)'}</p>
      <div className="mobile-card__actions">
        <Button variant="primary" isLoading={decision.isSubmitting} onClick={onApprove}>
          <Check size={16} />
          승인
        </Button>
        <Button variant="secondary" isLoading={decision.isSubmitting} onClick={onReject}>
          <X size={16} />
          거절
        </Button>
      </div>
    </li>
  );
}

export default function LeaderConsole({ groupId, onChanged, onDisbanded }) {
  const applications = useAsync(() => groupService.getApplications(groupId), [groupId]);

  const decision = useSubmit(async ({ applicationId, approve }) => {
    if (approve) {
      await groupService.approveApplication(applicationId);
    } else {
      await groupService.rejectApplication(applicationId);
    }
    await applications.reload();
    onChanged?.();
  });

  const disband = useSubmit(async () => {
    await groupService.deleteGroup(groupId);
    onDisbanded();
  });

  const decide = (applicationId, approve) => decision.submit({ applicationId, approve }).catch(() => {});

  return (
    <>
      <section className="mobile-section">
        <h3 className="mobile-section__title">
          가입 신청 대기자 ({(applications.data || []).length})
        </h3>
        <ScreenState
          query={applications}
          loadingLabel="가입 신청을 불러오는 중입니다"
          emptyWhen={(value) => !value || value.length === 0}
          emptyMessage="대기 중인 신청자가 없습니다."
        >
          <ul className="mobile-list">
            {(applications.data || []).map((application) => (
              <ApplicationCard
                key={application.applicationId}
                application={application}
                decision={decision}
                onApprove={() => decide(application.applicationId, true)}
                onReject={() => decide(application.applicationId, false)}
              />
            ))}
          </ul>
        </ScreenState>
        {decision.errorMessage && <p className="mobile-auth__error">{decision.errorMessage}</p>}
      </section>

      <section className="mobile-section">
        <h3 className="mobile-section__title">스터디 관리</h3>
        <ConfirmAction
          label="스터디 강제 해체"
          confirmMessage="정말로 이 스터디 그룹을 해체하시겠습니까? 해체 시 채팅·퀴즈·자료 등 모든 데이터가 삭제되며 복구할 수 없습니다."
          confirmLabel="해체하기"
          isLoading={disband.isSubmitting}
          onConfirm={() => disband.submit().catch(() => {})}
        />
        {disband.errorMessage && <p className="mobile-auth__error">{disband.errorMessage}</p>}
      </section>
    </>
  );
}
