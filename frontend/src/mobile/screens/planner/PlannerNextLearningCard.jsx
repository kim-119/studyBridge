import React from 'react';
import { ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import { plannerService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import { splitRoadmapTitle } from './plannerAdapter';
import { completionPercent, nextLearningOrderLabel } from './planAnalysisModel';

function nextLearningPath(nextLearning) {
  if (nextLearning.nextPlannerId != null) return `/planner/${nextLearning.nextPlannerId}`;
  if (nextLearning.nextMaterialId != null) return `/archive/${nextLearning.nextMaterialId}`;
  return null;
}

function CompletionProgress({ nextLearning }) {
  const percent = completionPercent(nextLearning);

  if (percent == null) {
    return (
      <p className="mobile-card__meta">
        체크리스트가 없어 이행도를 확인할 수 없습니다. AI 계획 분석의 체크리스트를 완료하면 반영됩니다.
      </p>
    );
  }

  return (
    <>
      <p className="mobile-card__meta">
        현재 계획 이행도 {percent}% ({nextLearning.checklistCompleted}/{nextLearning.checklistTotal})
      </p>
      <div className="mobile-progress">
        <span style={{ width: `${percent}%` }} />
      </div>
    </>
  );
}

function NextLearningBody({ nextLearning }) {
  const navigate = useNavigate();

  if (!nextLearning.available) {
    return (
      <>
        <p className="mobile-paragraph">{nextLearning.reason || '현재 등록된 다음 학습 계획이 없습니다.'}</p>
        {completionPercent(nextLearning) != null && <CompletionProgress nextLearning={nextLearning} />}
      </>
    );
  }

  const path = nextLearningPath(nextLearning);
  const isInProgress = nextLearning.status === 'IN_PROGRESS';

  return (
    <>
      <p className="mobile-card__meta">{nextLearningOrderLabel(nextLearning)}</p>
      <p className="mobile-quiz__stem">{splitRoadmapTitle(nextLearning.title || '').topic}</p>
      <p className="mobile-card__meta">
        {[nextLearning.subject && `과목 ${nextLearning.subject}`, nextLearning.plannerDate && `예정일 ${nextLearning.plannerDate}`]
          .filter(Boolean)
          .join(' · ')}
      </p>
      <p className="mobile-paragraph">
        {isInProgress
          ? '현재 계획을 먼저 마무리해 주세요. 완료한 뒤 이어서 학습할 수 있습니다.'
          : '현재 계획을 완료한 뒤 이어서 학습할 수 있습니다.'}
      </p>

      <CompletionProgress nextLearning={nextLearning} />

      {nextLearning.reason && <p className="mobile-card__meta">{nextLearning.reason}</p>}

      <Button
        fullWidth
        variant={nextLearning.status === 'READY' ? 'primary' : 'secondary'}
        disabled={!path}
        onClick={() => navigate(path)}
      >
        다음 학습 보기
        <ArrowRight size={16} />
      </Button>
    </>
  );
}

export default function PlannerNextLearningCard({ plannerId }) {
  const nextLearning = useAsync(() => plannerService.getNextLearning(plannerId), [plannerId]);

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">다음 학습 추천</h3>

      <ScreenState
        query={nextLearning}
        loadingLabel="다음 학습 순서를 확인하는 중입니다"
        emptyWhen={(value) => !value}
        emptyMessage="다음 학습 정보가 없습니다."
      >
        {nextLearning.data && <NextLearningBody nextLearning={nextLearning.data} />}
      </ScreenState>
    </section>
  );
}
