import React, { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import BottomNav from './shell/BottomNav';
import MobileBoot from './MobileBoot';
import RequireAuth from './auth/RequireAuth';
import ForgotPasswordScreen from './screens/auth/ForgotPasswordScreen';
import LoginScreen from './screens/auth/LoginScreen';
import RegisterScreen from './screens/auth/RegisterScreen';
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
const AUTH_PATHS = ['/login', '/register', '/forgot-password'];

function useHardwareBackNavigation() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    return registerHardwareBackButton(({ canGoBack }) => {
      if (AUTH_PATHS.includes(pathname) && pathname !== '/login') {
        navigate('/login');
        return true;
      }

      if (canGoBack && pathname !== HOME_PATH) {
        navigate(-1);
        return true;
      }

      if (pathname !== HOME_PATH && pathname !== '/login') {
        navigate(HOME_PATH);
        return true;
      }

      return false;
    });
  }, [navigate, pathname]);
}

function ShellLayout({ children }) {
  return (
    <div className="mobile-root">
      {children}
      <BottomNav />
    </div>
  );
}

export default function MobileApp() {
  const { pathname } = useLocation();
  useHardwareBackNavigation();

  useEffect(() => {
    applyNativeChrome();
  }, []);

  const isAuthRoute = AUTH_PATHS.includes(pathname);

  const routes = (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/register" element={<RegisterScreen />} />
      <Route path="/forgot-password" element={<ForgotPasswordScreen />} />

      <Route
        path="/"
        element={
          <RequireAuth>
            <HomeScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/studymate"
        element={
          <RequireAuth>
            <StudyMateScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/groupstudy"
        element={
          <RequireAuth>
            <GroupStudyScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/archive"
        element={
          <RequireAuth>
            <ArchiveScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/planner"
        element={
          <RequireAuth>
            <PlannerScreen />
          </RequireAuth>
        }
      />
      <Route
        path="/more"
        element={
          <RequireAuth>
            <MoreScreen />
          </RequireAuth>
        }
      />

      {SECONDARY_SCREENS.map(({ path, title, description }) => (
        <Route
          key={path}
          path={path}
          element={
            <RequireAuth>
              <PendingScreen title={title} description={description} showBackButton />
            </RequireAuth>
          }
        />
      ))}

      <Route path="*" element={<Navigate to={HOME_PATH} replace />} />
    </Routes>
  );

  return (
    <MobileBoot>{isAuthRoute ? routes : <ShellLayout>{routes}</ShellLayout>}</MobileBoot>
  );
}
