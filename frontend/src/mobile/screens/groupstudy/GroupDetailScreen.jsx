import React, { useState } from 'react';
import { Download, FileText, UserRound, Video } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ListRow from '../../components/ListRow';
import ScreenState from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { groupService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { openExternalUrl } from '../../platform/externalLink';

const DETAIL_TABS = [
  { key: 'overview', label: '소개' },
  { key: 'members', label: '참여자' },
  { key: 'materials', label: '학습자료' },
];

function MembersTab({ groupId }) {
  const members = useAsync(() => groupService.getMembers(groupId), [groupId]);

  return (
    <ScreenState
      query={members}
      loadingLabel="참여자를 불러오는 중입니다"
      emptyWhen={(value) => !value || value.length === 0}
      emptyMessage="아직 참여자가 없습니다."
    >
      <ul className="mobile-list">
        {(members.data || []).map((member) => (
          <li key={member.userId}>
            <ListRow
              icon={<UserRound size={20} />}
              title={member.displayName}
              subtitle={member.major}
              meta={member.role}
            />
          </li>
        ))}
      </ul>
    </ScreenState>
  );
}

function MaterialsTab({ groupId }) {
  const materials = useAsync(() => groupService.getGroupMaterials(groupId), [groupId]);

  const download = useSubmit(async (materialId) => {
    const response = await groupService.getGroupMaterialDownloadUrl(materialId);
    await openExternalUrl(response?.presignedUrl || response?.url || response);
  });

  return (
    <ScreenState
      query={materials}
      loadingLabel="학습자료를 불러오는 중입니다"
      emptyWhen={(value) => !value || value.length === 0}
      emptyMessage="공유된 학습자료가 없습니다."
    >
      <ul className="mobile-list">
        {(materials.data || []).map((material) => (
          <li key={material.id ?? material.materialId}>
            <ListRow
              icon={<FileText size={20} />}
              title={material.title}
              subtitle={material.originalFileName}
              onClick={() => download.submit(material.id ?? material.materialId).catch(() => {})}
              trailing={<Download size={18} />}
            />
          </li>
        ))}
      </ul>
    </ScreenState>
  );
}

function OverviewTab({ group, onJoin, joinAction }) {
  return (
    <>
      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">
          {[group?.leaderName, `${group?.currentCount ?? 0}/${group?.capacity ?? 0}명`, group?.status]
            .filter(Boolean)
            .join(' · ')}
        </p>

        {group?.hashtags && (
          <ul className="mobile-chips">
            {group.hashtags
              .split(',')
              .map((tag) => tag.trim())
              .filter(Boolean)
              .map((tag) => (
                <li key={tag}>#{tag}</li>
              ))}
          </ul>
        )}

        <p className="mobile-paragraph">{group?.description || '소개가 없습니다.'}</p>
      </section>

      <Button fullWidth isLoading={joinAction.isSubmitting} onClick={onJoin}>
        스터디 참여 신청
      </Button>

      {joinAction.errorMessage && <p className="mobile-auth__error">{joinAction.errorMessage}</p>}
    </>
  );
}

export default function GroupDetailScreen() {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState(DETAIL_TABS[0].key);

  const group = useAsync(() => groupService.getGroupDetail(groupId), [groupId]);

  const applyToGroup = useSubmit(async () => {
    await groupService.applyGroup(groupId, { message: '모바일에서 참여를 신청합니다.' });
    await group.reload();
  });

  return (
    <MobileScreen
      title={group.data?.title || '그룹스터디'}
      showBackButton
      actions={
        <button
          type="button"
          className="mobile-app-bar__action"
          aria-label="화상 스터디 입장"
          onClick={() => navigate(`/groupstudy/${groupId}/video`)}
        >
          <Video size={22} />
        </button>
      }
    >
      <ScreenState query={group} loadingLabel="스터디 정보를 불러오는 중입니다">
        <>
          <SubTabs tabs={DETAIL_TABS} activeKey={activeTab} onChange={setActiveTab} />

          {activeTab === 'overview' && (
            <OverviewTab
              group={group.data}
              joinAction={applyToGroup}
              onJoin={() => applyToGroup.submit().catch(() => {})}
            />
          )}
          {activeTab === 'members' && <MembersTab groupId={groupId} />}
          {activeTab === 'materials' && <MaterialsTab groupId={groupId} />}
        </>
      </ScreenState>
    </MobileScreen>
  );
}
