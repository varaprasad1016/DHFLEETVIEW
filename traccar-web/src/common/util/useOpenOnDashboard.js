import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { savePersistedState } from './usePersistedState';

// How long the app has to be out of sight before coming back counts as opening
// it again. Short enough that closing the app and returning lands on the
// dashboard; long enough that glancing at a text message does not throw the
// driver off the map they were watching.
const AWAY_LONG_ENOUGH = 60 * 1000;

/**
 * Coming back to a backgrounded app shows the dashboard again.
 *
 * Starting the app fresh is handled before the first render, in index.jsx.
 * This covers the other way an app is "opened" on a phone: it was never really
 * closed, just left, so there is no reload to reset anything. The dashboard is
 * a view of the main page rather than a page of its own, hence both the view
 * and the route being put back.
 */
export default () => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const hiddenAtRef = useRef(null);
  // Held in a ref so moving around the app does not keep re-registering the
  // listener, while the listener still sees where the app currently is.
  const pathnameRef = useRef(pathname);
  useEffect(() => {
    pathnameRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.hidden) {
        hiddenAtRef.current = Date.now();
        return;
      }
      const away = hiddenAtRef.current && Date.now() - hiddenAtRef.current;
      hiddenAtRef.current = null;
      if (away && away >= AWAY_LONG_ENOUGH) {
        savePersistedState('fleetView', 'dashboard');
        if (pathnameRef.current !== '/') {
          navigate('/', { replace: true });
        }
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [navigate]);
};
