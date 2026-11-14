/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  TextField,
  MenuItem,
  Button,
  Tabs,
  Tab,
  Box,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
  ListItemButton,
  Chip,
  Slider,
  LinearProgress,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import StopIcon from '@mui/icons-material/Stop';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import VolumeOffIcon from '@mui/icons-material/VolumeOff';
import SearchIcon from '@mui/icons-material/Search';
import DownloadIcon from '@mui/icons-material/Download';
import GridViewIcon from '@mui/icons-material/GridView';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import HomeRoundedIcon from '@mui/icons-material/HomeRounded';
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded';
import BackIcon from '../common/components/BackIcon';
import { savePersistedState } from '../common/util/usePersistedState';
import useComplianceAccess from '../common/util/useComplianceAccess';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useAttributePreference } from '../common/util/preferences';
import {
  cmsv9GetConfig,
  cmsv9StartLive,
  cmsv9StopLive,
  cmsv9StartPlayback,
  cmsv9Search,
  cmsv9History,
  cmsv9StreamStatus,
} from '../common/util/cmsv9';
import { useCatch, useCatchCallback } from '../reactHelper';
import MapView from '../map/core/MapView';
import MapPositionMarkers from '../map/MapPositionMarkers';
import MapCamera from '../map/MapCamera';
import MapScale from '../map/MapScale';
import MapCurrentLocation from '../map/MapCurrentLocation';
import useTachoLive from '../common/util/useTachoLive';
import TachoOverlay from './components/TachoOverlay';

const useStyles = makeStyles()((theme) => ({
  root: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
  },
  title: {
    flexGrow: 1,
    [theme.breakpoints.down('sm')]: {
      display: 'none',
    },
  },
  video: {
    flexGrow: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#000',
    minHeight: 240,
    maxHeight: 'calc(100vh - 200px)',
    position: 'relative',
  },
  player: {
    maxWidth: '100%',
    maxHeight: '100%',
    width: '100%',
    height: '100%',
  },
  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    padding: theme.spacing(1, 2),
    flexWrap: 'wrap',
  },
  search: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    padding: theme.spacing(1, 2),
    flexWrap: 'wrap',
  },
  overlay: {
    position: 'absolute',
    color: '#fff',
  },
  list: {
    maxHeight: 220,
    overflow: 'auto',
  },
  tab: {
    minHeight: 48,
    minWidth: 0,
    [theme.breakpoints.down('sm')]: {
      flexGrow: 1,
    },
  },
  // The grid divides the space it is given rather than sizing itself from its
  // tiles. Fixing each tile to 4:3 made a 2x2 wall about 800px tall whatever
  // the window could spare, so the top row was cut off above the visible area
  // and the whole thing quietly scrolled - which is what "muddled up" looked
  // like. The rows and columns are set from the channel count instead, and
  // each picture letterboxes inside its tile.
  grid: {
    display: 'grid',
    gap: theme.spacing(1),
    padding: theme.spacing(1, 2),
    backgroundColor: '#000',
    // A flex child will not shrink below its content without this, and then
    // the grid pushes the map off the bottom instead of sharing the space.
    minHeight: 0,
    overflow: 'hidden',
  },
  cell: {
    position: 'relative',
    backgroundColor: '#0a0a0a',
    borderRadius: 8,
    overflow: 'hidden',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: `1px solid ${theme.palette.divider}`,
    // Each tile is whatever its share of the grid is; the picture fits inside
    // it with object-fit, so an odd-shaped tile letterboxes rather than
    // stretching the image or overflowing the row.
    minHeight: 0,
    minWidth: 0,
    // display:flex above beats the hidden attribute's own display:none, and
    // the other tiles are hidden that way while one fills the screen.
    '&[hidden]': { display: 'none' },
  },
  cellVideo: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },
  // Double-tapping a tile lifts it out of the grid to fill the screen. Done
  // with fixed positioning rather than the Fullscreen API alone: iOS Safari
  // will not make an arbitrary element fullscreen, and inside the app's
  // WebView the native call is refused more often than it is granted. This
  // works everywhere, and the native call is still attempted on top of it so
  // Android gives up its system bars as well.
  cellFullscreen: {
    position: 'fixed',
    top: 0,
    left: 0,
    width: '100vw',
    // Falls back for anything without dvh; dvh is what keeps it exact while a
    // phone's address bar slides in and out.
    height: '100vh',
    // eslint-disable-next-line no-dupe-keys
    height: '100dvh',
    zIndex: theme.zIndex.modal + 2,
    borderRadius: 0,
    border: 'none',
    backgroundColor: '#000',
    margin: 0,
  },
  fullscreenHint: {
    position: 'absolute',
    bottom: 'calc(env(safe-area-inset-bottom, 0px) + 14px)',
    left: 0,
    right: 0,
    textAlign: 'center',
    color: 'rgba(255,255,255,0.72)',
    fontSize: '0.75rem',
    textShadow: '0 1px 3px rgba(0,0,0,0.9)',
    pointerEvents: 'none',
    zIndex: 2,
  },
  cellLabel: {
    position: 'absolute',
    top: 6,
    left: 8,
    color: '#fff',
    textShadow: '0 1px 3px rgba(0,0,0,0.8)',
    fontSize: '0.7rem',
    fontWeight: 600,
    zIndex: 1,
    pointerEvents: 'none',
  },
  cellSelected: {
    border: '2px solid #22c55e',
  },
  groupTabs: {
    display: 'flex',
    justifyContent: 'center',
    gap: theme.spacing(1),
    padding: theme.spacing(1, 2, 0),
    flexWrap: 'wrap',
  },
  cellActions: {
    position: 'absolute',
    bottom: 6,
    right: 6,
    display: 'flex',
    gap: 4,
    zIndex: 1,
  },
  cellButton: {
    backgroundColor: 'rgba(0,0,0,0.55)',
    color: '#fff',
    '&:hover': {
      backgroundColor: 'rgba(0,0,0,0.75)',
    },
  },
  // The speaker that is live: the same green as the selected tile's border.
  cellButtonOn: {
    backgroundColor: 'rgba(34,197,94,0.85)',
    '&:hover': {
      backgroundColor: 'rgba(34,197,94,1)',
    },
  },
  cellPlaceholder: {
    color: '#666',
    fontSize: '0.8rem',
  },
  // Live map under the video: half the screen alongside a single channel, and the
  // space left under the grid in multi-channel view.
  mapArea: {
    position: 'relative',
    flexGrow: 1,
    minHeight: 200,
    borderTop: `1px solid ${theme.palette.divider}`,
  },
  mapHalf: {
    flex: '1 1 50%',
    minHeight: 180,
  },
  videoHalf: {
    flex: '1 1 50%',
    maxHeight: 'none',
  },
  // With the map below it the grid takes the larger share and the map the
  // rest, both able to shrink. Before, the grid was flexGrow 0 and sized by
  // its tiles, so it overran whatever was left and the first row was clipped.
  gridWithMap: {
    flex: '1 1 54%',
  },
  mapEmpty: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.palette.background.paper,
    zIndex: 1,
  },
}));

// How the tiles are arranged for a given number of channels. Two columns
// regardless meant a single camera got half the width for no reason, and six
// made three rows that could not fit. Rows are explicit so the grid divides
// the height it has rather than growing past it.
const gridShape = (count) => {
  const columns = count <= 1 ? 1 : count <= 4 ? 2 : count <= 9 ? 3 : 4;
  const rows = Math.max(1, Math.ceil(count / columns));
  return {
    gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
    gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
  };
};

// Speeds offered when reviewing a clip. Browsers honour playbackRate up to
// 16, which is where this stops.
const REVIEW_RATES = [1, 2, 4, 8, 16];

const clockOf = (seconds) => {
  const whole = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
};

const formatMb = (bytes) => `${Math.round((bytes || 0) / (1024 * 1024))} MB`;

// How often a stalled tile is restarted from the DVR before it gives up, and
// how long a tile may show nothing before it counts as stalled.
const GRID_RESTART_LIMIT = 3;
const GRID_RESTART_DELAY_MS = 1500;
const GRID_FIRST_FRAME_MS = 45000;

