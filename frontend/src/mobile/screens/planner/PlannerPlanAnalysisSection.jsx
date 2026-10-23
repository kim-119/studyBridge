import React, { useState } from 'react';
import { ChevronDown, Download, RefreshCw, Sparkles } from 'lucide-react';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import { plannerService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { extractDownloadUrl } from '../../platform/downloadUrl';
import { openExternalUrl } from '../../platform/externalLink';
import {
  DEFAULT_START_TIME,
  activityTypeLabel,
  alignmentLevelLabel,
  analysisPrerequisites,
  analysisTimeLabel,
  buildSchedulePreview,
  isAnalysisEmpty,
} from './planAnalysisModel';

function AnalysisCard({ title, action, children }) {
  return (
    <section className="mobile-card mobile-section">
      <div className="mobile-planner-analysis__header">
        <h3 className="mobile-section__title">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function OverviewCard({ analysis, rerunButton }) {
  const checklist = analysis.checklistProgress || { total: 0, completed: 0, percent: 0 };
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings.filter(Boolean) : [];

  return (
    <AnalysisCard title={analysis.title || 'AI 계획 분석'} action={rerunButton}>
      {analysis.learningGoal && <p className="mobile-paragraph">{analysis.learningGoal}</p>}

      <ul className="mobile-chips mobile-planner-analysis__chips">
        <li>{analysisTimeLabel(analysis)}</li>
        {analysis.subject && <li>{analysis.subject}</li>}
      </ul>

      {analysis.summary && <p className="mobile-paragraph">{analysis.summary}</p>}

      <p className="mobile-card__meta mobile-planner-analysis__progress-label">
        체크리스트 진행 {checklist.completed || 0}/{checklist.total || 0} ({checklist.percent || 0}%)
      </p>
      <div className="mobile-progress">
        <span style={{ width: `${Math.max(0, Math.min(100, checklist.percent || 0))}%` }} />
      </div>

      {warnings.length > 0 && (
        <ul className="mobile-bullets">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </AnalysisCard>
  );
}

function GoalAlignmentCard({ goal }) {
  const issues = Array.isArray(goal.issues) ? goal.issues : [];

  return (
    <AnalysisCard
      title="목표 정합성"
      action={<span className="mobile-planner-analysis__badge">{alignmentLevelLabel(goal.level)}</span>}
    >
      {goal.summary && <p className="mobile-paragraph">{goal.summary}</p>}
      {goal.reason && <p className="mobile-card__meta">{goal.reason}</p>}

      {issues.length > 0 && (
        <>
          <p className="mobile-roadmap-detail__label">정합성 점검</p>
          <ul className="mobile-bullets">
            {issues.map((issue, position) => (
              <li key={position}>{typeof issue === 'string' ? issue : issue?.reason || issue?.name || ''}</li>
            ))}
          </ul>
        </>
      )}
    </AnalysisCard>
  );
}

function PrerequisitesCard({ analysis }) {
  const prerequisites = analysisPrerequisites(analysis);

  return (
    <AnalysisCard title="선행 개념 · 학습 전 확인 권장">
      {prerequisites.length === 0 ? (
        <p className="mobile-card__meta">이 계획에 대해 별도로 확인이 권장되는 선행 개념이 없습니다.</p>
      ) : (
        <ul className="mobile-bullets">
          {prerequisites.map((prerequisite, position) => (
            <li key={`${prerequisite.name}-${position}`}>
              <strong>{prerequisite.name}</strong>
              {prerequisite.reason && <p className="mobile-card__meta">{prerequisite.reason}</p>}
            </li>
          ))}
        </ul>
      )}
    </AnalysisCard>
  );
}

function ActivityDetail({ task }) {
  const sequence = Array.isArray(task.learningSequence) ? task.learningSequence.filter(Boolean) : [];
  const alignment = task.goalAlignment || {};

  return (
    <div className="mobile-planner-analysis__detail">
      <p className="mobile-card__meta">
        유형 {activityTypeLabel(task.type)} · 권장시간 {task.recommendedMinutes ?? 0}분
        {alignment.level && ` · 목표 정합성 ${alignmentLevelLabel(alignment.level)}`}
      </p>
      {alignment.reason && <p className="mobile-paragraph">{alignment.reason}</p>}
      {task.description && <p className="mobile-paragraph">{task.description}</p>}
      {task.whyImportant && <p className="mobile-paragraph">{task.whyImportant}</p>}
      {sequence.length > 0 && <p className="mobile-card__meta">권장 순서: {sequence.join(' → ')}</p>}
    </div>
  );
}

function ActivitiesCard({ tasks }) {
  const [expandedKey, setExpandedKey] = useState(null);

  if (tasks.length === 0) return null;

  return (
    <AnalysisCard title="학습 활동">
      <ul className="mobile-list">
        {tasks.map((task, position) => {
          const key = task.id ?? task.order ?? position;
          const isExpanded = expandedKey === key;

          return (
            <li key={key} className="mobile-planner-analysis__activity">
              <button
                type="button"
                className="mobile-planner-analysis__activity-toggle"
                aria-expanded={isExpanded}
                onClick={() => setExpandedKey(isExpanded ? null : key)}
              >
                <span>
                  <strong>{task.title}</strong>
                  <span className="mobile-card__meta">
                    {activityTypeLabel(task.type)} · {task.recommendedMinutes ?? 0}분
                  </span>
                </span>
                <ChevronDown size={18} className={isExpanded ? 'is-open' : ''} />
              </button>
              {isExpanded && <ActivityDetail task={task} />}
            </li>
          );
        })}
      </ul>
    </AnalysisCard>
  );
}

function DailyScheduleCard({ plannerId, analysis }) {
  const [startTime, setStartTime] = useState(DEFAULT_START_TIME);
  const rows = buildSchedulePreview(analysis, startTime);

  const downloadSchedulePdf = useSubmit(async () => {
    const response = await plannerService.generateSchedulePdf(plannerId, startTime);
    const url = extractDownloadUrl(response);
    if (!url) throw new Error('PDF 생성 실패');
    await openExternalUrl(url);
  });

  return (
    <AnalysisCard title="하루 학습 시간표">
      <TextField
        label="학습 시작 시간"
        type="time"
        value={startTime}
        onChange={(event) => setStartTime(event.target.value || DEFAULT_START_TIME)}
      />

      <Button
        fullWidth
        variant="secondary"
        isLoading={downloadSchedulePdf.isSubmitting}
        onClick={() => downloadSchedulePdf.submit().catch(() => {})}
      >
        <Download size={16} />
        PDF 다운로드
      </Button>
      {downloadSchedulePdf.errorMessage && (
        <p className="mobile-auth__error mobile-roadmap__error">{downloadSchedulePdf.errorMessage}</p>
      )}

      {rows.length === 0 ? (
        <p className="mobile-card__meta">표시할 학습 활동이 없습니다.</p>
      ) : (
        <ul className="mobile-list mobile-planner-analysis__schedule">
          {rows.map((row) => (
            <li key={row.key} className="mobile-planner-analysis__slot">
              <strong>
                {row.startTime} ~ {row.endTime}
              </strong>
              <span>{row.title}</span>
              <span className="mobile-card__meta">{activityTypeLabel(row.type)}</span>
            </li>
          ))}
        </ul>
      )}

      <p className="mobile-card__meta">총 학습시간 {analysis.totalRecommendedMinutes ?? 0}분</p>
    </AnalysisCard>
  );
}

function AnalysisResult({ plannerId, analysis, isAnalyzing, onRerun }) {
  const rerunButton = (
    <Button variant="ghost" isLoading={isAnalyzing} onClick={onRerun}>
      <RefreshCw size={16} />
      다시 분석
    </Button>
  );

  return (
    <>
      {analysis.stale && (
        <p className="mobile-notice mobile-section">플래너 내용이 바뀌었어요. 다시 분석하기를 눌러 최신 내용으로 분석하세요.</p>
      )}
      <OverviewCard analysis={analysis} rerunButton={rerunButton} />
      <GoalAlignmentCard goal={analysis.goalAlignment || {}} />
      <PrerequisitesCard analysis={analysis} />
      <ActivitiesCard tasks={Array.isArray(analysis.tasks) ? analysis.tasks : []} />
      <DailyScheduleCard plannerId={plannerId} analysis={analysis} />
    </>
  );
}

export default function PlannerPlanAnalysisSection({ plannerId }) {
  const analysis = useAsync(() => plannerService.getPlanAnalysis(plannerId), [plannerId]);

  const runAnalysis = useSubmit(async () => {
    const result = await plannerService.analyzePlan(plannerId);
    analysis.setData(result || null);
    if (result?.errorCode) throw new Error(result.summary || '분석 중 문제가 발생했습니다.');
  });

  const startAnalysis = () => runAnalysis.submit().catch(() => {});

  return (
    <>
      {runAnalysis.errorMessage && <p className="mobile-auth__error">{runAnalysis.errorMessage}</p>}

      <ScreenState query={analysis} loadingLabel="AI 계획 분석을 불러오는 중입니다">
        {isAnalysisEmpty(analysis.data) ? (
          <AnalysisCard title="AI 계획 분석">
            <p className="mobile-paragraph">
              아직 분석 결과가 없습니다. AI 계획 분석을 실행하면 학습 목표 정합성, 선수지식, 학습 흐름과 하루
              시간표까지 구조적으로 정리해드립니다.
            </p>
            <Button fullWidth isLoading={runAnalysis.isSubmitting} onClick={startAnalysis}>
              <Sparkles size={16} />
              AI 계획 분석 실행
            </Button>
          </AnalysisCard>
        ) : (
          <AnalysisResult
            plannerId={plannerId}
            analysis={analysis.data}
            isAnalyzing={runAnalysis.isSubmitting}
            onRerun={startAnalysis}
          />
        )}
      </ScreenState>
    </>
  );
}
