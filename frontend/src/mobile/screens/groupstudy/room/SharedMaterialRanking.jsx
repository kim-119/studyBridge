import React, { useEffect, useMemo, useState } from 'react';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import { groupService, materialService } from '../../../../services/api';
import { useAsync } from '../../../data/useAsync';
import { RANKING_STATE, RANKING_STATE_MESSAGE, classifyQuizListError } from '../../archive/materialRankingModel';
import RankingTab from '../../archive/tabs/RankingTab';

function materialLabel(material) {
  const owner = material.mine ? '내 자료' : material.ownerNickname;
  return [material.title || `자료 ${material.materialId}`, owner].filter(Boolean).join(' · ');
}

// 그룹에 공유된 PDF 자료별 퀴즈 랭킹. 순위·점수는 서버 랭킹 API 그대로 표시한다(자료마다 독립 집계).
export default function SharedMaterialRanking({ groupId }) {
  const materials = useAsync(() => groupService.getSharedMaterials(groupId), [groupId]);
  const [selectedId, setSelectedId] = useState(null);
  const list = useMemo(() => (Array.isArray(materials.data) ? materials.data : []), [materials.data]);
  const selected = list.find((material) => String(material.materialId) === String(selectedId)) || null;

  useEffect(() => {
    if (!list.some((material) => String(material.materialId) === String(selectedId))) {
      setSelectedId(list[0]?.materialId ?? null);
    }
  }, [list, selectedId]);

  const blocked = materials.isError ? classifyQuizListError(materials.error) : null;
  if (blocked && blocked !== RANKING_STATE.ERROR) {
    return <EmptyState message={RANKING_STATE_MESSAGE[blocked]} />;
  }

  return (
    <ScreenState
      query={materials}
      loadingLabel="공유된 PDF를 불러오는 중입니다"
      emptyWhen={(value) => !Array.isArray(value) || value.length === 0}
      emptyMessage="이 그룹에 공유된 PDF 자료가 없습니다. 자료보관함의 PDF를 그룹에 공유하면 퀴즈 랭킹을 볼 수 있습니다."
    >
      <>
        {list.length > 1 && (
          <select
            className="mobile-select mobile-archive-fill mobile-section"
            aria-label="랭킹을 볼 PDF 선택"
            value={selectedId ?? ''}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {list.map((material) => (
              <option key={material.materialId} value={material.materialId}>
                {materialLabel(material)}
              </option>
            ))}
          </select>
        )}
        {selected && (
          <RankingTab
            key={selected.materialId}
            material={selected}
            loadQuizzes={materialService.getSharedQuizzes}
            emptyQuizMessage="이 PDF에는 아직 퀴즈가 없어 랭킹이 없습니다."
          />
        )}
      </>
    </ScreenState>
  );
}
