import React, { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import BottomNav from './shell/BottomNav';
import MobileBoot from './MobileBoot';
import PendingScreen from './screens/PendingScreen';
import ArchiveScreen from './screens/ArchiveScreen';
import GroupStudyScreen from './screens/GroupStudyScreen';
import HomeScreen from './screens/HomeScreen';
import MoreScreen from './screens/MoreScreen';
import PlannerScreen from './screens/PlannerScreen';
import StudyMateScreen from './screens/StudyMateScreen';
import { applyNativeChrome, registerHardwareBackButton } from './platform/nativeShell';

const HOME_PATH = '/';

function useHardwareBackNavigation() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    return registerHardwareBackButton(({ canGoBack }) => {
      if (canGoBack) {
        navigate(-1);
        return true;
      }

      if (pathname !== HOME_PATH) {
        navigate(HOME_PATH);
        return true;
      }

      return false;
    });
  }, [navigate, pathname]);
}

export default function MobileApp() {
  useHardwareBackNavigation();

  useEffect(() => {
    applyNativeChrome();
  }, []);

  return (
    <MobileBoot>
      <div className="mobile-root">
        <Routes>
          <Route path="/" element={<HomeScreen />} />
          <Route path="/studymate" element={<StudyMateScreen />} />
          <Route path="/groupstudy" element={<GroupStudyScreen />} />
          <Route path="/archive" element={<ArchiveScreen />} />
          <Route path="/planner" element={<PlannerScreen />} />
          <Route path="/more" element={<MoreScreen />} />
          <Route
            path="/review-notes"
            element={<PendingScreen title="오답노트" description="오답 카드와 다시 풀기는 부가기능 단계에서 연결됩니다." />}
          />
          <Route
            path="/weekly-schedule"
            element={<PendingScreen title="주간일정" description="월간·주간 일정 관리는 부가기능 단계에서 연결됩니다." />}
          />
          <Route
            path="/knowledge"
            element={<PendingScreen title="지식공유" description="게시판 목록과 상세는 부가기능 단계에서 연결됩니다." />}
          />
          <Route
            path="/mindmap"
            element={<PendingScreen title="마인드맵" description="노드 탐색과 확대·축소는 부가기능 단계에서 연결됩니다." />}
          />
          <Route
            path="/mypage"
            element={<PendingScreen title="마이페이지" description="프로필과 계정 보안은 부가기능 단계에서 연결됩니다." />}
          />
          <Route path="*" element={<Navigate to={HOME_PATH} replace />} />
        </Routes>

        <BottomNav />
      </div>
    </MobileBoot>
  );
}
