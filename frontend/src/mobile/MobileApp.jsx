import React, { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import BottomNav from './shell/BottomNav';
import MobileBoot from './MobileBoot';
import ArchiveScreen from './screens/ArchiveScreen';
import GroupStudyScreen from './screens/GroupStudyScreen';
import HomeScreen from './screens/HomeScreen';
import MoreScreen from './screens/MoreScreen';
import PendingScreen from './screens/PendingScreen';
import PlannerScreen from './screens/PlannerScreen';
import StudyMateScreen from './screens/StudyMateScreen';
import { SECONDARY_SCREENS } from './screens/secondaryScreens';
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

          {SECONDARY_SCREENS.map(({ path, title, description }) => (
            <Route
              key={path}
              path={path}
              element={<PendingScreen title={title} description={description} showBackButton />}
            />
          ))}

          <Route path="*" element={<Navigate to={HOME_PATH} replace />} />
        </Routes>

        <BottomNav />
      </div>
    </MobileBoot>
  );
}
