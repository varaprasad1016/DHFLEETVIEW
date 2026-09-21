import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { savePersistedState } from './usePersistedState';

/**
 * Coming back to the app shows the dashboard again, every time.
 *
 * Starting the app fresh is handled before the first render, in index.jsx.
 * This covers the other way an app is "opened" on a phone: closing it often
 * only backgrounds it, so there is no reload to reset anything, and the app
 * comes back exactly as it was left.
 *
 * There is no way to tell a phone that was closed from one that was glanced
 * away from, so this does not try: coming back always shows the dashboard,
 * which is what was asked for and is at least predictable. The dashboard is a
 * view of the main page rather than a page of its own, hence both the view and
 * the route being put back.
 */
export default () => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const wasHiddenRef = useRef(false);
  // Held in a ref so moving around the app does not keep re-registering the
  // listener, while the listener still sees where the app currently is.
  const pathnameRef = useRef(pathname);
  useEffect(() => {
    pathnameRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    const showDashboard = () => {
      savePersistedState('fleetView', 'dashboard');
      if (pathnameRef.current !== '/') {
        navigate('/', { replace: true });
      }
    };
    const onVisibilityChange = () => {
      if (document.hidden) {
        wasHiddenRef.current = true;
      } else if (wasHiddenRef.current) {
        wasHiddenRef.current = false;
        showDashboard();
      }
    };
    // A phone may restore the app from its back/forward cache instead of
    // making it visible again, which fires this and nothing else.
    const onPageShow = (event) => {
      if (event.persisted) {
        wasHiddenRef.current = false;
        showDashboard();
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [navigate]);
};