let jessibucaPromise = null;
function loadJessibuca() {
  if (!jessibucaPromise) {
    jessibucaPromise = new Promise((resolve, reject) => {
      if (window.jessibuca) {
        resolve(window.jessibuca);
        return;
      }
      const script = document.createElement('script');
      script.src = '/jessibuca.js';
      script.onload = () => resolve(window.jessibuca);
      script.onerror = () => reject(new Error('Failed to load video player'));
      document.head.appendChild(script);
    });
  }
  return jessibucaPromise;
}

function parseCnmsFileTime(v) {
  if (!v || String(v).length < 12) return null;
  const s = String(v);
  return dayjs(
    `20${s.slice(0, 2)}-${s.slice(2, 4)}-${s.slice(4, 6)}T${s.slice(6, 8)}:${s.slice(8, 10)}:${s.slice(10, 12)}`,
  );
}

async function createFlvPlayer(container, url, options = {}) {
  const Jessibuca = await loadJessibuca();
  const player = new Jessibuca({
    container,
    videoBuffer: options.videoBuffer ?? 0.2,
    decoder: '/decoder.js',
    hasAudio: options.hasAudio !== false,
    isFlv: true,
    useMSE: false,
    useWCS: true,
    autoWasm: true,
    debug: false,
    showBandwidth: false,
    // true = keep the picture's own shape and letterbox it; false = stretch to
    // fill the container. Everything that shows video wants the former.
    isResize: options.isResize ?? false,
    useWebFullScreen: false,
    timeout: options.timeout || 20,
    loadingTimeout: options.loadingTimeout || 30,
    // A live tile that stops receiving frames used to sit there frozen. Let the
    // player notice the silence and reconnect on its own; the page restarts the
    // channel from the DVR if those attempts run out (see startChannel).
    heartTimeout: options.heartTimeout || 8,
    heartTimeoutReplay: true,
    heartTimeoutReplayTimes: 2,
    loadingTimeoutReplay: true,
  });
  player.on('error', (err) => console.log('[cmsv9] error:', err));
  player.on('videoInfo', (d) => console.log('[cmsv9] videoInfo:', d));
  player.on('audioInfo', (d) => console.log('[cmsv9] audioInfo:', d));
  player.on('load', () => console.log('[cmsv9] load'));
  player.on('play', () => console.log('[cmsv9] play'));
  player.on('start', () => console.log('[cmsv9] start'));
  player.on('timeout', () => console.log('[cmsv9] timeout'));
  player.on('loadingTimeout', () => console.log('[cmsv9] loadingTimeout'));
  player.play(resolveUrl(url)).then(
    () => console.log('[cmsv9] play() resolved'),
    (e) => console.log('[cmsv9] play() rejected:', e),
  );
  return player;
}

// Jessibuca starts every stream muted (isNotMute is off). Turning a speaker
// on also resumes the audio context, which the browser suspends until the
// page has had a click - and this is only ever called from one.
function setPlayerAudio(player, on) {
  if (!player) return;
  try {
    if (on) {
      player.audioResume?.();
      player.cancelMute?.();
    } else {
      player.mute?.();
    }
  } catch (e) {
    // a player mid-teardown; nothing to hear from it anyway
  }
}

function destroyFlvPlayer(player) {
  if (player) {
    try {
      player.destroy();
    } catch (e) {
      // ignore cleanup errors
    }
  }
}

async function waitForStreamReady(deviceId, channel, timeoutMs, cancelFn) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (cancelFn && cancelFn()) return false;
    try {
      const data = await cmsv9StreamStatus(deviceId, channel);
      if (data.ready) return true;
    } catch (e) {
      // keep polling while device starts pushing
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return false;
}

function resolveUrl(url) {
  try {
    return new URL(url, window.location.origin).href;
  } catch (e) {
    return url;
  }
}

async function waitForStream(url, timeoutMs = 45000, cancelFn) {
  const absolute = resolveUrl(url);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (cancelFn && cancelFn()) return false;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 1200);
      const res = await fetch(absolute, { signal: controller.signal, cache: 'no-store' });
      clearTimeout(timer);
      if (res.ok) {
        // We only need to know the stream exists. Abort immediately so this probe
        // does not hold a streaming connection open — otherwise N channels leak N
        // connections and blow past the browser's ~6-per-host limit, leaving no
        // sockets for the actual players (the "only 2 channels play" bug).
        controller.abort();
        return true;
      }
    } catch (e) {
      // keep polling while device starts pushing
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return false;
}

