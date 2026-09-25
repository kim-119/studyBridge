import React, { useState } from 'react';
import { CheckCircle2, Circle } from 'lucide-react';
import Button from '../../../components/Button';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { useAsync, useSubmit } from '../../../data/useAsync';

const LEVEL_OPTIONS = [
  { key: 'beginner', label: '초급' },
  { key: 'intermediate', label: '중급' },
  { key: 'advanced', label: '고급' },
];

function stepsOf(roadmap) {
  if (Array.isArray(roadmap?.steps)) return roadmap.steps;

  const data = roadmap?.roadmapData;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.steps)) return data.steps;
  if (Array.isArray(data?.weeks)) return data.weeks;

  return [];
}

export default function RoadmapTab({ materialId }) {
  const roadmap = useAsync(() => materialService.getRoadmap(materialId), [materialId]);
  const [level, setLevel] = useState('intermediate');

  const regenerate = useSubmit(async () => {
    await materialService.regenerateRoadmap(materialId, level);
    await roadmap.reload();
  });

  const toggleTask = useSubmit(async (stepId) => {
    await materialService.toggleRoadmapTask(materialId, stepId);
    await roadmap.reload();
  });

  const steps = stepsOf(roadmap.data);

  return (
    <ScreenState query={roadmap} loadingLabel="로드맵을 불러오는 중입니다">
      <>
        <section className="mobile-card mobile-section">
          <div className="mobile-toolbar">
            <select
              className="mobile-select"
              aria-label="난이도"
              value={level}
              onChange={(event) => setLevel(event.target.value)}
            >
              {LEVEL_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <Button
            fullWidth
            isLoading={regenerate.isSubmitting}
            onClick={() => regenerate.submit().catch(() => {})}
          >
            로드맵 생성
          </Button>

          {regenerate.errorMessage && <p className="mobile-auth__error">{regenerate.errorMessage}</p>}
        </section>

        {steps.length === 0 ? (
          <EmptyState message="아직 생성된 로드맵이 없습니다." />
        ) : (
          <ul className="mobile-list">
            {steps.map((step, index) => {
              const stepId = step.stepId ?? step.id ?? index;
              const isCompleted = Boolean(step.completed ?? step.isCompleted);

              return (
                <li key={stepId} className="mobile-card">
                  <button
                    type="button"
                    className="mobile-roadmap__step"
                    disabled={step.stepId == null}
                    onClick={() => toggleTask.submit(step.stepId).catch(() => {})}
                  >
                    {isCompleted ? (
                      <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
                    ) : (
                      <Circle size={20} className="mobile-roadmap__check" />
                    )}

                    <span>
                      <strong>
                        {step.stepOrder ? `${step.stepOrder}주차` : `${index + 1}단계`} · {step.title || step.topic}
                      </strong>
                      {step.description && <span>{step.description}</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </>
    </ScreenState>
  );
}
