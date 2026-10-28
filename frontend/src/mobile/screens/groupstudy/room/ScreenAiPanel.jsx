import React, { useEffect, useRef, useState } from 'react';
import { Crop, MonitorUp, Square } from 'lucide-react';
import Button from '../../../components/Button';
import MarkdownText from '../../../components/MarkdownText';
import ScreenState from '../../../components/ScreenState';
import { SCREEN_AI_PRESETS, describeShareAvailability, normalizeRegion, regionToSourceRect } from '../screenAiModel';
import { encodeFrame, releaseSnapshot, snapshotScreenFrame } from '../screenFrameCapture';
import { useScreenAnalysis } from '../useScreenAnalysis';

const REGION_PRESET = SCREEN_AI_PRESETS.find((preset) => preset.needsRegion);

function pointIn(event, element) {
  const box = element.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}

// 고정한 스냅샷 위에서 드래그로 영역을 고른다. 같은 스냅샷을 잘라 보내므로 좌표와 프레임이 어긋나지 않는다.
function RegionSelector({ snapshot, limits, onConfirm, onCancel }) {
  const imageRef = useRef(null);
  const [drag, setDrag] = useState(null);
  const [error, setError] = useState(null);

  const region =
    drag?.end && imageRef.current
      ? normalizeRegion(drag.start, drag.end, {
          width: imageRef.current.clientWidth,
          height: imageRef.current.clientHeight,
        })
      : null;

  const confirm = () => {
    const sourceRect = regionToSourceRect(region, snapshot.frameSize, limits.minSide);
    if (!sourceRect) {
      setError('영역이 너무 작습니다. 조금 더 넓게 선택해 주세요.');
      return;
    }
    try {
      const encoded = encodeFrame(snapshot.canvas, {
        sourceRect,
        frameSize: snapshot.frameSize,
        maxLongSide: limits.maxLongSide,
        maxBytes: limits.maxImageBytes,
      });
      onConfirm(encoded.dataUrl);
    } catch (caught) {
      setError(caught.message);
    }
  };

  return (
    <section className="mobile-card mobile-section mobile-screen-ai__region">
      <p className="mobile-field__hint">설명받을 영역을 손가락으로 드래그해 선택하세요.</p>
      <div
        className="mobile-screen-ai__snapshot"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setError(null);
          setDrag({ start: pointIn(event, imageRef.current), end: null });
        }}
        onPointerMove={(event) => {
          if (drag) setDrag({ ...drag, end: pointIn(event, imageRef.current) });
        }}
        onPointerUp={(event) => {
          if (drag) setDrag({ ...drag, end: pointIn(event, imageRef.current) });
        }}
      >
        <img ref={imageRef} src={snapshot.previewUrl} alt="선택할 화면" draggable={false} />
        {region && (
          <span
            className="mobile-screen-ai__selection"
            style={{
              left: `${region.x * 100}%`,
              top: `${region.y * 100}%`,
              width: `${region.width * 100}%`,
              height: `${region.height * 100}%`,
            }}
          />
        )}
      </div>
      {error && <p className="mobile-auth__error">{error}</p>}
      <div className="mobile-actions">
        <Button variant="ghost" onClick={onCancel}>
          취소
        </Button>
        <Button disabled={!region} onClick={confirm}>
          이 영역 분석
        </Button>
      </div>
    </section>
  );
}

function AnalysisEntry({ entry, onCancel }) {
  return (
    <>
      <li className="mobile-chat__bubble is-user">
        <span className="mobile-chat__author">{entry.sharerName}님 화면</span>
        <p className="mobile-paragraph">{entry.question}</p>
      </li>
      <li
        className={
          entry.status === 'failed' || entry.status === 'cancelled'
            ? 'mobile-chat__bubble mobile-room-chat__error'
            : 'mobile-chat__bubble mobile-chat__bubble--agent'
        }
        data-screen-ai-status={entry.status}
      >
        <span className="mobile-chat__author">AI 화면 분석</span>
        {entry.status === 'pending' && (
          <>
            <p className="mobile-paragraph">화면을 분석하는 중입니다. 다른 요청이 많으면 시간이 걸릴 수 있습니다.</p>
            <Button variant="ghost" onClick={() => onCancel()}>
              <Square size={14} />
              분석 취소
            </Button>
          </>
        )}
        {entry.status === 'done' && <MarkdownText>{entry.answer}</MarkdownText>}
        {(entry.status === 'failed' || entry.status === 'cancelled') && (
          <p className="mobile-paragraph">{entry.errorMessage}</p>
        )}
      </li>
    </>
  );
}

