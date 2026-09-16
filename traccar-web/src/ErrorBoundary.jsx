import React from 'react';
import { Alert, Box, Button } from '@mui/material';

// How many times to silently remount before showing the error card. A foldable
// crossing a layout breakpoint can throw a one-frame render race deep in a store
// subscription (react-redux useSyncExternalStore); those resolve on the next
// paint, so we auto-recover instead of white-screening. A genuinely broken render
// throws again immediately and, after MAX_RETRIES, we surface it.
const MAX_RETRIES = 3;

const HARD_RELOAD_KEY = 'errorBoundaryHardReload';

// Reload without the offline cache. A crash can come from an old build that the
// service worker (or the mobile app's web view) is still serving after a fix
// was deployed; a normal reload would load the same broken files again.
export const hardReload = async () => {
  try {
    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((registration) => registration.unregister()));
    }
    if (window.caches) {
      const keys = await window.caches.keys();
      await Promise.all(keys.map((key) => window.caches.delete(key)));
    }
  } catch {
    // Still reload below.
  }
  window.location.reload();
};

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, retries: 0 };
    this.retryTimer = null;
    this.resetTimer = null;
    this.handleResize = this.handleResize.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidMount() {
    // A fold/unfold settling is a good moment to try recovering.
    window.addEventListener('resize', this.handleResize);
    window.addEventListener('orientationchange', this.handleResize);
  }

  componentDidCatch(error) {
    if (this.state.retries < MAX_RETRIES) {
      clearTimeout(this.retryTimer);
      // Remount on the next paint, once the layout transition has settled.
      this.retryTimer = setTimeout(() => {
        this.setState((s) => ({ error: null, retries: s.retries + 1 }));
      }, 150);
      // After a stable period, forget the retry count so later transients also recover.
      clearTimeout(this.resetTimer);
      this.resetTimer = setTimeout(() => this.setState({ retries: 0 }), 8000);
    } else {
      if (typeof console !== 'undefined') {
        // eslint-disable-next-line no-console
        console.error('ErrorBoundary: giving up after retries', error);
      }
      // Heal a stale cached build automatically, once per session; a real bug
      // shows the error card after that.
      try {
        if (!window.sessionStorage.getItem(HARD_RELOAD_KEY)) {
          window.sessionStorage.setItem(HARD_RELOAD_KEY, String(Date.now()));
          hardReload();
        }
      } catch {
        // sessionStorage unavailable: leave it to the Reload button.
      }
    }
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.handleResize);
    window.removeEventListener('orientationchange', this.handleResize);
    clearTimeout(this.retryTimer);
    clearTimeout(this.resetTimer);
  }

  handleResize() {
    if (this.state.error && this.state.retries < MAX_RETRIES) {
      this.setState((s) => ({ error: null, retries: s.retries + 1 }));
    }
  }

  render() {
    const { error, retries } = this.state;
    if (error && retries >= MAX_RETRIES) {
      return (
        <Box sx={{ p: 2 }}>
          <Alert
            severity="error"
            action={(
              <Button color="inherit" size="small" onClick={() => hardReload()}>
                Reload
              </Button>
            )}
          >
            <code style={{ whiteSpace: 'pre-wrap' }}>{error.stack}</code>
          </Alert>
        </Box>
      );
    }
    if (error) {
      // Recovering: render nothing for a beat; componentDidCatch remounts shortly.
      return null;
    }
    const { children } = this.props;
    return children;
  }
}

export default ErrorBoundary;
