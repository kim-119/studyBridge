import React, {
  useCallback, useEffect, useRef, useState,
} from 'react';
import { mindmapMemoService } from '../../services/api';
import { countGraphemes, splitByGrapheme } from '../../utils/graph/graphLabel';

// 노드별 메모 섹션(우측 상세 패널 내부).
//  · 저장 단위: materialId + nodeId(저장된 MINDMAP material 의 안정 id). 사용자별은 백엔드 권한으로 분리.
//  · 새로고침 후에도 서버에서 다시 로드 → 영속. 1노드 1메모(빈 내용 저장 = 삭제).
//  · IME 조합 중 자동저장 금지, grapheme 기준 1000자 제한, debounce 자동저장 + 수동 저장, Ctrl/Cmd+S.
//  · 빠른 노드 전환 시 이전 응답이 새 노드를 덮어쓰지 않게 요청 토큰(seq) 가드.
const MAX_GRAPHEMES = 1000;
const AUTOSAVE_MS = 1000;

const STATUS_TEXT = {
  idle: '',
  loading: '불러오는 중…',
  dirty: '변경사항 있음',
  saving: '저장 중…',
  saved: '저장됨',
  autosaved: '자동 저장됨',
  error: '저장 실패 · 다시 시도',
  empty: '',
};

