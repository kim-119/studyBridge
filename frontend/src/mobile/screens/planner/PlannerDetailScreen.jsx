import React from 'react';
import { CalendarPlus, Download, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { extractDownloadUrl } from '../../platform/downloadUrl';
import { openExternalUrl } from '../../platform/externalLink';
import { toPlannerDetail } from './plannerAdapter';

export default function PlannerDetailScreen() {
  const { plannerId } = useParams();
  const navigate = useNavigate();

  const planner = useAsync(
    async () => toPlannerDetail(await plannerService.getPlanner(plannerId)),
    [plannerId]
  );

  const registerSchedule = useSubmit(async () => {
    await plannerService.registerSchedule(plannerId);
    await planner.reload();
  });

  const downloadPdf = useSubmit(async () => {
    const response = await plannerService.getDownloadUrl(plannerId);
    await openExternalUrl(extractDownloadUrl(response));
  });

  const removePlanner = useSubmit(async () => {
    await plannerService.deletePlanner(plannerId);
    navigate('/planner', { replace: true });
  });

  const data = planner.data;

  return (
    <MobileScreen title={data?.title || '플래너'} showBackButton>
      <ScreenState query={planner} loadingLabel="플래너를 불러오는 중입니다">
        <>
          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">
              {[data?.subject, data?.date, data?.term, data?.priority].filter(Boolean).join(' · ')}
            </p>

            {data?.progress?.total > 0 && (
              <>
                <div className="mobile-progress">
                  <span style={{ width: `${data.progress.ratio}%` }} />
                </div>
                <p className="mobile-card__meta">
                  {data.progress.completed}/{data.progress.total} 완료 · {data.progress.ratio}%
                </p>
              </>
            )}

            {data?.goalTime && <p className="mobile-card__meta">목표 학습 시간 {data.goalTime}</p>}
            {data?.content && <p className="mobile-paragraph">{data.content}</p>}
          </section>

          {data?.tasks?.length > 0 && (
            <section className="mobile-section">
              <h3 className="mobile-section__title">학습 항목</h3>

              <ul className="mobile-list">
                {data.tasks.map((task, index) => (
                  <li key={task.id ?? task.title ?? index} className="mobile-card">
                    <p className="mobile-paragraph">{task.title || task.content || task.text}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="mobile-actions">
            <Button
              variant="secondary"
              isLoading={registerSchedule.isSubmitting}
              onClick={() => registerSchedule.submit().catch(() => {})}
            >
              <CalendarPlus size={16} />
              일정 등록
            </Button>

            <Button
              variant="secondary"
              isLoading={downloadPdf.isSubmitting}
              onClick={() => downloadPdf.submit().catch(() => {})}
            >
              <Download size={16} />
              PDF
            </Button>

            <Button
              variant="ghost"
              isLoading={removePlanner.isSubmitting}
              onClick={() => removePlanner.submit().catch(() => {})}
            >
              <Trash2 size={16} />
              삭제
            </Button>
          </div>

          {(registerSchedule.errorMessage || downloadPdf.errorMessage || removePlanner.errorMessage) && (
            <p className="mobile-auth__error">
              {registerSchedule.errorMessage || downloadPdf.errorMessage || removePlanner.errorMessage}
            </p>
          )}
        </>
      </ScreenState>
    </MobileScreen>
  );
}