const Cmsv9VideoPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const t = useTranslation();

  const videoRef = useRef(null);
  const flvPlayerRef = useRef(null);
  const gridPlayers = useRef({});
  // Which tile is filling the screen, and when each tile was last tapped, so a
  // second tap soon after counts as a double. onDoubleClick is not dependable
  // on a touch screen - a browser that treats the first tap as a zoom gesture
  // never sends it - so the pair is timed here.
  const [fullscreenChannel, setFullscreenChannel] = useState(null);
  const lastTapRef = useRef({ ch: null, at: 0 });
  const cellElsRef = useRef({});
  // Which tile's microphone is being listened to. Every tile's stream carries
  // its cab audio (the DVR is asked for audio and video together), but they
  // all start muted: four microphones in one cab at once is noise, and a
  // browser will not autoplay sound anyway. One speaker is on at a time. The
  // ref is what a tile restarted behind the user's back reads, so it comes
  // back with its sound on rather than silently muted.
  const [audioChannel, setAudioChannel] = useState(null);
  const audioChannelRef = useRef(null);

  const [searchParams] = useSearchParams();
  const deviceId = searchParams.get('deviceId');
  const device = useSelector((state) => state.devices.items[deviceId]);
  // Live position of this vehicle, for the map under the video.
  const position = useSelector((state) => state.session.positions[deviceId]);

  const defaultChannels = useAttributePreference('cmsv9Channels', 4);

  const cmsv9DeviceId = device?.attributes?.cmsv9DeviceId;

  // Tachograph, over the map. The vehicle's own unit sends the driver's hours
  // with its positions, so the panel needs nothing from the server that the
  // map is not already receiving.
  const live = useTachoLive(deviceId, position);
  // Shown for a vehicle whose tracker can carry a tachograph, even before any
  // data has arrived - an empty panel that says so beats no sign of the feature
  // at all on a vehicle that is meant to have it. Camera-only vehicles get nothing.
  const tachoCapable = live.hasData || /FM[BC]\d?6/i.test(device?.attributes?.trackerModel || '');
  // The app's Home and Compliance shortcuts normally live stacked in the map's
  // bottom-right corner. On this page that corner is taken by the map's own
  // zoom and location controls, so here they move up into the controls row
  // instead (and App.jsx hides the stacked pair on this route).
  const complianceAccess = useComplianceAccess();
  const [tachoOpen, setTachoOpen] = useState(() => {
    try {
      return window.localStorage.getItem('dhfv-tacho-hidden') !== '1';
    } catch (e) {
      return true;
    }
  });
  const showTacho = useCallback((open) => {
    setTachoOpen(open);
    try {
      window.localStorage.setItem('dhfv-tacho-hidden', open ? '0' : '1');
    } catch (e) {
      // the choice is not remembered; the panel still opens and closes
    }
  }, []);

  // Whatever takes the user back out of here - the arrow above, the phone's own
  // back button, the app's back gesture - lands on the Map view with the vehicle
  // list under it, not the dashboard. The arrow asks with ?view=map, but the
  // other two just pop history to "/" and MainPage then shows whichever view
  // was last saved; so the choice is saved the moment the cameras open. Home
  // goes to the same place: from here, "home" is the map with the fleet on it.
  useEffect(() => {
    savePersistedState('fleetView', 'map');
  }, []);

  // Land on the multi-channel grid, not a single camera. Tapping a vehicle in
  // the list comes straight here, and the whole point of that is seeing every
  // channel next to the map without hunting for the right one first.
  //
  // The channels do not start on their own. Auto-play was tried and taken out
  // again (54013881): arriving on a page should not open four live streams off
  // a vehicle's 4G, and a stuck push session makes the device refuse the next
  // play. One tap on the grid starts them.
  const [tab, setTab] = useState(1);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [channel, setChannel] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [liveError, setLiveError] = useState(false);
  const [playbackActive, setPlaybackActive] = useState(false);
  // The clip being reviewed, and where we are in it.
  const reviewRef = useRef(null);
  const [reviewUrl, setReviewUrl] = useState('');
  const [reviewRate, setReviewRate] = useState(1);
  const [reviewAt, setReviewAt] = useState(0);
  const [reviewLength, setReviewLength] = useState(0);
  const [reviewRunning, setReviewRunning] = useState(false);
  const [reviewWaiting, setReviewWaiting] = useState(false);
  const [playerMsg, setPlayerMsg] = useState('');

  const [gridActive, setGridActive] = useState(false);
  const [gridHd, setGridHd] = useState(false);
  const gridHdRef = useRef(false);
  const [singleHd, setSingleHd] = useState(true);
  const singleHdRef = useRef(true);
  const [gridErrors, setGridErrors] = useState({});

  const [from, setFrom] = useState(dayjs().subtract(1, 'hour'));
  const [to, setTo] = useState(dayjs());
  const [searching, setSearching] = useState(false);
  const [recordings, setRecordings] = useState([]);
  const [timelineDate, setTimelineDate] = useState(dayjs());
  const [segments, setSegments] = useState([]);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [trimStart, setTrimStart] = useState(null);
  const [trimEnd, setTrimEnd] = useState(null);
  // Fetching a clip off a vehicle: what we are fetching, and how far it has got.
  const [clipJob, setClipJob] = useState(null);
  const clipJobRef = useRef(null);

  const channels = useMemo(() => {
    const n = config?.channels || Number(defaultChannels) || 4;
    return Array.from({ length: Math.min(Math.max(Number(n), 1), 16) }, (_, i) => i);
  }, [config, defaultChannels]);

  // Show channels four-up (2x2), paged by CH1-4 / CH5-8 groups like the DVR app.
  const channelGroups = useMemo(() => {
    const groups = [];
    for (let i = 0; i < channels.length; i += 4) {
      groups.push(channels.slice(i, i + 4));
    }
    return groups.length ? groups : [[]];
  }, [channels]);
  const [activeGroup, setActiveGroup] = useState(0);
  const visibleChannels = useMemo(
    () => channelGroups[Math.min(activeGroup, channelGroups.length - 1)] || [],
    [channelGroups, activeGroup],
  );
  const [selectedChannel, setSelectedChannel] = useState(null);

  const ensureConfig = useCallback(async () => {
    if (config) return config;
    setLoading(true);
    setError(null);
    try {
      const data = await cmsv9GetConfig(deviceId);
      if (data.configured) {
        setConfig(data);
        return data;
      }
      throw new Error('CMSV9 not configured on server');
    } catch (e) {
      setError(e.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [config, deviceId]);

  useEffect(() => {
    if (cmsv9DeviceId) {
      ensureConfig();
    }
  }, [cmsv9DeviceId, ensureConfig]);

  const stopPlayback = useCallback(() => {
    destroyFlvPlayer(flvPlayerRef.current);
    flvPlayerRef.current = null;
    if (videoRef.current) {
      videoRef.current.innerHTML = '';
    }
    setPlaying(false);
  }, []);

  const cancelledRef = useRef(false);
  const activeChannelRef = useRef(null);

  const startLive = useCallback(async () => {
    setLiveError(false);
    setPlayerMsg('');
    stopPlayback();
    await ensureConfig();
    if (!cmsv9DeviceId) return;

    cancelledRef.current = false;
    activeChannelRef.current = channel;
    setLoading(true);
    try {
      const data = await cmsv9StartLive(deviceId, channel, singleHdRef.current ? 0 : 1);
      if (data.errCode !== 0 && data.errCode !== -1) {
        throw new Error(data.resultMsg || 'Failed to start live');
      }
      const { flvUrl } = data;
      if (!flvUrl) throw new Error('No stream URL returned');
      setPlaying(true);
      const found = await waitForStream(flvUrl, 90000, () => cancelledRef.current);
      if (!found) {
        if (!cancelledRef.current) {
          setLiveError(true);
          setPlaying(false);
        }
        return;
      }
      if (!videoRef.current || cancelledRef.current) return;
      const player = await createFlvPlayer(videoRef.current, flvUrl, { isResize: true });
      if (!player) {
        setLiveError(true);
        setPlaying(false);
        return;
      }
      flvPlayerRef.current = player;
      const timeout = setTimeout(() => {
        setLiveError(true);
        setPlaying(false);
        destroyFlvPlayer(player);
        flvPlayerRef.current = null;
      }, 30000);
      player.on('videoInfo', () => {
        clearTimeout(timeout);
      });
      player.on('error', (err) => {
        clearTimeout(timeout);
        setPlayerMsg(String(err || 'decode error'));
        setLiveError(true);
        setPlaying(false);
      });
    } catch (e) {
      setLiveError(true);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [ensureConfig, cmsv9DeviceId, deviceId, channel, stopPlayback]);

  const doStopLive = useCallback(async () => {
    cancelledRef.current = true;
    activeChannelRef.current = null;
    stopPlayback();
    if (cmsv9DeviceId) {
      try {
        await cmsv9StopLive(deviceId, channel);
      } catch (e) {
        // ignore
      }
    }
  }, [cmsv9DeviceId, channel, stopPlayback]);

  // Switch the single-channel view between HD (DVR main stream) and SD (sub
  // stream). A ref feeds startLive so the memoised callback always reads the
  // latest choice; toggling while playing restarts the stream at the new quality.
  const setSingleQuality = useCallback(
    (hd) => {
      setSingleHd(hd);
      singleHdRef.current = hd;
      if (playing) {
        doStopLive();
        setTimeout(() => startLive(), 350);
      }
    },
    [playing, doStopLive, startLive],
  );

  const unmountStateRef = useRef({ deviceId, cmsv9DeviceId });
  unmountStateRef.current = { deviceId, cmsv9DeviceId };
  useEffect(
    () => () => {
      cancelledRef.current = true;
      stopPlayback();
      const state = unmountStateRef.current;
      const channelId = activeChannelRef.current;
      if (state.cmsv9DeviceId && channelId != null) {
        try {
          cmsv9StopLive(state.deviceId, channelId).catch(() => {});
        } catch (e) {
          // ignore
        }
      }
    },
    [stopPlayback],
  );

  const [pendingMaximize, setPendingMaximize] = useState(null);

  useEffect(() => {
    if (gridActive && visibleChannels.length && !visibleChannels.includes(selectedChannel)) {
      setSelectedChannel(visibleChannels[0]);
    }
  }, [gridActive, visibleChannels, selectedChannel]);

  const stopGrid = useCallback(() => {
    cancelledRef.current = true;
    channels.forEach((ch) => {
      destroyFlvPlayer(gridPlayers.current[ch]?.player);
      delete gridPlayers.current[ch];
      if (cmsv9DeviceId) {
        try {
          cmsv9StopLive(deviceId, ch).catch(() => {});
        } catch (e) {
          // ignore
        }
      }
    });
    setGridActive(false);
    setGridErrors({});
  }, [channels, cmsv9DeviceId, deviceId]);

  useEffect(() => {
    if (pendingMaximize !== null && tab === 0) {
      setPendingMaximize(null);
      startLive();
    }
  }, [pendingMaximize, tab, startLive]);

  const maximizeChannel = useCallback(
    (ch) => {
      stopGrid();
      setChannel(ch);
      setTab(0);
      setPendingMaximize(ch);
    },
    [stopGrid],
  );

  const startGrid = useCallback(async () => {
    await ensureConfig();
    if (!cmsv9DeviceId) return;
    cancelledRef.current = false;
    setGridErrors({});
    setGridActive(true);
  }, [ensureConfig, cmsv9DeviceId]);

  // Switch the grid between the DVR's main (HD) and sub (SD) streams. HD is
  // heavier over the vehicle's cellular uplink, so a full grid may struggle;
  // SD stays the default for reliable multi-channel. Toggling restarts the grid.
  // Start the cameras on arrival rather than making the operator press Play
  // for something they already asked for by tapping the vehicle. Goes through
  // startGrid, the same path the button uses, so the staggered tile startup
  // and the error handling are identical.
  //
  // Once per visit: the ref is what stops a re-render, a quality toggle or a
  // stop-then-start from re-triggering it. Pressing Stop has to mean stopped.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (autoStarted.current || tab !== 1 || !cmsv9DeviceId) return;
    autoStarted.current = true;
    startGrid();
  }, [tab, cmsv9DeviceId, startGrid]);

  // Leaving the page stops the cameras. A play order left running keeps the
  // vehicle uploading over its own 4G, and can leave a push session the DVR
  // then refuses to replace - which is why auto-play was removed last time.
  //
  // The deps are empty on purpose, and stopGrid is reached through a ref.
  // Depending on stopGrid directly looks harmless and is not: it is rebuilt
  // whenever `channels` is, `channels` is rebuilt when the config arrives,
  // and the config arrives moments after the grid starts - so the effect
  // would re-run and fire its cleanup, stopping the cameras it just started.
  const stopGridRef = useRef(stopGrid);
  stopGridRef.current = stopGrid;
  useEffect(() => () => stopGridRef.current(), []);

  const setGridQuality = useCallback(
    (hd) => {
      setGridHd(hd);
      gridHdRef.current = hd;
      if (gridActive) {
        stopGrid();
        setTimeout(() => startGrid(), 350);
      }
    },
    [gridActive, stopGrid, startGrid],
  );

  // Starts one tile of the grid, and restarts it if the picture stops arriving.
  // A live stream can stall a few seconds in (the vehicle's uplink drops frames,
  // or the DVR stops feeding); the player retries on its own first, and if that
  // fails we ask the DVR for the channel again, up to GRID_RESTART_LIMIT times.
  const startChannel = useCallback(
    async (ch, attempt = 0) => {
      const entry = gridPlayers.current[ch];
      const videoEl = entry?.videoEl;
      if (!videoEl || cancelledRef.current) return;
      clearTimeout(entry?.timer);
      destroyFlvPlayer(entry?.player);
      gridPlayers.current[ch] = { videoEl };
      setGridErrors((prev) => {
        if (!prev[ch]) return prev;
        const next = { ...prev };
        delete next[ch];
        return next;
      });

      const stalled = (reason) => {
        if (cancelledRef.current || gridPlayers.current[ch]?.videoEl !== videoEl) return;
        if (attempt + 1 < GRID_RESTART_LIMIT) {
          console.log(`[cmsv9] channel ${ch + 1} ${reason}; restarting (attempt ${attempt + 2})`);
          gridPlayers.current[ch] = {
            videoEl,
            timer: setTimeout(() => startChannel(ch, attempt + 1), GRID_RESTART_DELAY_MS),
          };
        } else {
          setGridErrors((prev) => ({ ...prev, [ch]: 'stalled' }));
        }
      };

      try {
        const data = await cmsv9StartLive(deviceId, ch, gridHdRef.current ? 0 : 1);
        if ((data.errCode !== 0 && data.errCode !== -1) || !data.flvUrl) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'novideo' }));
          return;
        }
        const found = await waitForStream(data.flvUrl, 150000, () => cancelledRef.current);
        if (!found) {
          if (!cancelledRef.current) {
            setGridErrors((prev) => ({ ...prev, [ch]: 'novideo' }));
          }
          return;
        }
        if (cancelledRef.current || gridPlayers.current[ch]?.videoEl !== videoEl) return;
        // Keep the picture's own shape inside the tile. Stretching to fill was
        // fine while every tile was locked to 4:3; now that a tile is whatever
        // share of the grid it gets, stretching would squash the image.
        const player = await createFlvPlayer(videoEl, data.flvUrl, {
          isResize: true,
        });
        if (!player) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
          return;
        }
        if (audioChannelRef.current === ch) setPlayerAudio(player, true);
        // No picture at all within this window counts as a stall too.
        const timer = setTimeout(() => stalled('never showed a picture'), GRID_FIRST_FRAME_MS);
        gridPlayers.current[ch] = { player, videoEl, timer };
        videoEl.dataset.attached = '1';
        player.on('videoInfo', () => clearTimeout(gridPlayers.current[ch]?.timer));
        player.on('timeout', () => stalled('stopped sending video'));
        player.on('error', () => stalled('reported an error'));
      } catch (e) {
        if (!cancelledRef.current) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
        }
      }
    },
    [deviceId],
  );

  useEffect(() => {
    if (!gridActive || !config) return;
    cancelledRef.current = false;
    visibleChannels.forEach(async (ch, idx) => {
      const videoEl = gridPlayers.current[ch]?.videoEl;
      if (!videoEl || videoEl.dataset.attached) return;
      // Stagger startup: N tiles firing play-orders and spinning up N WASM
      // H.265 decoders at the same instant is what makes multi-channel struggle.
      if (idx > 0) {
        await new Promise((resolve) => setTimeout(resolve, idx * 400));
        if (cancelledRef.current) return;
      }
      startChannel(ch, 0);
    });
    return () => {
      cancelledRef.current = true;
      visibleChannels.forEach((ch) => {
        clearTimeout(gridPlayers.current[ch]?.timer);
        destroyFlvPlayer(gridPlayers.current[ch]?.player);
        if (gridPlayers.current[ch]?.videoEl) {
          delete gridPlayers.current[ch].videoEl.dataset.attached;
        }
        delete gridPlayers.current[ch];
        if (cmsv9DeviceId) {
          try {
            cmsv9StopLive(deviceId, ch).catch(() => {});
          } catch (e) {
            // ignore
          }
        }
      });
    };
  }, [gridActive, config, cmsv9DeviceId, deviceId, visibleChannels, startChannel]);

  /* Jessibuca measures its container once and draws to a canvas of that size,
   * so a tile that changes shape keeps the old picture until it is told. Give
   * the browser a frame to lay the new size out first. */
  const remeasure = useCallback((ch) => {
    requestAnimationFrame(() => {
      const player = gridPlayers.current[ch]?.player;
      try {
        player?.resize?.();
      } catch {
        // An older build without resize() still redraws on the next frame.
      }
    });
  }, []);

  const exitFullscreen = useCallback(() => {
    setFullscreenChannel((was) => {
      if (was !== null) remeasure(was);
      return null;
    });
    try {
      if (document.fullscreenElement) document.exitFullscreen?.();
    } catch {
      // Never granted in the first place; the CSS layer is what mattered.
    }
    try {
      window.screen?.orientation?.unlock?.();
    } catch {
      // Not supported, or not allowed outside fullscreen. Harmless.
    }
  }, [remeasure]);

  const enterFullscreen = useCallback((ch) => {
    setFullscreenChannel(ch);
    remeasure(ch);
    // Asked for on top of the CSS, not instead of it: where it is granted the
    // system bars go too, and a phone held upright gets the landscape turn
    // that makes a 4:3 camera worth looking at. Both are refused often enough
    // that neither can be relied on, and neither is needed for this to work.
    const el = cellElsRef.current[ch];
    try {
      el?.requestFullscreen?.({ navigationUI: 'hide' })
        .then(() => window.screen?.orientation?.lock?.('landscape'))
        .catch(() => {})
        .finally(() => remeasure(ch));
    } catch {
      // Older WebViews throw rather than reject.
    }
  }, [remeasure]);

  // The speaker on a tile: on for that camera, off for every other. Works the
  // same while a tile fills the screen, because the tile (and its player) is
  // the same element either way - nothing is torn down going in or out.
  const toggleAudio = useCallback((ch) => {
    const next = audioChannelRef.current === ch ? null : ch;
    Object.entries(gridPlayers.current).forEach(([key, entry]) => {
      setPlayerAudio(entry?.player, Number(key) === next);
    });
    audioChannelRef.current = next;
    setAudioChannel(next);
  }, []);

  /* A tile's own tap handling: one tap selects it (or retries a dead channel),
   * two in quick succession fill the screen. */
  const handleCellTap = useCallback((ch) => {
    const now = Date.now();
    const isDouble = lastTapRef.current.ch === ch && now - lastTapRef.current.at < 320;
    // A double consumes both taps: the pair is forgotten by channel, not by
    // pushing the time out of range, so a third tap straight after starts a
    // fresh pair instead of toggling again.
    lastTapRef.current = { ch: isDouble ? null : ch, at: now };
    if (isDouble) {
      if (fullscreenChannel === ch) exitFullscreen();
      else enterFullscreen(ch);
      return;
    }
    if (gridErrors[ch]) startChannel(ch, 0);
    else setSelectedChannel(ch);
  }, [fullscreenChannel, gridErrors, startChannel, enterFullscreen, exitFullscreen]);

  // Back out of fullscreen the ways people expect: Escape, the Android back
  // button (which closes native fullscreen without telling React), and leaving
  // the page entirely.
  useEffect(() => {
    if (fullscreenChannel === null) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') exitFullscreen(); };
    const onChange = () => { if (!document.fullscreenElement) setFullscreenChannel(null); };
    const onResize = () => remeasure(fullscreenChannel);
    window.addEventListener('keydown', onKey);
    document.addEventListener('fullscreenchange', onChange);
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('fullscreenchange', onChange);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, [fullscreenChannel, exitFullscreen, remeasure]);

  const takeSnapshot = useCatch(
    async (player) => {
      if (!player || typeof player.screenshot !== 'function') return;
      const base64 = player.screenshot('snapshot', 'png', 0.92, 'base64');
      if (!base64) return;
      const link = document.createElement('a');
      link.download = `cmsv9-${cmsv9DeviceId}-${dayjs().format('YYYYMMDD-HHmmss')}.png`;
      link.href = base64;
      link.click();
    },
    [cmsv9DeviceId],
  );

  const doSearch = useCatchCallback(async () => {
    const cfg = await ensureConfig();
    if (!cfg) return;
    setSearching(true);
    try {
      const data = await cmsv9Search({
        deviceId: deviceId,
        channel,
        from: from.format('YYYY-MM-DD'),
        to: to.format('YYYY-MM-DD'),
        type: '1',
      });
      const list = data?.resultData?.list || [];
      setRecordings(Array.isArray(list) ? list : []);
    } finally {
      setSearching(false);
    }
  }, [ensureConfig, cmsv9DeviceId, channel, from, to]);

  const loadTimeline = useCatchCallback(async () => {
    const cfg = await ensureConfig();
    if (!cfg) return;
    setLoadingTimeline(true);
    try {
      const data = await cmsv9History(
        deviceId,
        channel,
        timelineDate.format('YYYY-MM-DD 00:00:00'),
        timelineDate.format('YYYY-MM-DD 23:59:59'),
      );
      const list = data?.resultData || [];
      setSegments(Array.isArray(list) ? list : []);
    } finally {
      setLoadingTimeline(false);
    }
  }, [ensureConfig, deviceId, channel, timelineDate]);

  useEffect(() => {
    if (tab === 2 && cmsv9DeviceId) {
      loadTimeline();
    }
  }, [tab, timelineDate, channel, cmsv9DeviceId]);

  // Footage does not arrive as a file. The camera plays it back off its own SD
  // card in real time over the vehicle's mobile connection, so a ten minute
  // clip takes ten minutes and costs the SIM about 220 MB. Worse, the relay
  // gives every playback of a channel the same name, so two requests for the
  // same camera fight over one stream and both end after a few seconds - a
  // browser asking twice for one download was enough to cause it.
  //
  // So a clip is fetched once, on the server, and kept. This asks for that
  // fetch and waits for it, reporting progress; afterwards the same clip is
  // served from disk, instantly and without touching the vehicle again.
  const clipUrl = useCallback(
    (startStr, endStr, share) =>
      `/api/cmsv9/download/${deviceId}/${channel}` +
      `?startTime=${encodeURIComponent(startStr)}` +
      `&endTime=${encodeURIComponent(endStr)}` +
      (share ? '&format=share&disposition=attachment' : ''),
    [deviceId, channel],
  );

  const fetchClip = useCallback(
    async (startStr, endStr, share, label) => {
      const query =
        `?startTime=${encodeURIComponent(startStr)}` +
        `&endTime=${encodeURIComponent(endStr)}` +
        (share ? '&format=share' : '');
      const base = `/api/cmsv9/clip/${deviceId}/${channel}${query}`;
      const token = {};
      clipJobRef.current = token;
      try {
        const started = await fetch(base, { method: 'POST' });
        if (!started.ok) {
          // The server answers a rejected request with a Java exception and its
          // stack; the sentence on the first line is the part worth showing.
          const body = await started.text();
          const first = (body || '').split('\n')[0].replace(/^[\w.]+Exception:\s*/, '');
          throw new Error(first || 'The clip could not be requested.');
        }
        let state = await started.json();
        setClipJob({ label, share, ...state });
        // Nothing to wait for when the server already has it.
        while (!state.ready) {
          await new Promise((resolve) => {
            setTimeout(resolve, 2000);
          });
          if (clipJobRef.current !== token) return null;
          const poll = await fetch(base);
          if (!poll.ok) throw new Error('Lost contact with the server while fetching the clip.');
          state = await poll.json();
          setClipJob({ label, share, ...state });
          if (!state.ready && !state.working) {
            throw new Error('The camera stopped sending that footage. It may be offline.');
          }
        }
        setClipJob(null);
        return clipUrl(startStr, endStr, share);
      } catch (e) {
        if (clipJobRef.current === token) {
          setClipJob(null);
          setPlayerMsg(e.message);
        }
        return null;
      } finally {
        if (clipJobRef.current === token) clipJobRef.current = null;
      }
    },
    [deviceId, channel, clipUrl],
  );

  // Reviewing a clip is a different job from watching a live picture, and it
  // needs a different player: a complete MP4 in the browser's own video element
  // gives real seeking and any speed we ask for, which a pushed FLV cannot.
  const reviewClip = useCallback(
    async (startStr, endStr) => {
      cancelledRef.current = true;
      stopPlayback();
      setPlaybackActive(false);
      setLiveError(false);
      setReviewRate(1);
      setReviewUrl('');
      const url = await fetchClip(startStr, endStr, false, 'Preview');
      if (url) setReviewUrl(url);
    },
    [fetchClip, stopPlayback],
  );

  // Start the clip without waiting for the play arrow.
  //
  // Two things have to be true and neither is reliable as JSX alone. The
  // element must really be muted - React sets muted as an attribute, which
  // the browser does not always honour as the property its autoplay policy
  // actually reads - and play() has to be called after the new source is
  // attached. Doing both here, on the element itself, is what makes Preview
  // behave like pressing play.
  //
  // A rejection is not a failure: the browser has declined, and the user
  // presses play exactly as before.
  useEffect(() => {
    const el = reviewRef.current;
    if (!el || !reviewUrl) return;
    el.muted = true;
    el.load();
    el.play?.().catch(() => {});
  }, [reviewUrl]);

  const setRate = useCallback((rate) => {
    setReviewRate(rate);
    if (reviewRef.current) reviewRef.current.playbackRate = rate;
  }, []);

  // format=share re-encodes to H.264 with the index at the front. Without it
  // the file is the camera's own H.265 in a fragmented container: fine in VLC
  // or on a PC, but WhatsApp and the phone galleries refuse it. The re-encode
  // is done from the copy the server already holds, so previewing a clip and
  // then downloading it costs one trip to the vehicle, not two.
  //
  // The save happens only once the server has the whole clip, so the browser's
  // download manager gets a complete file with a length it can resume - it is
  // free to ask again, which it does, and that ask no longer reaches the
  // vehicle.
  const downloadSegment = useCallback(
    async (startStr, endStr) => {
      const url = await fetchClip(startStr, endStr, true, 'Download');
      if (!url) return;
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
    },
    [fetchClip],
  );

  const playRecording = useCallback(
    async (item) => {
      setLiveError(false);
      setPlaybackActive(false);
      stopPlayback();
      if (!cmsv9DeviceId) return;
      setLoading(true);
      cancelledRef.current = false;
      try {
        const data = await cmsv9StartPlayback(
          deviceId,
          channel,
          item.startTime || from.format('YYYY-MM-DD HH:mm:ss'),
          item.endTime || to.format('YYYY-MM-DD HH:mm:ss'),
        );
        if (data.errCode !== 0 && data.errCode !== -1) {
          throw new Error(data.resultMsg || 'Failed to start playback');
        }
        const { flvUrl } = data;
        if (!flvUrl) throw new Error('No playback URL returned');
        setPlaying(true);
        // The platform pushes the recorded segment to the portal relay as a
        // regular FLV stream, so it plays directly in the browser just like
        // live does.
        const found = await waitForStream(flvUrl, 90000, () => cancelledRef.current);
        if (!found) {
          if (!cancelledRef.current) {
            setLiveError(true);
            setPlaying(false);
          }
          return;
        }
        if (!videoRef.current || cancelledRef.current) return;
        const player = await createFlvPlayer(videoRef.current, flvUrl, { isResize: true });
        flvPlayerRef.current = player;
        if (!player) {
          setLiveError(true);
          setPlaying(false);
          return;
        }
        const timeout = setTimeout(() => {
          setLiveError(true);
          setPlaying(false);
          destroyFlvPlayer(player);
          flvPlayerRef.current = null;
        }, 30000);
        player.on('videoInfo', () => {
          clearTimeout(timeout);
          setPlaybackActive(true);
        });
        player.on('error', () => {
          clearTimeout(timeout);
          setLiveError(true);
          setPlaying(false);
        });
      } catch (e) {
        setLiveError(true);
        setError(e.message);
      } finally {
        setLoading(false);
      }
    },
    [cmsv9DeviceId, channel, from, to, stopPlayback],
  );

  const configured = Boolean(cmsv9DeviceId);

  return (
    <div className={classes.root}>
      <AppBar
        position="static"
        color="transparent"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: 'divider' }}
      >
        <Toolbar>
          {/* Back lands on the Map view (live map over the vehicle list), not
              wherever history happens to point - that was the dashboard, and
              the office wants the map. MainPage consumes ?view=map. */}
          <IconButton edge="start" sx={{ mr: 2 }} onClick={() => navigate('/?view=map')}>
            <BackIcon />
          </IconButton>
          <Typography variant="h6" className={classes.title}>
            {device?.name || t('linkLiveVideo')}
          </Typography>
          <Tabs
            value={tab}
            onChange={(_, value) => setTab(value)}
            className={classes.tab}
            variant="scrollable"
            scrollButtons="auto"
            allowScrollButtonsMobile
          >
            {/* The single-camera view is gone: this page shows every channel at
                once. Values are explicit so Multi stays 1 and Download stays 2,
                rather than every tab check in the file shifting by one. */}
            <Tab value={1} label={t('cmsv9Multi')} icon={<GridViewIcon />} iconPosition="start" />
            <Tab value={2} label="Download" icon={<DownloadIcon />} iconPosition="start" />
          </Tabs>
        </Toolbar>
      </AppBar>
      {!configured && (
        <Box sx={{ p: 3, textAlign: 'center' }}>
          <Typography color="textSecondary">{t('cmsv9NotConfigured')}</Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>
            {t('cmsv9NotConfiguredHint')}
          </Typography>
        </Box>
      )}
      {configured && (
        <>
          {/* Quality only. The channel picker drove the single-camera view, which
              no longer exists, and the play button is redundant now the grid starts
              on arrival - between them they cost a row of height the map is better
              off having. */}
          <div className={classes.controls}>
            {/* Download works on one channel at a time - you pick the camera you
                want the footage from - so the picker belongs here. It is gone from
                the live grid, which plays every channel at once. */}
            {tab === 2 && (
              <TextField
                select
                size="small"
                label={t('sharedChannel')}
                value={channel}
                onChange={(e) => setChannel(Number(e.target.value))}
                sx={{ minWidth: 130 }}
              >
                {channels.map((ch) => (
                  <MenuItem key={ch} value={ch}>
                    {t('sharedChannel')} {ch + 1}
                  </MenuItem>
                ))}
              </TextField>
            )}
            {tab === 1 && (
              <Button
                variant={gridHd ? 'contained' : 'outlined'}
                size="small"
                onClick={() => setGridQuality(!gridHd)}
                title="Toggle live quality. HD uses the DVR main stream; SD (default) is lighter for multi-channel."
              >
                {gridHd ? 'HD' : 'SD'}
              </Button>
            )}
            {/* Shows and hides the tachograph panel. It lives up here rather than
                on the map because the map's right-hand corner already carries the
                app's fixed Home and Compliance buttons and the map's own controls,
                and anything put there ends up underneath them. */}
            {tab === 1 && tachoCapable && (
              <Button
                variant={tachoOpen ? 'contained' : 'outlined'}
                size="small"
                startIcon={<AccessTimeIcon />}
                onClick={() => showTacho(!tachoOpen)}
                title="Show the driver's tachograph hours over the map"
              >
                Tacho
              </Button>
            )}
            {loading && <CircularProgress size={20} />}
            {/* Home and Compliance, pushed to the far right of this row so they
                sit beside the Tacho toggle rather than stacked over the map's
                own controls in the bottom-right corner. */}
            <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
              <IconButton
                size="small"
                onClick={() => navigate('/?view=map')}
                title="Home"
                aria-label="Home"
              >
                <HomeRoundedIcon fontSize="small" />
              </IconButton>
              {complianceAccess && (
                <IconButton
                  size="small"
                  component="a"
                  href="/tacho/compliance"
                  title="Compliance hub"
                  aria-label="Compliance hub"
                >
                  <FactCheckRoundedIcon fontSize="small" />
                </IconButton>
              )}
            </Box>
          </div>
          {error && (
            <Box sx={{ px: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography color="error" variant="body2">
                {t('cmsv9LoginFailed')}: {error}
              </Typography>
              <Button
                size="small"
                variant="outlined"
                onClick={() => {
                  setConfig(null);
                  ensureConfig();
                }}
              >
                {t('sharedRetry')}
              </Button>
            </Box>
          )}
          {tab === 0 && (
            <div className={`${classes.video} ${classes.videoHalf}`}>
              {playing && !liveError && <div ref={videoRef} className={classes.player} />}
              {liveError && (
                <Typography className={classes.overlay}>
                  {playerMsg || t('errorConnection')}
                </Typography>
              )}
              {!playing && !liveError && (
                <Typography className={classes.overlay}>{t('sharedPlay')}</Typography>
              )}
            </div>
          )}
          {tab === 1 && channelGroups.length > 1 && (
            <div className={classes.groupTabs}>
              {channelGroups.map((grp, gi) => (
                <Chip
                  key={gi}
                  label={`CH${grp[0] + 1}-${grp[grp.length - 1] + 1}`}
                  color={activeGroup === gi ? 'primary' : 'default'}
                  onClick={() => setActiveGroup(gi)}
                  size="small"
                />
              ))}
            </div>
          )}
          {tab === 1 && (
            <div
              className={`${classes.grid} ${classes.gridWithMap}`}
              style={gridShape(visibleChannels.length)}
            >
              {visibleChannels.map((ch) => (
                <div
                  key={ch}
                  ref={(el) => { cellElsRef.current[ch] = el; }}
                  className={[
                    classes.cell,
                    selectedChannel === ch ? classes.cellSelected : '',
                    fullscreenChannel === ch ? classes.cellFullscreen : '',
                  ].filter(Boolean).join(' ')}
                  // Hidden rather than unmounted: unmounting would tear the
                  // player down and the stream would have to be asked for
                  // again on the way back.
                  hidden={fullscreenChannel !== null && fullscreenChannel !== ch}
                  onClick={() => handleCellTap(ch)}
                >
                  <Chip
                    label={`${device?.name ? `${device.name} - ` : ''}CH${ch + 1}`}
                    size="small"
                    className={classes.cellLabel}
                  />
                  {fullscreenChannel === ch && (
                    <Typography className={classes.fullscreenHint}>
                      Double tap to go back
                    </Typography>
                  )}
                  {gridActive && !gridErrors[ch] && (
                    <div
                      ref={(el) => {
                        if (el)
                          gridPlayers.current[ch] = { ...gridPlayers.current[ch], videoEl: el };
                      }}
                      className={classes.cellVideo}
                    />
                  )}
                  {(!gridActive || gridErrors[ch]) && (
                    <Typography className={classes.cellPlaceholder}>
                      {gridErrors[ch] === 'novideo' && `${t('cmsv9NoVideo')} — tap to retry`}
                      {gridErrors[ch] === 'stalled' && 'Picture stopped — tap to retry'}
                      {gridErrors[ch] === 'error' && `${t('errorConnection')} — tap to retry`}
                      {!gridErrors[ch] && t('sharedPlay')}
                    </Typography>
                  )}
                  <div className={classes.cellActions}>
                    {/* Filling the screen is a double tap on the tile itself,
                        so there is no expand control here to get in the way of
                        it. The snapshot swallows its own taps: two of them in
                        a row are two photographs, not a request for
                        fullscreen. */}
                    <IconButton
                      size="small"
                      className={`${classes.cellButton}${audioChannel === ch ? ` ${classes.cellButtonOn}` : ''}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleAudio(ch);
                      }}
                      disabled={!gridActive || gridErrors[ch]}
                      title={audioChannel === ch ? 'Mute this camera' : 'Listen to this camera'}
                      aria-label={audioChannel === ch ? 'Mute this camera' : 'Listen to this camera'}
                      aria-pressed={audioChannel === ch}
                    >
                      {audioChannel === ch
                        ? <VolumeUpIcon fontSize="small" />
                        : <VolumeOffIcon fontSize="small" />}
                    </IconButton>
                    <IconButton
                      size="small"
                      className={classes.cellButton}
                      onClick={(e) => {
                        e.stopPropagation();
                        const ctx = gridPlayers.current[ch];
                        takeSnapshot(ctx?.player);
                      }}
                      disabled={!gridActive || gridErrors[ch]}
                    >
                      <PhotoCameraIcon fontSize="small" />
                    </IconButton>
                  </div>
                </div>
              ))}
            </div>
          )}
          {(tab === 0 || tab === 1) && (
            <div className={`${classes.mapArea}${tab === 0 ? ` ${classes.mapHalf}` : ''}`}>
              <MapView>
                <MapPositionMarkers positions={position ? [position] : []} showStatus />
              </MapView>
              <MapScale />
              <MapCurrentLocation />
              {position && (
                <MapCamera latitude={position.latitude} longitude={position.longitude} zoom={15} />
              )}
              {tachoCapable && tachoOpen && (
                <TachoOverlay
                  live={live}
                  deviceName={device?.name}
                  onClose={() => showTacho(false)}
                />
              )}
              {!position && (
                <div className={classes.mapEmpty}>
                  <Typography variant="body2" color="textSecondary">
                    {t('sharedNoData')}
                  </Typography>
                </div>
              )}
            </div>
          )}
          {tab === 2 && (
            <>
              {reviewUrl && (
                <Box sx={{ px: 2, pt: 2 }}>
                  <Box sx={{ bgcolor: '#000', borderRadius: 2, overflow: 'hidden' }}>
                    <video
                      ref={reviewRef}
                      src={reviewUrl}
                      // Muted because that is the price of starting on its own: a browser
                      // refuses to autoplay anything with sound, which is why Preview used
                      // to open the player and then sit waiting for the play arrow. The
                      // controls still carry an unmute, so the audio is a click away rather
                      // than gone.
                      autoPlay
                      muted
                      playsInline
                      style={{
                        width: '100%',
                        maxHeight: 360,
                        display: 'block',
                        background: '#000',
                      }}
                      onLoadedMetadata={(e) => {
                        e.currentTarget.playbackRate = reviewRate;
                        // Some builds ignore the attribute when the source is swapped in
                        // after mount; asking directly covers that. A refusal here is not
                        // an error - it just means the user presses play, as before.
                        e.currentTarget.play?.().catch(() => {});
                        // A clip still arriving reports Infinity; the slider
                        // then follows what has been received so far.
                        const d = e.currentTarget.duration;
                        setReviewLength(Number.isFinite(d) ? d : 0);
                      }}
                      onDurationChange={(e) => {
                        const d = e.currentTarget.duration;
                        if (Number.isFinite(d)) setReviewLength(d);
                      }}
                      onTimeUpdate={(e) => setReviewAt(e.currentTarget.currentTime)}
                      onPlay={() => setReviewRunning(true)}
                      onPause={() => setReviewRunning(false)}
                      onWaiting={() => setReviewWaiting(true)}
                      onPlaying={() => setReviewWaiting(false)}
                      onError={() => {
                        // No ffmpeg on the server means the clip comes back as
                        // FLV, which no browser will play. Fall back to the
                        // relay stream so the footage is still watchable -
                        // without the seeking and speed this player adds.
                        setReviewUrl('');
                        setError(
                          'This clip cannot be scrubbed on this server; ' +
                            'playing it at normal speed instead.',
                        );
                        cancelledRef.current = false;
                        playRecording({
                          startTime: trimStart.format('YYYY-MM-DD HH:mm:ss'),
                          endTime: trimEnd.format('YYYY-MM-DD HH:mm:ss'),
                        });
                      }}
                    />
                  </Box>
                  <Box
                    sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, flexWrap: 'wrap' }}
                  >
                    <IconButton
                      size="small"
                      onClick={() => {
                        const v = reviewRef.current;
                        if (!v) return;
                        if (v.paused) v.play();
                        else v.pause();
                      }}
                    >
                      {reviewRunning ? <PauseIcon /> : <PlayArrowIcon />}
                    </IconButton>
                    <Typography
                      variant="caption"
                      sx={{ fontVariantNumeric: 'tabular-nums', minWidth: 92 }}
                    >
                      {`${clockOf(reviewAt)} / ${reviewLength ? clockOf(reviewLength) : '—'}`}
                    </Typography>
                    <Slider
                      size="small"
                      min={0}
                      max={reviewLength || Math.max(reviewAt, 1)}
                      step={0.1}
                      value={Math.min(reviewAt, reviewLength || reviewAt)}
                      onChange={(_e, value) => {
                        const v = reviewRef.current;
                        if (v) v.currentTime = value;
                        setReviewAt(value);
                      }}
                      sx={{ flex: '1 1 200px', mx: 1 }}
                      disabled={!reviewLength}
                    />
                    {/* Fast forward is the browser's own playback rate, so it
                        works on whatever has been received without asking the
                        vehicle for anything. */}
                    {REVIEW_RATES.map((rate) => (
                      <Button
                        key={rate}
                        size="small"
                        variant={reviewRate === rate ? 'contained' : 'outlined'}
                        onClick={() => setRate(rate)}
                        sx={{ minWidth: 44, px: 0.5 }}
                      >
                        {`${rate}×`}
                      </Button>
                    ))}
                    {reviewWaiting && <CircularProgress size={16} />}
                    <Button
                      size="small"
                      color="inherit"
                      startIcon={<StopIcon />}
                      onClick={() => {
                        setReviewUrl('');
                        setReviewRunning(false);
                      }}
                    >
                      Close
                    </Button>
                  </Box>
                  <Typography variant="caption" color="textSecondary">
                    The clip plays back off the camera&apos;s card in real time, so a long one fills
                    in as it arrives — you can scrub and speed through whatever has already come
                    down.
                  </Typography>
                </Box>
              )}
              {!reviewUrl && (playing || liveError) && (
                <Box sx={{ px: 2, pt: 2 }}>
                  <Box
                    sx={{
                      position: 'relative',
                      width: '100%',
                      height: 320,
                      background: '#000',
                      borderRadius: 2,
                      overflow: 'hidden',
                    }}
                  >
                    {!liveError && <div ref={videoRef} style={{ width: '100%', height: '100%' }} />}
                    {!liveError && !playbackActive && (
                      <Box
                        sx={{
                          position: 'absolute',
                          inset: 0,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: 1,
                          color: '#fff',
                        }}
                      >
                        <CircularProgress size={28} color="inherit" />
                        <Typography variant="body2">Starting playback…</Typography>
                      </Box>
                    )}
                    {liveError && (
                      <Box
                        sx={{
                          position: 'absolute',
                          inset: 0,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: 0.5,
                          color: '#fff',
                          textAlign: 'center',
                          px: 2,
                        }}
                      >
                        <Typography variant="subtitle2">Playback unavailable</Typography>
                        <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.7)' }}>
                          The vehicle may not be streaming right now. Try again in a moment.
                        </Typography>
                      </Box>
                    )}
                  </Box>
                </Box>
              )}
              <Box sx={{ px: 2, pt: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
                  <TextField
                    size="small"
                    type="date"
                    label="Date"
                    value={timelineDate.format('YYYY-MM-DD')}
                    onChange={(e) => setTimelineDate(dayjs(e.target.value))}
                    InputLabelProps={{ shrink: true }}
                  />
                  <Button
                    variant="outlined"
                    startIcon={<SearchIcon />}
                    onClick={loadTimeline}
                    disabled={loadingTimeline || !config}
                  >
                    Load timeline
                  </Button>
                  {loadingTimeline && <CircularProgress size={18} />}
                  <Typography variant="caption" color="textSecondary">
                    Channel {channel + 1} · {segments.length} segment
                    {segments.length === 1 ? '' : 's'}
                  </Typography>
                </Box>
                <Box
                  sx={{
                    position: 'relative',
                    height: 44,
                    borderRadius: 1,
                    bgcolor: 'action.hover',
                    overflow: 'hidden',
                    border: '1px solid',
                    borderColor: 'divider',
                  }}
                >
                  {segments.map((seg, i) => {
                    const start = parseCnmsFileTime(seg.startTime);
                    const end = parseCnmsFileTime(seg.endTime);
                    if (!start || !end) return null;
                    const dayStart = timelineDate.startOf('day');
                    const leftPct = Math.min(
                      100,
                      Math.max(0, (start.diff(dayStart, 'second') / 86400) * 100),
                    );
                    const widthPct = Math.max(0.3, (end.diff(start, 'second') / 86400) * 100);
                    const alarm = Boolean(seg.alarmFlagUInt64) && seg.alarmFlagUInt64 !== '0';
                    return (
                      <Box
                        key={i}
                        title={`${start.format('HH:mm:ss')} - ${end.format('HH:mm:ss')}${alarm ? ' (alarm)' : ''}`}
                        onClick={() => {
                          setTrimStart(start);
                          setTrimEnd(end);
                        }}
                        sx={{
                          position: 'absolute',
                          top: 4,
                          bottom: 4,
                          left: `${leftPct}%`,
                          width: `${widthPct}%`,
                          minWidth: '2px',
                          bgcolor: alarm ? 'error.main' : 'primary.main',
                          borderRadius: 0.5,
                          cursor: 'pointer',
                          '&:hover': { opacity: 0.75 },
                        }}
                      />
                    );
                  })}
                </Box>
                <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                  {['00:00', '06:00', '12:00', '18:00', '24:00'].map((h) => (
                    <Typography key={h} variant="caption" color="textSecondary">
                      {h}
                    </Typography>
                  ))}
                </Box>
                <Typography variant="caption" color="textSecondary">
                  Select a segment to set the range, then press Preview to watch it or Download for
                  the exact clip. The list below grabs whole segments. The camera plays footage back
                  in real time over the vehicle&apos;s mobile data — about a minute and 22 MB per
                  minute of footage — so a clip takes as long as it lasts the first time. After that
                  it is kept here, and watching or downloading it again is instant and free.
                </Typography>
                {clipJob && (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <CircularProgress size={16} />
                      <Typography variant="caption">
                        {`Fetching ${clockOf(clipJob.seconds)} of footage from the vehicle`}
                        {clipJob.elapsedSeconds > 0 &&
                          ` — ${clockOf(Math.min(clipJob.elapsedSeconds, clipJob.seconds))} of ${clockOf(
                            clipJob.seconds,
                          )}`}
                        {clipJob.bytes > 0 && ` · ${formatMb(clipJob.bytes)}`}
                        {clipJob.share && ' · a shareable copy will be made from it'}
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant={clipJob.seconds ? 'determinate' : 'indeterminate'}
                      value={
                        clipJob.seconds
                          ? Math.min(100, ((clipJob.elapsedSeconds || 0) / clipJob.seconds) * 100)
                          : 0
                      }
                    />
                  </Box>
                )}
              </Box>
              {trimStart && trimEnd && (
                <Box sx={{ px: 2, pb: 1.5, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <Typography variant="subtitle2">Trim &amp; download</Typography>
                  <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
                    <TextField
                      size="small"
                      type="datetime-local"
                      label="Start"
                      value={trimStart.format('YYYY-MM-DDTHH:mm:ss')}
                      onChange={(e) => setTrimStart(dayjs(e.target.value))}
                      InputLabelProps={{ shrink: true }}
                      inputProps={{ step: 1 }}
                    />
                    <TextField
                      size="small"
                      type="datetime-local"
                      label="End"
                      value={trimEnd.format('YYYY-MM-DDTHH:mm:ss')}
                      onChange={(e) => setTrimEnd(dayjs(e.target.value))}
                      InputLabelProps={{ shrink: true }}
                      inputProps={{ step: 1 }}
                    />
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<PlayArrowIcon />}
                      disabled={Boolean(clipJob)}
                      onClick={() =>
                        reviewClip(
                          trimStart.format('YYYY-MM-DD HH:mm:ss'),
                          trimEnd.format('YYYY-MM-DD HH:mm:ss'),
                        )
                      }
                    >
                      Preview
                    </Button>
                    {playing && (
                      <Button
                        size="small"
                        variant="outlined"
                        color="inherit"
                        startIcon={<StopIcon />}
                        onClick={() => {
                          cancelledRef.current = true;
                          stopPlayback();
                          setPlaybackActive(false);
                          setLiveError(false);
                        }}
                      >
                        Stop
                      </Button>
                    )}
                    <Button
                      size="small"
                      variant="contained"
                      startIcon={<DownloadIcon />}
                      disabled={Boolean(clipJob)}
                      onClick={() =>
                        downloadSegment(
                          trimStart.format('YYYY-MM-DD HH:mm:ss'),
                          trimEnd.format('YYYY-MM-DD HH:mm:ss'),
                        )
                      }
                    >
                      Download clip
                    </Button>
                  </Box>
                </Box>
              )}
              <List dense className={classes.list}>
                {segments.length === 0 && !loadingTimeline && (
                  <ListItem>
                    <ListItemText primary={t('sharedNoData')} />
                  </ListItem>
                )}
                {segments.map((seg, i) => {
                  const start = parseCnmsFileTime(seg.startTime);
                  const end = parseCnmsFileTime(seg.endTime);
                  if (!start || !end) return null;
                  const startStr = start.format('YYYY-MM-DD HH:mm:ss');
                  const endStr = end.format('YYYY-MM-DD HH:mm:ss');
                  const alarm = Boolean(seg.alarmFlagUInt64) && seg.alarmFlagUInt64 !== '0';
                  return (
                    <ListItem
                      key={`${i}`}
                      disablePadding
                      secondaryAction={
                        <IconButton
                          edge="end"
                          color="primary"
                          title="Download this clip"
                          disabled={Boolean(clipJob)}
                          onClick={() => downloadSegment(startStr, endStr)}
                        >
                          <DownloadIcon />
                        </IconButton>
                      }
                    >
                      <ListItemButton
                        onClick={() => {
                          setTrimStart(start);
                          setTrimEnd(end);
                        }}
                      >
                        <ListItemText
                          primary={`${start.format('HH:mm:ss')} - ${end.format('HH:mm:ss')}`}
                          secondary={alarm ? 'Alarm' : undefined}
                        />
                      </ListItemButton>
                    </ListItem>
                  );
                })}
              </List>
            </>
          )}
        </>
      )}
    </div>
  );
};

export default Cmsv9VideoPage;
