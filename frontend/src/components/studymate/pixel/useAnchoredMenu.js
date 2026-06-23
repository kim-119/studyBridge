import { useCallback, useLayoutEffect, useRef, useState } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// 선택된 교수 actor의 DOMRect 기준으로 액션 메뉴를 stage 안에 anchor + 충돌 보정한다.
//   · 물리 인치/특정 해상도 분기 없음 — viewport·stage·actor·menu rect + clamp 로만 계산.
//   · placement 폴백: top → (좌우 clamp로 top-start/top-end 자연 발생) → side(left/right).
//   · ResizeObserver(stage·actor·menu) + window resize/scroll + document.fonts.ready +
//     content signature 변경 시 재계산한다(목표 5/6).
//   · 메뉴는 stage 레이아웃을 밀지 않는 floating layer(absolute)로 띄운다(목표 8).
// ─────────────────────────────────────────────────────────────────────────────
const GAP = 10;  // 이름표/몸통과 메뉴 사이 safe gap (8~12px, 목표 7)
const PAD = 8;   // stage 가장자리 safe inset

export default function useAnchoredMenu({ stageRef, selectedRole, signature }) {
  const menuRef = useRef(null);
  // ready=false 동안은 메뉴를 visibility:hidden 으로 두어 잘못된 위치 깜빡임을 막는다.
  const [pos, setPos] = useState({ left: 0, top: 0, placement: 'top', ready: false });

  const recalc = useCallback(() => {
    const stage = stageRef.current;
    const menu = menuRef.current;
    if (!stage || !menu || !selectedRole) return;
    const actor = stage.querySelector(`.professor-position-layer[data-role="${selectedRole}"]`);
    if (!actor) return;

    const s = stage.getBoundingClientRect();
    const a = actor.getBoundingClientRect();
    const m = menu.getBoundingClientRect();
    const stageW = s.width;
    const stageH = s.height;
    const mW = m.width;
    const mH = m.height;
    // actor 좌표(stage 로컬). actorTop = sprite(머리) 상단.
    const aLeft = a.left - s.left;
    const aTop = a.top - s.top;
    const aCx = aLeft + a.width / 2;

    const clampX = (x) => Math.max(PAD, Math.min(x, Math.max(PAD, stageW - mW - PAD)));
    const clampY = (y) => Math.max(PAD, Math.min(y, Math.max(PAD, stageH - mH - PAD)));

    let placement = 'top';
    let left = clampX(aCx - mW / 2);
    let top = aTop - mH - GAP;

    if (top < PAD) {
      // 위 공간 부족 → 측면 폴백(actor가 왼쪽 절반이면 오른쪽, 아니면 왼쪽에 붙인다).
      const onLeftHalf = aCx < stageW / 2;
      placement = onLeftHalf ? 'right' : 'left';
      top = clampY(aTop);
      left = clampX(onLeftHalf ? aLeft + a.width + GAP : aLeft - mW - GAP);
    } else if (left <= PAD + 0.5) {
      placement = 'top-start';
    } else if (left >= stageW - mW - PAD - 0.5) {
      placement = 'top-end';
    }

    setPos((prev) => {
      const next = { left: Math.round(left), top: Math.round(top), placement, ready: true };
      if (prev.ready && prev.left === next.left && prev.top === next.top && prev.placement === next.placement) {
        return prev;
      }
      return next;
    });
  }, [stageRef, selectedRole]);

  useLayoutEffect(() => {
    if (!selectedRole) {
      setPos((p) => (p.ready ? { ...p, ready: false } : p));
      return undefined;
    }
    setPos((p) => (p.ready ? { ...p, ready: false } : p));
    // 마운트 직후 + 다음 프레임(레이아웃/폰트 안정 후) 2회 측정해 초기 위치를 안정화한다.
    let raf2 = 0;
    let raf1 = requestAnimationFrame(() => {
      recalc();
      raf2 = requestAnimationFrame(recalc);
    });

    const stage = stageRef.current;
    const actor = stage?.querySelector(`.professor-position-layer[data-role="${selectedRole}"]`);
    let ro = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => recalc());
      if (stage) ro.observe(stage);
      if (actor) ro.observe(actor);
      if (menuRef.current) ro.observe(menuRef.current);
    }
    const onReflow = () => recalc();
    window.addEventListener('resize', onReflow);
    window.addEventListener('scroll', onReflow, true);
    // 폰트 로딩 완료 시 글자폭이 바뀌므로 재계산(목표 5).
    if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) {
      document.fonts.ready.then(recalc).catch(() => {});
    }

    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      if (ro) ro.disconnect();
      window.removeEventListener('resize', onReflow);
      window.removeEventListener('scroll', onReflow, true);
    };
  }, [selectedRole, signature, recalc, stageRef]);

  return { menuRef, pos };
}
