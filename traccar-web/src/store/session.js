import { createSlice } from '@reduxjs/toolkit';

// The trail drawn behind a followed vehicle: the fixes of the last minute, kept
// per device regardless of the live-routes preference (which is a separate,
// unlimited-length feature).
export const TRAIL_WINDOW_MS = 60 * 1000;
const TRAIL_MAX_POINTS = 120;

export const trailPoints = (trail, now = Date.now()) =>
  (trail || []).filter((point) => now - point[2] <= TRAIL_WINDOW_MS);

const { reducer, actions } = createSlice({
  name: 'session',
  initialState: {
    server: null,
    user: null,
    socket: null,
    includeLogs: false,
    logs: [],
    positions: {},
    history: {},
    trail: {},
  },
  reducers: {
    updateServer(state, action) {
      state.server = action.payload;
    },
    updateUser(state, action) {
      state.user = action.payload;
    },
    updateSocket(state, action) {
      state.socket = action.payload;
    },
    enableLogs(state, action) {
      state.includeLogs = action.payload;
      if (!action.payload) {
        state.logs = [];
      }
    },
    updateLogs(state, action) {
      state.logs.push(...action.payload);
    },
    updatePositions(state, action) {
      const liveRoutes =
        state.user.attributes.mapLiveRoutes || state.server.attributes.mapLiveRoutes || 'none';
      const liveRoutesLimit =
        state.user.attributes['web.liveRouteLength'] ||
        state.server.attributes['web.liveRouteLength'] ||
        10;
      const now = Date.now();
      action.payload.forEach((position) => {
        state.positions[position.deviceId] = position;

        // Follow trail: keep this device's fixes from the last minute.
        const trail = trailPoints(state.trail[position.deviceId], now);
        const previous = trail.at(-1);
        if (!previous || previous[0] !== position.longitude || previous[1] !== position.latitude) {
          trail.push([position.longitude, position.latitude, now]);
        }
        state.trail[position.deviceId] = trail.slice(-TRAIL_MAX_POINTS);

        if (liveRoutes !== 'none') {
          const route = state.history[position.deviceId] || [];
          const last = route.at(-1);
          if (!last || (last[0] !== position.longitude && last[1] !== position.latitude)) {
            state.history[position.deviceId] = [
              ...route.slice(1 - liveRoutesLimit),
              [position.longitude, position.latitude],
            ];
          }
        } else {
          state.history = {};
        }
      });
    },
  },
});

export { actions as sessionActions };
export { reducer as sessionReducer };