export default function ScreenAiPanel({ groupId, remoteParticipants }) {
  const analysis = useScreenAnalysis(groupId, remoteParticipants);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState('');
  const [snapshot, setSnapshot] = useState(null);
  const [notice, setNotice] = useState(null);

  const { shares } = analysis;
  const selected = shares.find((share) => share.connectionId === selectedId) || shares[0] || null;
  const unavailable = describeShareAvailability(selected);
  const canAsk = !unavailable && !analysis.isPending && analysis.viewerConnected;

  useEffect(() => {
    if (selectedId && !shares.some((share) => share.connectionId === selectedId)) setSelectedId(null);
  }, [selectedId, shares]);

  // 고정한 스냅샷은 영역 선택이 끝나면 바로 버린다(프레임 최소 보관).
  useEffect(() => () => releaseSnapshot(snapshot), [snapshot]);

  const ask = async (question, options) => {
    setNotice(null);
    const outcome = await analysis.analyze(selected, question, options);
    if (!outcome.ok && outcome.message) setNotice(outcome.message);
  };

  const startRegionSelection = async () => {
    setNotice(null);
    try {
      setSnapshot(await snapshotScreenFrame(selected.streamManager, analysis.limits));
    } catch (error) {
      setNotice(error.message);
    }
  };

  return (
    <ScreenState query={analysis.sharesQuery} loadingLabel="화면공유 목록을 불러오는 중입니다">
      <div className="mobile-room-chat">
        <p className="mobile-field__hint">
          공유자가 허용한 화면만 분석할 수 있습니다. 지금 보이는 화면 1장만 AI로 보내고 앱에 저장하지 않습니다.
        </p>

        {!analysis.isEnabled && <p className="mobile-chat__status">AI 화면 분석 기능이 지금은 꺼져 있습니다.</p>}
        {analysis.isEnabled && !analysis.viewerConnected && (
          <p className="mobile-chat__status">영상 연결이 준비되면 화면을 분석할 수 있습니다.</p>
        )}

        {analysis.isEnabled && shares.length === 0 && (
          <p className="mobile-chat__empty">
            <MonitorUp size={18} /> 지금 분석할 수 있는 화면공유가 없습니다.
          </p>
        )}

        {shares.length > 1 && (
          <select
            className="mobile-select mobile-archive-fill"
            aria-label="분석할 화면공유 선택"
            value={selected?.connectionId ?? ''}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {shares.map((share) => (
              <option key={share.connectionId} value={share.connectionId}>
                {share.sharerName}님의 화면{share.hasConsent ? '' : ' (분석 미허용)'}
              </option>
            ))}
          </select>
        )}
        {selected && unavailable && <p className="mobile-chat__status">{unavailable}</p>}

        <ul className="mobile-chat__messages">
          {analysis.entries.map((entry) => (
            <AnalysisEntry key={entry.id} entry={entry} onCancel={analysis.cancel} />
          ))}
        </ul>

        {notice && <p className="mobile-auth__error">{notice}</p>}

        {snapshot ? (
          <RegionSelector
            snapshot={snapshot}
            limits={analysis.limits}
            onCancel={() => setSnapshot(null)}
            onConfirm={(image) => {
              setSnapshot(null);
              ask(REGION_PRESET.question, { image });
            }}
          />
        ) : (
          selected && (
            <>
              <div className="mobile-chat__followups" aria-label="화면 분석 빠른 질문">
                {SCREEN_AI_PRESETS.map((preset) => (
                  <button
                    key={preset.key}
                    type="button"
                    disabled={!canAsk}
                    onClick={() => (preset.needsRegion ? startRegionSelection() : ask(preset.question))}
                  >
                    {preset.needsRegion && <Crop size={14} />}
                    {preset.label}
                  </button>
                ))}
              </div>
              <form
                className="mobile-chat__composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!canAsk || !draft.trim()) return;
                  ask(draft);
                  setDraft('');
                }}
              >
                <textarea
                  className="mobile-chat__input"
                  rows={1}
                  value={draft}
                  maxLength={analysis.limits.maxQuestionChars}
                  placeholder="화면에 대해 질문하세요"
                  onChange={(event) => setDraft(event.target.value)}
                />
                <button type="submit" className="mobile-chat__send" disabled={!canAsk || !draft.trim()}>
                  분석
                </button>
              </form>
            </>
          )
        )}
      </div>
    </ScreenState>
  );
}
