import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter';
import { BrowserRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { CssBaseline, StyledEngineProvider } from '@mui/material';
import store from './store';
import { LocalizationProvider } from './common/components/LocalizationProvider';
import ErrorHandler from './common/components/ErrorHandler';
import Navigation from './Navigation';
import preloadImages from './map/core/preloadImages';
import NativeInterface from './common/components/NativeInterface';
import ServerProvider from './ServerProvider';
import ErrorBoundary from './ErrorBoundary';
import AppThemeProvider from './AppThemeProvider';
import { savePersistedState } from './common/util/usePersistedState';

preloadImages();

// Starting the app fresh shows the dashboard, whichever view it was left on.
// This runs on a real page load and nothing else, so an app that was only
// switched away from comes back exactly as it was left - on the page and the
// view the user was using. Set before the first render, or the old view would
// appear for a moment first.
savePersistedState('fleetView', 'dashboard');

const root = createRoot(document.getElementById('root'));
root.render(
  <ErrorBoundary>
    <Provider store={store}>
      <LocalizationProvider>
        <StyledEngineProvider injectFirst>
          <AppThemeProvider>
            <CssBaseline />
            <ServerProvider>
              <BrowserRouter>
                <Navigation />
              </BrowserRouter>
              <ErrorHandler />
              <NativeInterface />
            </ServerProvider>
          </AppThemeProvider>
        </StyledEngineProvider>
      </LocalizationProvider>
    </Provider>
  </ErrorBoundary>,
);