export default function GraphNodeMemo({ materialId, nodeId, nodeLabel, onContentChange }) {
  const isLoggedIn = (() => {
    try { return !!localStorage.getItem('token'); } catch { return false; }
  })();
  // 저장 가능 조건: 저장된 자료(materialId) + 노드 id + 로그인.
  const canUse = materialId != null && !!nodeId && isLoggedIn;

  const [content, setContent] = useState('');
  const [status, setStatus] = useState('idle');
  const [composing, setComposing] = useState(false);

  const taRef = useRef(null);
  const seqRef = useRef(0);          // 요청 토큰: 응답 stale 판정.
  const savedRef = useRef('');       // 마지막으로 서버에 반영된 내용(baseline).
  const debounceRef = useRef(null);
  const composingRef = useRef(false);
  const contentRef = useRef('');     // 최신 content(키 변경/언마운트 시 flush 판단).
  contentRef.current = content;
  // 언마운트 flush 에서 참조할 최신 컨텍스트(노드 전환 시 미저장분 보존, spec 4-3).
  const flushDataRef = useRef({});
  flushDataRef.current = { canUse, materialId, nodeId, nodeLabel };

  const reportContent = useCallback((c) => { onContentChange?.(c); }, [onContentChange]);

  // ── 노드/자료 변경 시 메모 로드(요청 토큰 가드) ──────────────────────────────
  useEffect(() => {
    if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
    if (!canUse) {
      setContent(''); savedRef.current = ''; setStatus('idle'); reportContent('');
      return undefined;
    }
    const my = (seqRef.current += 1);
    let alive = true;
    setStatus('loading');
    mindmapMemoService.getNodeMemo(materialId, nodeId)
      .then((data) => {
        if (!alive || my !== seqRef.current) return; // 다른 노드로 이동했으면 무시.
        const c = data?.memo?.content || '';
        savedRef.current = c;
        setContent(c);
        setStatus(c ? 'saved' : 'idle');
        reportContent(c);
      })
      .catch(() => {
        if (!alive || my !== seqRef.current) return;
        // 404/없음/네트워크 실패 → 빈 메모로 시작(입력은 가능).
        savedRef.current = '';
        setContent('');
        setStatus('idle');
        reportContent('');
      });
    return () => { alive = false; };
  }, [materialId, nodeId, canUse, reportContent]);

  // ── 저장(수동/자동 공통) ────────────────────────────────────────────────────
  const doSave = useCallback(async (auto) => {
    if (!canUse) return;
    const value = contentRef.current;
    if (value === savedRef.current) { setStatus(value ? 'saved' : 'idle'); return; }
    if (countGraphemes(value) > MAX_GRAPHEMES) { setStatus('error'); return; }
    const my = seqRef.current; // 현재 노드 토큰.
    setStatus('saving');
    try {
      await mindmapMemoService.saveNodeMemo(materialId, { nodeId, nodeLabel, content: value });
      if (my !== seqRef.current) return; // 저장 중 노드 전환됨 → 상태 갱신 생략.
      savedRef.current = value;
      setStatus(value ? (auto ? 'autosaved' : 'saved') : 'idle');
      reportContent(value);
    } catch {
      if (my !== seqRef.current) return;
      setStatus('error'); // 입력값(content)은 유지 → 재시도 가능.
    }
  }, [canUse, materialId, nodeId, nodeLabel, reportContent]);

  // ── 입력 변경(grapheme 1000 제한, IME 중에는 자동저장 예약 안 함) ────────────
  const onChange = useCallback((e) => {
    let v = e.target.value;
    // 제한 초과 입력은 잘라서 막는다(조합 중에는 허용해 IME 깨짐 방지).
    if (!composingRef.current && countGraphemes(v) > MAX_GRAPHEMES) {
      v = splitByGrapheme(v).slice(0, MAX_GRAPHEMES).join('');
    }
    setContent(v);
    setStatus('dirty');
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!composingRef.current) {
      debounceRef.current = setTimeout(() => { doSave(true); }, AUTOSAVE_MS);
    }
  }, [doSave]);

  const onCompositionStart = useCallback(() => { composingRef.current = true; setComposing(true); }, []);
  const onCompositionEnd = useCallback((e) => {
    composingRef.current = false; setComposing(false);
    // 조합 종료 시 최종값 반영 + 자동저장 예약.
    setContent(e.target.value);
    setStatus('dirty');
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { doSave(true); }, AUTOSAVE_MS);
  }, [doSave]);

  const onKeyDown = useCallback((e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
      e.preventDefault();
      if (debounceRef.current) clearTimeout(debounceRef.current);
      doSave(false);
    } else if (e.key === 'Escape') {
      e.stopPropagation();
      taRef.current?.blur();
    }
  }, [doSave]);

  const onDelete = useCallback(async () => {
    if (!canUse) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const my = seqRef.current;
    setStatus('saving');
    try {
      await mindmapMemoService.deleteNodeMemo(materialId, nodeId);
      if (my !== seqRef.current) return;
      savedRef.current = ''; setContent(''); setStatus('idle'); reportContent('');
    } catch {
      if (my !== seqRef.current) return;
      setStatus('error');
    }
  }, [canUse, materialId, nodeId, reportContent]);

  // 언마운트 시: debounce 정리 + 미저장분 flush(fire-and-forget, setState 없음).
  //  · 각 메모는 (materialId,nodeId) 로 격리 저장되므로, 떠나는 노드의 저장이 새 노드를 덮어쓰지 않는다.
  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const v = contentRef.current;
    const d = flushDataRef.current;
    if (d.canUse && v !== savedRef.current && countGraphemes(v) <= MAX_GRAPHEMES) {
      mindmapMemoService
        .saveNodeMemo(d.materialId, { nodeId: d.nodeId, nodeLabel: d.nodeLabel, content: v })
        .catch(() => { /* 이동 중 저장 실패는 조용히 무시(다음 진입 시 서버값 로드) */ });
    }
  }, []);

  const used = countGraphemes(content);
  const over = used > MAX_GRAPHEMES;
  const dirty = content !== savedRef.current;

  return (
    <section className="obsg-detail-section obsg-memo">
      <div className="obsg-memo-head">
        <h5>메모</h5>
        <span className={`obsg-memo-count${over ? ' is-over' : ''}`}>{used} / {MAX_GRAPHEMES}</span>
      </div>

      {!canUse ? (
        <div className="obsg-memo-hint">
          {!isLoggedIn
            ? '로그인하면 노드 메모를 작성할 수 있어요.'
            : materialId == null
              ? '마인드맵을 자료보관함에 저장하면 노드 메모를 작성할 수 있어요.'
              : '이 노드에는 메모를 저장할 수 없어요.'}
        </div>
      ) : (
        <>
          <textarea
            ref={taRef}
            className="obsg-memo-textarea"
            value={content}
            onChange={onChange}
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            onKeyDown={onKeyDown}
            placeholder="이 노드에 대한 메모를 입력하세요."
            aria-label="노드 메모"
            maxLength={4000}
          />
          <div className="obsg-memo-actions">
            <span className={`obsg-memo-status is-${status}`}>
              {composing ? '입력 중…' : (over ? '1000자를 초과했습니다' : STATUS_TEXT[status] || (dirty ? STATUS_TEXT.dirty : ''))}
            </span>
            <div className="obsg-memo-buttons">
              <button
                type="button"
                className="obsg-memo-delete"
                onClick={onDelete}
                disabled={status === 'saving' || (!content && !savedRef.current)}
              >
                삭제
              </button>
              <button
                type="button"
                className="obsg-memo-save"
                onClick={() => doSave(false)}
                disabled={status === 'saving' || over || !dirty}
              >
                메모 저장
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
