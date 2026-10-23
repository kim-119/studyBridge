import { useCallback } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

export const ROOM_PANEL = {
  MENU: 'menu',
  SETTINGS: 'settings',
  CHAT: 'chat',
  AI: 'ai',
  PARTICIPANTS: 'participants',
  MATERIALS: 'materials',
  QUIZ: 'quiz',
};

const OVERLAY_STATE = { overlay: true };

export function useRoomOverlay() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();

  const panel = searchParams.get('panel');
  const focusedConnectionId = searchParams.get('focus');
  const viewerMaterialId = searchParams.get('viewer');
  const isOverlayEntry = Boolean(location.state?.overlay);

  const pushLayer = useCallback(
    (params) => setSearchParams(params, { state: OVERLAY_STATE }),
    [setSearchParams]
  );

  const openPanel = useCallback(
    (key) => setSearchParams({ panel: key }, { replace: isOverlayEntry, state: OVERLAY_STATE }),
    [isOverlayEntry, setSearchParams]
  );

  const openFocus = useCallback((connectionId) => pushLayer({ focus: connectionId }), [pushLayer]);

  const openViewer = useCallback(
    (materialId) => pushLayer({ panel: ROOM_PANEL.MATERIALS, viewer: String(materialId) }),
    [pushLayer]
  );

  const close = useCallback(() => {
    if (isOverlayEntry) {
      navigate(-1);
      return;
    }
    setSearchParams({}, { replace: true });
  }, [isOverlayEntry, navigate, setSearchParams]);

  return {
    panel,
    focusedConnectionId,
    viewerMaterialId,
    openPanel,
    openFocus,
    openViewer,
    close,
  };
}
