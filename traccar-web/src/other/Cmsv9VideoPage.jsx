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
  Fab,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import { useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import StopIcon from '@mui/icons-material/Stop';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import CloseFullscreenIcon from '@mui/icons-material/CloseFullscreen';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import CloseIcon from '@mui/icons-material/Close';
import VideocamIcon from '@mui/icons-material/Videocam';
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
  cmsv9Activity,
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
  // --- Download tab: the camera app's own shape, in this app's colours. ---
  dlPlayer: {
    position: 'relative',
    width: '100%',
    aspectRatio: '16 / 10',
    maxHeight: 320,
    backgroundColor: '#000',
    flexShrink: 0,
  },
  dlVideo: {
    width: '100%',
    height: '100%',
    display: 'block',
    objectFit: 'contain',
    backgroundColor: '#000',
  },
  dlOverlayBtn: {
    position: 'absolute',
    color: '#fff',
    backgroundColor: 'rgba(0,0,0,0.35)',
    '&:hover': { backgroundColor: 'rgba(0,0,0,0.55)' },
    '&.Mui-disabled': { color: 'rgba(255,255,255,0.4)' },
  },
  dlTopLeft: { top: 8, left: 8 },
  dlTopRight: { top: 8, right: 8 },
  dlTitle: {
    position: 'absolute',
    top: 14,
    left: 52,
    right: 52,
    color: '#fff',
    fontSize: '0.78rem',
    textAlign: 'center',
    textShadow: '0 1px 3px rgba(0,0,0,0.9)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    pointerEvents: 'none',
  },
  dlHint: {
    position: 'absolute',
    inset: 0,
    display: 'grid',
    placeItems: 'center',
    color: 'rgba(255,255,255,0.65)',
    fontSize: '0.85rem',
    textAlign: 'center',
    padding: theme.spacing(0, 3),
    pointerEvents: 'none',
  },
  dlBusy: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: theme.spacing(1),
    pointerEvents: 'none',
  },
  dlControls: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.5),
    padding: theme.spacing(0.5, 1),
    background: 'linear-gradient(transparent, rgba(0,0,0,0.65))',
  },
  dlClock: {
    color: '#fff',
    fontSize: '0.72rem',
    fontVariantNumeric: 'tabular-nums',
    minWidth: 46,
    textAlign: 'center',
  },
  dlChannelTabs: {
    minHeight: 40,
    borderBottom: `1px solid ${theme.palette.divider}`,
    flexShrink: 0,
    '& .MuiTab-root': { minHeight: 40, minWidth: 56, fontSize: '0.8rem' },
  },
  dlRuler: {
    padding: theme.spacing(0.75, 2, 0.5),
    flexShrink: 0,
  },
  dlRulerDate: {
    fontSize: '0.72rem',
    fontWeight: 600,
    color: theme.palette.text.secondary,
    marginBottom: 4,
  },
  dlRulerTrack: {
    position: 'relative',
    height: 22,
    borderRadius: 4,
    backgroundColor: theme.palette.action.hover,
    overflow: 'hidden',
  },
  dlRulerBar: {
    position: 'absolute',
    top: 4,
    bottom: 4,
    minWidth: 2,
    borderRadius: 2,
    backgroundColor: theme.palette.success.main,
    cursor: 'pointer',
  },
  dlRulerBarOn: {
    backgroundColor: theme.palette.primary.main,
    top: 1,
    bottom: 1,
  },
  dlRulerTick: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: theme.palette.divider,
  },
  dlRulerLabels: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: 2,
  },
  dlRulerLabel: {
    fontSize: '0.62rem',
    color: theme.palette.text.secondary,
    fontVariantNumeric: 'tabular-nums',
  },
  dlList: {
    flex: 1,
    minHeight: 0,
    overflowY: 'auto',
    paddingBottom: theme.spacing(9),
  },
  dlRowOn: {
    backgroundColor: theme.palette.action.selected,
  },
  dlThumb: {
    width: 56,
    height: 42,
    flexShrink: 0,
    marginRight: theme.spacing(1.5),
    borderRadius: 6,
    backgroundColor: theme.palette.action.hover,
    color: theme.palette.text.secondary,
    display: 'grid',
    placeItems: 'center',
  },
  dlRowTop: {
    display: 'flex',
    alignItems: 'baseline',
    gap: theme.spacing(1),
    fontSize: '0.86rem',
    fontWeight: 500,
    flexWrap: 'wrap',
  },
  dlRowTime: {
    fontVariantNumeric: 'tabular-nums',
    color: theme.palette.text.secondary,
  },
  dlGet: {
    color: theme.palette.primary.contrastText,
    backgroundColor: theme.palette.primary.main,
    '&:hover': { backgroundColor: theme.palette.primary.dark },
    '&.Mui-disabled': { backgroundColor: theme.palette.action.disabledBackground },
  },
  dlFind: {
    position: 'absolute',
    right: 16,
    bottom: 16,
    zIndex: 3,
  },
  // Fixed rather than only the Fullscreen API: the API is refused often
  // enough on phones that it cannot be what this depends on.
  dlPlayerFull: {
    position: 'fixed',
    inset: 0,
    width: '100vw',
    height: '100vh',
    // eslint-disable-next-line no-dupe-keys
    height: '100dvh',
    maxHeight: 'none',
    aspectRatio: 'auto',
    zIndex: theme.zIndex.modal + 2,
  },
  dlStreams: {
    position: 'absolute',
    inset: 0,
    display: 'grid',
    gap: 2,
    backgroundColor: '#000',
  },
  dlStreamCell: {
    position: 'relative',
    minWidth: 0,
    minHeight: 0,
    backgroundColor: '#0a0a0a',
    overflow: 'hidden',
  },
  dlStreamLabel: {
    position: 'absolute',
    top: 4,
    left: 6,
    color: '#fff',
    fontSize: '0.65rem',
    fontWeight: 700,
    textShadow: '0 1px 3px rgba(0,0,0,0.9)',
    pointerEvents: 'none',
  },
  dlStreamState: {
    position: 'absolute',
    inset: 0,
    display: 'grid',
    placeItems: 'center',
    color: 'rgba(255,255,255,0.6)',
    fontSize: '0.72rem',
    pointerEvents: 'none',
  },
  dlPickRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: theme.spacing(0.75),
    marginTop: theme.spacing(0.75),
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

/*
 * What a download is actually doing, in words.
 *
 * There are two quite different waits and they used to look the same. First
 * the camera has to be told to play the footage back and start pushing it,
 * which can take the best part of a minute on a vehicle with poor signal and
 * sends nothing at all; then the footage arrives, in real time. Counting the
 * clock against the clip's length from the moment the button was pressed made
 * a fifteen-second clip read "0:15 of 0:15" while nothing had happened yet,
 * which looks exactly like a finished download that has hung.
 */
const downloadProgress = (job) => {
  const waiting = clockOf(job.elapsedSeconds || 0);
  // Nothing has arrived yet: no percentage, because none of this is footage.
  if (!job.started) {
    return { percent: null, label: '—', text: `Waiting for the camera to start — ${waiting}` };
  }
  const seconds = job.seconds || 0;
  const fetched = job.fetchingSeconds || 0;
  // Held at 99 until the file is actually there: the last of it is the camera
  // closing the stream and the server writing the index, and a bar that sits
  // at 100% with nothing to show for it reads as stuck.
  const percent = seconds ? Math.min(99, Math.floor((fetched / seconds) * 100)) : null;
  return {
    percent,
    label: percent === null ? '—' : `${percent}%`,
    text: `${percent === null ? '' : `${percent}% · `}${formatMb(job.bytes)} fetched`
      + (seconds && fetched > seconds + 30 ? ' · the vehicle is slow' : ''),
  };
};

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
    // Muted unless asked otherwise: a tile restarted while its speaker is on
    // comes back with sound from the first frame rather than waiting for an
    // unmute that may land before its audio pipeline exists.
    isNotMute: options.isNotMute === true,
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
// on resumes the audio context (suspended by the browser until the page has
// had a tap), lifts the mute and sets the volume outright - cancelMute alone
// only restores a stored "last volume", which a stream that has never been
// unmuted does not have. While muted the player throws decoded audio away
// rather than buffering it, so sound starts from the next frame, not from a
// backlog.
function setPlayerAudio(player, on) {
  if (!player) return;
  try {
    if (on) {
      player.audioResume?.();
      player.cancelMute?.();
      player.setVolume?.(1);
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
  // Clips start muted because that is the price of playing on their own; the
  // speaker in the controls is how the cab audio gets turned on.
  const [reviewMuted, setReviewMuted] = useState(true);
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
  // Download tab, laid out the way the camera maker's own app lays it out:
  // a player, a channel strip, the day's ruler and the recordings as a list.
  // -1 is the "All" tab, which asks every channel and merges the answers.
  const [dlChannel, setDlChannel] = useState(-1);
  const [dlBegin, setDlBegin] = useState('00:00');
  const [dlEnd, setDlEnd] = useState('23:59');
  const [dlSegments, setDlSegments] = useState([]);
  const [dlSelected, setDlSelected] = useState(null);
  const [dlTitle, setDlTitle] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  // Watching a recording plays it off the camera as a stream; a clip that has
  // been downloaded plays from the file. Both use the same box, one at a time.
  const [dlStreaming, setDlStreaming] = useState(false);
  // Playing a recording back: one player per channel, each in its own box,
  // because Jessibuca will not build a second player in a container it has
  // already used. On the All tab every camera plays at once.
  const dlCellsRef = useRef({});
  const dlPlayersRef = useRef({});
  const [dlPlaying, setDlPlaying] = useState({});
  // The whole player area fills the screen, not one camera in it: on the All
  // tab what you want bigger is the wall of cameras. Done with fixed
  // positioning as well as the Fullscreen API, because iOS Safari refuses the
  // API on an arbitrary element and a WebView often does too.
  const dlPlayerRef = useRef(null);
  const [dlFullscreen, setDlFullscreen] = useState(false);
  // What happened to the last download, so a finished one says so rather than
  // the progress simply disappearing and leaving you to guess.
  const [dlDone, setDlDone] = useState(null);
  // The part of a recording to fetch: opens on the segment's own span and
  // will not go outside it, because the camera has nothing else to give.
  const [segDialog, setSegDialog] = useState(null);
  // Fetching a clip off a vehicle: what we are fetching, and how far it has got.
  const [clipJob, setClipJob] = useState(null);
  // Footage being pulled off this vehicle - by this page or by somebody else
  // entirely. The camera has one uplink and playback cannot share it with live
  // channels, so live is paused for the duration; every page showing this
  // vehicle asks the server about it rather than being left with tiles that
  // stopped for no visible reason.
  const [downloading, setDownloading] = useState(null);
  const clipJobRef = useRef(null);

  const channels = useMemo(() => {
    const n = config?.channels || Number(defaultChannels) || 4;
    return Array.from({ length: Math.min(Math.max(Number(n), 1), 16) }, (_, i) => i);
  }, [config, defaultChannels]);

  // Which boxes the Download tab's player area shows: every camera on the All
  // tab, otherwise just the one. Declared here, after `channels` exists - a
  // useMemo runs while the component renders, so reading it any earlier is
  // reading a const that has not been initialised yet.
  const dlPlayChannels = useMemo(
    () => (dlChannel < 0 ? channels : [dlChannel]),
    [dlChannel, channels],
  );

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
      if (data.errCode === -3) {
        setDownloading(data.downloading ? { downloading: true, ...data.downloading } : { downloading: true });
        throw new Error(data.message || 'Footage is downloading from this vehicle.');
      }
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

  /*
   * Watch for footage being pulled off this vehicle, and give the uplink to it.
   *
   * The page that asked for the clip knows what it is waiting for; this is for
   * the vehicle's other watchers - another phone, another tab, the operator who
   * opened the cameras while a download was already running. The tiles come
   * down while it runs and start again by themselves when the vehicle is free,
   * which is what somebody who never asked for the download would expect.
   */
  const resumeAfterRef = useRef(false);
  const gridActiveRef = useRef(gridActive);
  gridActiveRef.current = gridActive;
  useEffect(() => {
    if (!cmsv9DeviceId) return undefined;
    let stopped = false;
    const check = async () => {
      try {
        const state = await cmsv9Activity(deviceId);
        if (stopped) return;
        // A cancel just asked for: let it land before believing the server.
        const justCancelled = Date.now() - cancelAtRef.current < 10000;
        setDownloading(state.downloading && !justCancelled ? state : null);
        if (state.downloading) {
          if (gridActiveRef.current) {
            resumeAfterRef.current = true;
            stopGridRef.current();
          }
        } else if (resumeAfterRef.current) {
          resumeAfterRef.current = false;
          startGrid();
        }
      } catch (e) {
        // the server is unreachable for a moment; the tiles say so themselves
      }
    };
    check();
    const timer = setInterval(check, 5000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [cmsv9DeviceId, deviceId, startGrid]);

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
        // The vehicle is sending footage and the server has refused live for
        // the duration. Not an error to retry: the watcher above brings the
        // tiles back when the download is done.
        if (data.errCode === -3) {
          setDownloading(data.downloading ? { downloading: true, ...data.downloading } : { downloading: true });
          resumeAfterRef.current = true;
          stopGridRef.current();
          return;
        }
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
          isNotMute: audioChannelRef.current === ch,
        });
        if (!player) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
          return;
        }
        // The audio pipeline is only built once the stream's first audio
        // frame has been seen, so an unmute before that is lost; say it
        // again when it arrives. (A tile whose speaker was turned on before
        // its audio existed is exactly the "has audio enabled, hears
        // nothing" case.)
        if (audioChannelRef.current === ch) setPlayerAudio(player, true);
        player.on('audioInfo', () => {
          if (audioChannelRef.current === ch) setPlayerAudio(player, true);
        });
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

  /*
   * The day's recordings for the Download tab.
   *
   * The camera answers one channel at a time and its answer does not say which
   * channel it came from, so "All" asks each one and tags the rows itself.
   * Queried in parallel: these are index reads off the camera's own card, not
   * footage, so they cost the vehicle almost nothing.
   */
  const loadRecordings = useCatchCallback(async () => {
    const cfg = await ensureConfig();
    if (!cfg) return;
    setLoadingTimeline(true);
    try {
      const day = timelineDate.format('YYYY-MM-DD');
      const from2 = `${day} ${dlBegin}:00`;
      const to2 = `${day} ${dlEnd}:59`;
      const wanted = dlChannel < 0 ? channels : [dlChannel];
      const answers = await Promise.all(
        wanted.map(async (ch) => {
          try {
            const data = await cmsv9History(deviceId, ch, from2, to2);
            return (data?.resultData || []).map((seg) => ({ ...seg, channel: ch }));
          } catch (e) {
            return []; // one camera with nothing to say must not empty the list
          }
        }),
      );
      const rows = answers
        .flat()
        .map((seg) => ({
          ...seg,
          start: parseCnmsFileTime(seg.startTime),
          end: parseCnmsFileTime(seg.endTime),
        }))
        .filter((seg) => seg.start && seg.end)
        // Newest first, and within one minute the lowest channel first, so the
        // same recording across eight cameras reads as one block.
        .sort((a, b) => b.start.valueOf() - a.start.valueOf() || a.channel - b.channel);
      setDlSegments(rows);
      setSegments(rows);
    } finally {
      setLoadingTimeline(false);
    }
  }, [ensureConfig, deviceId, channels, dlChannel, timelineDate, dlBegin, dlEnd]);

  useEffect(() => {
    if (tab === 2 && cmsv9DeviceId) {
      loadRecordings();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, timelineDate, dlChannel, cmsv9DeviceId]);

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
    (startStr, endStr, share, ch = channel) =>
      `/api/cmsv9/download/${deviceId}/${ch}` +
      `?startTime=${encodeURIComponent(startStr)}` +
      `&endTime=${encodeURIComponent(endStr)}` +
      (share ? '&format=share&disposition=attachment' : ''),
    [deviceId, channel],
  );

  const fetchClip = useCallback(
    async (startStr, endStr, share, label, ch = channel) => {
      const query =
        `?startTime=${encodeURIComponent(startStr)}` +
        `&endTime=${encodeURIComponent(endStr)}` +
        (share ? '&format=share' : '');
      const base = `/api/cmsv9/clip/${deviceId}/${ch}${query}`;
      const token = {};
      clipJobRef.current = token;
      cancelledClipRef.current = false;
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
        setClipJob({ label, share, startStr, endStr, ch, ...state });
        // Nothing to wait for when the server already has it.
        while (!state.ready) {
          await new Promise((resolve) => {
            setTimeout(resolve, 2000);
          });
          if (clipJobRef.current !== token) return null;
          const poll = await fetch(base);
          if (!poll.ok) throw new Error('Lost contact with the server while fetching the clip.');
          state = await poll.json();
          setClipJob({ label, share, startStr, endStr, ch, ...state });
          if (!state.ready && !state.working) {
            // Cancelled on purpose reads as "gone" from here too, so say
            // nothing alarming when that is what happened.
            throw new Error(cancelledClipRef.current
              ? 'Download cancelled'
              : 'The camera stopped sending that footage. It may be offline.');
          }
        }
        setClipJob(null);
        return clipUrl(startStr, endStr, share, ch);
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
  /*
   * Stop a download part way.
   *
   * Both ends have to know: the server kills the ffmpeg and tells the camera
   * to stop playing (which is where the vehicle's data is actually saved), and
   * the page stops following the job so the next poll does not report it as
   * having died on its own.
   */
  const cancelledClipRef = useRef(false);
  // The server is asked to stop, then has to notice; its activity poll would
  // otherwise keep saying "downloading" for a few seconds and the banner
  // would sit there as if the Cancel had done nothing. Ignore what it says
  // for a moment, and show that the cancel was taken.
  const cancelAtRef = useRef(0);
  const [cancelling, setCancelling] = useState(false);
  const cancelClip = useCallback(async () => {
    // Whatever this page knows about, or failing that whatever the server
    // says the vehicle is busy with: a download nobody can stop is worse than
    // one somebody stops by mistake, and a stopped one can simply be asked
    // for again.
    const job = clipJob && clipJob.startStr
      ? { start: clipJob.startStr, end: clipJob.endStr, ch: clipJob.ch ?? channel, share: clipJob.share }
      : (downloading && downloading.startTime
        ? { start: downloading.startTime, end: downloading.endTime, ch: downloading.channel, share: false }
        : null);
    cancelledClipRef.current = true;
    cancelAtRef.current = Date.now();
    clipJobRef.current = null;
    setClipJob(null);
    setDownloading(null);
    setCancelling(true);
    setPlayerMsg('Download cancelled');
    setTimeout(() => setCancelling(false), 6000);
    if (!job) return;
    try {
      const query = `?startTime=${encodeURIComponent(job.start)}&endTime=${encodeURIComponent(job.end)}`;
      // The shareable copy and the pull underneath it are separate jobs; the
      // pull is the one costing the vehicle, so stop both.
      await fetch(`/api/cmsv9/clip/${deviceId}/${job.ch}${query}&format=share`, { method: 'DELETE' });
      await fetch(`/api/cmsv9/clip/${deviceId}/${job.ch}${query}`, { method: 'DELETE' });
    } catch (e) {
      // the server will finish and cache it; nothing is lost, only time
    }
  }, [clipJob, downloading, deviceId, channel]);

  /** Stops every recording this tab is playing and frees its players. */
  const stopDlPlayers = useCallback(() => {
    Object.entries(dlPlayersRef.current).forEach(([ch, player]) => {
      destroyFlvPlayer(player);
      try {
        cmsv9StopLive(deviceId, Number(ch)).catch(() => {});
      } catch (e) {
        // the camera stops on its own at the end of the range anyway
      }
    });
    dlPlayersRef.current = {};
    setDlPlaying({});
  }, [deviceId]);

  /*
   * Watch a recording: the camera plays it back as a stream, exactly as it
   * does live, so there is nothing to wait for but the first frame and nothing
   * is kept. On the All tab every camera plays its own copy of that moment -
   * started a beat apart, because they are all coming up the same uplink.
   */
  const playSegment = useCallback(
    async (startStr, endStr, only) => {
      stopDlPlayers();
      setDlStreaming(true);
      setReviewUrl('');
      setPlayerMsg('');
      const wanted = only === undefined || only === null || only < 0 ? channels : [only];
      setDlPlaying(Object.fromEntries(wanted.map((ch) => [ch, 'starting'])));
      // Several at once means the sub recording: four main-quality streams up
      // one mobile uplink is what made this stutter. One camera on its own
      // gets the full-quality recording.
      const stream = wanted.length > 1 ? 1 : 0;
      wanted.forEach(async (ch, index) => {
        if (index) {
          await new Promise((resolve) => { setTimeout(resolve, index * 400); });
        }
        try {
          const data = await cmsv9StartPlayback(deviceId, ch, startStr, endStr, stream);
          if (data.errCode !== 0 && data.errCode !== -1) throw new Error(data.resultMsg || 'no playback');
          const { flvUrl } = data;
          if (!flvUrl) throw new Error('no playback url');
          const found = await waitForStream(flvUrl, 60000);
          const container = dlCellsRef.current[ch];
          if (!found || !container) {
            setDlPlaying((prev) => ({ ...prev, [ch]: 'failed' }));
            return;
          }
          destroyFlvPlayer(dlPlayersRef.current[ch]);
          // A recording is not live: nobody cares whether it is 200ms or two
          // seconds behind, and a buffer that size is the difference between
          // smooth footage and the stutter a vehicle's connection produces.
          const player = await createFlvPlayer(container, flvUrl, {
            isResize: true,
            videoBuffer: 1.5,
            heartTimeout: 20,
          });
          dlPlayersRef.current[ch] = player;
          player.on('videoInfo', () => setDlPlaying((prev) => ({ ...prev, [ch]: 'playing' })));
          player.on('error', () => setDlPlaying((prev) => ({ ...prev, [ch]: 'failed' })));
        } catch (e) {
          setDlPlaying((prev) => ({ ...prev, [ch]: 'failed' }));
        }
      });
    },
    [channels, deviceId, stopDlPlayers],
  );

  /* Jessibuca draws to a canvas sized when it was built, so every player has
   * to be told the box changed shape or they keep the old picture size. */
  const remeasureDl = useCallback(() => {
    requestAnimationFrame(() => {
      Object.values(dlPlayersRef.current).forEach((player) => {
        try {
          player?.resize?.();
        } catch (e) {
          // an older build redraws on its own next frame
        }
      });
    });
  }, []);

  const toggleDlFullscreen = useCallback(() => {
    setDlFullscreen((was) => {
      const next = !was;
      const el = dlPlayerRef.current;
      try {
        if (next) {
          el?.requestFullscreen?.({ navigationUI: 'hide' })
            .then(() => window.screen?.orientation?.lock?.('landscape'))
            .catch(() => {})
            .finally(remeasureDl);
        } else {
          if (document.fullscreenElement) document.exitFullscreen?.();
          window.screen?.orientation?.unlock?.();
        }
      } catch (e) {
        // refused: the CSS layer is what actually makes this work
      }
      remeasureDl();
      return next;
    });
  }, [remeasureDl]);

  // Escape, the Android back button (which closes native fullscreen without
  // telling React) and a turn of the phone all have to be followed.
  useEffect(() => {
    if (!dlFullscreen) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setDlFullscreen(false); };
    const onChange = () => { if (!document.fullscreenElement) setDlFullscreen(false); };
    window.addEventListener('keydown', onKey);
    document.addEventListener('fullscreenchange', onChange);
    window.addEventListener('resize', remeasureDl);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('fullscreenchange', onChange);
      window.removeEventListener('resize', remeasureDl);
    };
  }, [dlFullscreen, remeasureDl]);

  // Leaving the tab, or the page, must not leave a camera playing to itself.
  const stopDlRef = useRef(stopDlPlayers);
  stopDlRef.current = stopDlPlayers;
  useEffect(() => {
    if (tab !== 2) stopDlRef.current();
  }, [tab]);
  useEffect(() => () => stopDlRef.current(), []);

  const downloadSegment = useCallback(
    async (startStr, endStr, ch) => {
      // The clip's own player takes the box back from the camera streams.
      stopDlPlayers();
      setDlStreaming(false);
      stopPlayback();
      const url = await fetchClip(startStr, endStr, true, 'Download', ch);
      if (!url) return false;
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
      return true;
    },
    [fetchClip, stopPlayback, stopDlPlayers],
  );

  /*
   * The same moment from several cameras.
   *
   * One after another, not all at once: the vehicle plays footage back in real
   * time over one uplink, and asking for four channels together would leave
   * all four fighting and none of them finishing. The title above the player
   * says which one is coming now.
   */
  const downloadSegments = useCallback(
    async (startStr, endStr, picked) => {
      const list = picked && picked.length ? picked : [channel];
      setDlDone(null);
      const done = [];
      for (let i = 0; i < list.length; i += 1) {
        const ch = list[i];
        setDlTitle(
          `${device?.name || ''} CH${ch + 1} ${startStr} - ${endStr.slice(11)}`
            + (list.length > 1 ? `  (${i + 1} of ${list.length})` : ''),
        );
        // Deliberately sequential - see above.
        // eslint-disable-next-line no-await-in-loop
        if (await downloadSegment(startStr, endStr, ch)) done.push(ch);
        if (cancelledClipRef.current) break;
      }
      // Say what happened. A download that simply stops showing progress
      // leaves somebody wondering whether it worked.
      const span = `${startStr.slice(11)} - ${endStr.slice(11)}`;
      if (cancelledClipRef.current) {
        setDlDone(null);
      } else if (done.length === list.length) {
        setDlDone({
          ok: true,
          text: list.length === 1
            ? `Download finished — CH${done[0] + 1}, ${span}`
            : `${done.length} downloads finished — ${done.map((c) => `CH${c + 1}`).join(', ')}, ${span}`,
        });
      } else if (done.length) {
        setDlDone({
          ok: false,
          text: `${done.length} of ${list.length} downloaded — ${done.map((c) => `CH${c + 1}`).join(', ')}.`
            + ' The rest did not come off the vehicle; try them again.',
        });
      } else {
        setDlDone({ ok: false, text: 'Nothing came off the vehicle. Try again when it has signal.' });
      }
    },
    [channel, device, downloadSegment],
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
          item.channel ?? channel,
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
            {/* The Download tab has its own channel strip under the player,
                which also decides what plays; a second selector up here only
                disagreed with it. */}
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
          {/* Live is paused while the vehicle is sending footage - its uplink
              carries one or the other, not both. Said plainly, with how far
              along the download is, so nobody is left wondering why the
              pictures went. */}
          {/* How the last download ended. Stays until it is dismissed or the
              next one starts - a message that vanishes on its own is one
              somebody looking at their phone a moment later never sees. */}
          {dlDone && !clipJob && !downloading && (
            <Box
              sx={{
                mx: 2,
                mt: 1,
                p: 1.25,
                borderRadius: 2,
                display: 'flex',
                alignItems: 'center',
                gap: 1.25,
                bgcolor: (theme) => alpha(
                  dlDone.ok ? theme.palette.success.main : theme.palette.warning.main, 0.16,
                ),
                color: dlDone.ok ? 'success.dark' : 'warning.dark',
              }}
            >
              {dlDone.ok ? <CheckCircleIcon fontSize="small" /> : <WarningAmberIcon fontSize="small" />}
              <Typography variant="body2" sx={{ flex: 1, minWidth: 0, fontWeight: 600 }}>
                {dlDone.text}
              </Typography>
              <IconButton size="small" color="inherit" aria-label="Dismiss" onClick={() => setDlDone(null)}>
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>
          )}
          {(downloading || clipJob) && (
            <Box
              sx={{
                mx: 2,
                mt: 1,
                p: 1.25,
                borderRadius: 2,
                display: 'flex',
                alignItems: 'center',
                gap: 1.25,
                bgcolor: (theme) => alpha(theme.palette.warning.main, 0.14),
                color: 'warning.dark',
              }}
            >
              {/* The number people watch, big enough to read at a glance and
                  only moving once footage is genuinely arriving. */}
              <Box sx={{ position: 'relative', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                <CircularProgress
                  size={40}
                  thickness={4}
                  variant={downloadProgress(clipJob || downloading).percent === null ? 'indeterminate' : 'determinate'}
                  value={downloadProgress(clipJob || downloading).percent || 0}
                  color="inherit"
                />
                <Typography
                  variant="caption"
                  sx={{ position: 'absolute', fontWeight: 700, fontSize: '0.65rem' }}
                >
                  {downloadProgress(clipJob || downloading).label}
                </Typography>
              </Box>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  Download in progress — live view paused
                </Typography>
                <Typography variant="caption" sx={{ display: 'block' }}>
                  {/* The page's own job knows sooner than the server poll
                      does, so it is believed first. */}
                  {(() => {
                    const job = clipJob || downloading;
                    const bits = [];
                    if (job.channel !== undefined) bits.push(`CH${job.channel + 1}`);
                    bits.push(downloadProgress(job).text);
                    bits.push('the cameras restart on their own when it finishes');
                    return bits.join(' · ');
                  })()}
                </Typography>
              </Box>
              {/* Stoppable from any screen showing this vehicle, not only the
                  one that asked: a download that has lost its page would
                  otherwise hold the cameras until it finished on its own. */}
              <Button
                size="small"
                variant="contained"
                color="error"
                startIcon={<StopIcon />}
                onClick={cancelClip}
                disabled={cancelling}
                sx={{ flexShrink: 0 }}
              >
                {cancelling ? 'Stopping…' : 'Cancel'}
              </Button>
            </Box>
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
                      {downloading && 'Download in progress'}
                      {!downloading && gridErrors[ch] === 'novideo' && `${t('cmsv9NoVideo')} — tap to retry`}
                      {!downloading && gridErrors[ch] === 'stalled' && 'Picture stopped — tap to retry'}
                      {!downloading && gridErrors[ch] === 'error' && `${t('errorConnection')} — tap to retry`}
                      {!downloading && !gridErrors[ch] && t('sharedPlay')}
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
          {/*
            The Download tab, laid out the way the camera maker's own app lays
            it out, because that is the layout the people using this already
            know: the player at the top with its own controls over the picture,
            then the channel strip, then the day's ruler, then the recordings
            as a list with a download button on each row. "Find" opens the
            search sheet. Nothing here stops working while a download is
            running - the list and the player stay, and the download buttons
            say why they are waiting.
          */}
          {tab === 2 && (
            <>
              <Box
                ref={dlPlayerRef}
                className={`${classes.dlPlayer}${dlFullscreen ? ` ${classes.dlPlayerFull}` : ''}`}
              >
                {/* Streaming straight off the camera - what a tap on a row
                    gives you. One box per camera on the All tab, one box on a
                    channel tab. The clip player below takes over once footage
                    has actually been fetched. */}
                <Box
                  className={classes.dlStreams}
                  style={(() => {
                    // Two columns in the page, where the box is wide and
                    // short; closer to square once it has the whole screen,
                    // so eight cameras are not eight slivers.
                    const n = dlPlayChannels.length;
                    const columns = n <= 1 ? 1 : Math.min(n, dlFullscreen ? Math.ceil(Math.sqrt(n)) : 2);
                    return {
                      display: dlStreaming ? 'grid' : 'none',
                      gridTemplateColumns: `repeat(${columns}, 1fr)`,
                      gridTemplateRows: `repeat(${Math.ceil(n / columns) || 1}, 1fr)`,
                    };
                  })()}
                >
                  {dlPlayChannels.map((ch) => (
                    <Box key={ch} className={classes.dlStreamCell}>
                      <div
                        ref={(el) => { dlCellsRef.current[ch] = el; }}
                        className={classes.dlVideo}
                      />
                      <Typography className={classes.dlStreamLabel}>{`CH${ch + 1}`}</Typography>
                      {dlPlaying[ch] !== 'playing' && (
                        <Typography className={classes.dlStreamState}>
                          {dlPlaying[ch] === 'failed' ? 'No footage' : 'Starting…'}
                        </Typography>
                      )}
                    </Box>
                  ))}
                </Box>
                <video
                  ref={reviewRef}
                  src={reviewUrl || undefined}
                  autoPlay
                  muted
                  playsInline
                  className={classes.dlVideo}
                  style={{ display: dlStreaming ? 'none' : 'block' }}
                  onLoadedMetadata={(e) => {
                    e.currentTarget.playbackRate = reviewRate;
                    e.currentTarget.play?.().catch(() => {});
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
                    if (!reviewUrl) return;
                    setReviewUrl('');
                    setPlayerMsg('That clip could not be played here. Download it instead.');
                  }}
                />
                {/* Snapshot and fullscreen sit over the picture, as they do on
                    the camera's own app. */}
                <IconButton
                  size="small"
                  className={`${classes.dlOverlayBtn} ${classes.dlTopLeft}`}
                  disabled={!reviewUrl}
                  title="Save a still from this clip"
                  aria-label="Save a still from this clip"
                  onClick={() => {
                    const v = reviewRef.current;
                    if (!v || !v.videoWidth) return;
                    const canvas = document.createElement('canvas');
                    canvas.width = v.videoWidth;
                    canvas.height = v.videoHeight;
                    canvas.getContext('2d').drawImage(v, 0, 0);
                    const link = document.createElement('a');
                    link.download = `${device?.name || 'clip'}-${dayjs().format('YYYYMMDD-HHmmss')}.png`;
                    link.href = canvas.toDataURL('image/png');
                    link.click();
                  }}
                >
                  <PhotoCameraIcon fontSize="small" />
                </IconButton>
                {dlTitle && <Typography className={classes.dlTitle}>{dlTitle}</Typography>}
                {/* Fills the screen with whatever the box is showing - one
                    camera, or the whole wall of them on the All tab. */}
                <IconButton
                  size="small"
                  className={`${classes.dlOverlayBtn} ${classes.dlTopRight}`}
                  disabled={!reviewUrl && !dlStreaming}
                  title={dlFullscreen ? 'Leave fullscreen' : 'Fullscreen'}
                  aria-label={dlFullscreen ? 'Leave fullscreen' : 'Fullscreen'}
                  onClick={toggleDlFullscreen}
                >
                  {dlFullscreen ? <CloseFullscreenIcon fontSize="small" /> : <OpenInFullIcon fontSize="small" />}
                </IconButton>
                {!reviewUrl && !clipJob && !dlStreaming && (
                  <Typography className={classes.dlHint}>
                    {playerMsg || (dlDone?.ok ? 'Download finished' : 'Tap a recording below to watch it')}
                  </Typography>
                )}
                {(clipJob || reviewWaiting) && (
                  <Box className={classes.dlBusy}>
                    <Box sx={{ position: 'relative', display: 'grid', placeItems: 'center' }}>
                      <CircularProgress
                        size={64}
                        thickness={3}
                        sx={{ color: '#fff' }}
                        variant={!clipJob || downloadProgress(clipJob).percent === null ? 'indeterminate' : 'determinate'}
                        value={clipJob ? downloadProgress(clipJob).percent || 0 : 0}
                      />
                      {clipJob && (
                        <Typography sx={{ position: 'absolute', color: '#fff', fontWeight: 700 }}>
                          {downloadProgress(clipJob).label}
                        </Typography>
                      )}
                    </Box>
                    {clipJob && (
                      <>
                        <Typography variant="caption" sx={{ color: '#fff', textAlign: 'center', px: 2 }}>
                          {downloadProgress(clipJob).text}
                        </Typography>
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<StopIcon />}
                          onClick={cancelClip}
                          disabled={cancelling}
                          sx={{
                            color: '#fff',
                            borderColor: 'rgba(255,255,255,0.6)',
                            pointerEvents: 'auto',
                            mt: 0.5,
                          }}
                        >
                          {cancelling ? 'Stopping…' : 'Cancel download'}
                        </Button>
                      </>
                    )}
                  </Box>
                )}
                <Box className={classes.dlControls}>
                  <IconButton
                    size="small"
                    sx={{ color: '#fff' }}
                    disabled={!reviewUrl}
                    aria-label={reviewRunning ? 'Pause' : 'Play'}
                    onClick={() => {
                      const v = reviewRef.current;
                      if (!v) return;
                      if (v.paused) v.play();
                      else v.pause();
                    }}
                  >
                    {reviewRunning ? <PauseIcon /> : <PlayArrowIcon />}
                  </IconButton>
                  <Typography className={classes.dlClock}>{clockOf(reviewAt)}</Typography>
                  <Slider
                    size="small"
                    min={0}
                    max={reviewLength || Math.max(reviewAt, 1)}
                    step={0.1}
                    value={Math.min(reviewAt, reviewLength || reviewAt)}
                    disabled={!reviewUrl}
                    onChange={(_e, value) => {
                      const v = reviewRef.current;
                      if (v) v.currentTime = value;
                      setReviewAt(value);
                    }}
                    sx={{ flex: 1, color: '#fff', mx: 1 }}
                  />
                  <Typography className={classes.dlClock}>
                    {reviewLength ? clockOf(reviewLength) : '--:--'}
                  </Typography>
                  <IconButton
                    size="small"
                    sx={{ color: '#fff' }}
                    disabled={!reviewUrl}
                    aria-label={reviewMuted ? 'Unmute' : 'Mute'}
                    onClick={() => {
                      const v = reviewRef.current;
                      if (!v) return;
                      v.muted = !v.muted;
                      setReviewMuted(v.muted);
                    }}
                  >
                    {reviewMuted ? <VolumeOffIcon /> : <VolumeUpIcon />}
                  </IconButton>
                </Box>
              </Box>

              {/* Channel strip: All, then one per camera. */}
              <Tabs
                value={dlChannel}
                onChange={(_e, value) => {
                  // Changing what is listed also changes what plays, so the
                  // players come down rather than showing the wrong camera.
                  stopDlPlayers();
                  setDlStreaming(false);
                  setDlChannel(value);
                  setDlSelected(null);
                  setDlTitle('');
                }}
                variant="scrollable"
                scrollButtons={false}
                className={classes.dlChannelTabs}
              >
                <Tab value={-1} label="All" />
                {channels.map((ch) => (
                  <Tab key={ch} value={ch} label={`CH${ch + 1}`} />
                ))}
              </Tabs>

              {/* The day on a ruler, with what the camera recorded marked on
                  it. Tapping a block selects that recording in the list. */}
              <Box className={classes.dlRuler}>
                <Typography className={classes.dlRulerDate}>
                  {timelineDate.format('ddd D MMM')}
                </Typography>
                <Box className={classes.dlRulerTrack}>
                  {dlSegments.map((seg, i) => {
                    const startOfDay = seg.start.startOf('day');
                    const left = (seg.start.diff(startOfDay, 'second') / 86400) * 100;
                    const width = Math.max(0.4, (seg.end.diff(seg.start, 'second') / 86400) * 100);
                    return (
                      <Box
                        key={`bar-${i}`}
                        className={`${classes.dlRulerBar} ${dlSelected === i ? classes.dlRulerBarOn : ''}`}
                        style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
                        onClick={() => setDlSelected(i)}
                        title={`CH${seg.channel + 1} ${seg.start.format('HH:mm:ss')}`}
                      />
                    );
                  })}
                  {[0, 6, 12, 18].map((h) => (
                    <Box key={h} className={classes.dlRulerTick} style={{ left: `${(h / 24) * 100}%` }} />
                  ))}
                </Box>
                <Box className={classes.dlRulerLabels}>
                  {['00:00', '06:00', '12:00', '18:00', '24:00'].map((h) => (
                    <Typography key={h} className={classes.dlRulerLabel}>
                      {h}
                    </Typography>
                  ))}
                </Box>
              </Box>

              {/* The recordings themselves. */}
              <List dense disablePadding className={classes.dlList}>
                {loadingTimeline && (
                  <ListItem>
                    <CircularProgress size={18} sx={{ mr: 1.5 }} />
                    <ListItemText primary="Asking the camera what it has…" />
                  </ListItem>
                )}
                {!loadingTimeline && dlSegments.length === 0 && (
                  <ListItem>
                    <ListItemText
                      primary="No recordings for this day"
                      secondary="Press Find to choose another date, channel or time."
                    />
                  </ListItem>
                )}
                {dlSegments.map((seg, i) => {
                  const startStr = seg.start.format('YYYY-MM-DD HH:mm:ss');
                  const endStr = seg.end.format('YYYY-MM-DD HH:mm:ss');
                  const alarm = Boolean(seg.alarmFlagUInt64) && seg.alarmFlagUInt64 !== '0';
                  return (
                    <ListItem
                      key={`${seg.channel}-${seg.startTime}-${i}`}
                      disablePadding
                      className={dlSelected === i ? classes.dlRowOn : undefined}
                      secondaryAction={
                        <IconButton
                          edge="end"
                          className={classes.dlGet}
                          title={downloading ? 'Waiting for the vehicle to finish sending' : 'Download this recording'}
                          aria-label="Download this recording"
                          disabled={Boolean(clipJob) || Boolean(downloading)}
                          onClick={() =>
                            setSegDialog({
                              channel: seg.channel,
                              picked: [seg.channel],
                              start: seg.start,
                              end: seg.end,
                              min: seg.start,
                              max: seg.end,
                            })
                          }
                        >
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                      }
                    >
                      {/* A tap plays it, nothing more: the camera streams the
                          recording back as it would live, so watching costs
                          the wait for the first frame rather than the whole
                          clip. Keeping it is the button on the right. */}
                      <ListItemButton
                        disabled={Boolean(clipJob) || Boolean(downloading)}
                        onClick={() => {
                          setDlSelected(i);
                          setTrimStart(seg.start);
                          setTrimEnd(seg.end);
                          setPlayerMsg('');
                          setDlTitle(
                            `${device?.name || ''} ${dlChannel < 0 ? 'all cameras' : `CH${seg.channel + 1}`}`
                              + ` ${seg.start.format('YYYY-MM-DD HH:mm:ss')} - ${seg.end.format('HH:mm:ss')}`,
                          );
                          playSegment(startStr, endStr, dlChannel < 0 ? -1 : seg.channel);
                        }}
                      >
                        <Box className={classes.dlThumb}>
                          <VideocamIcon fontSize="small" />
                        </Box>
                        <ListItemText
                          primary={
                            <Box className={classes.dlRowTop}>
                              <span>{seg.start.format('YYYY-MM-DD')}</span>
                              <span className={classes.dlRowTime}>
                                {`${seg.start.format('HH:mm:ss')} - ${seg.end.format('HH:mm:ss')}`}
                              </span>
                            </Box>
                          }
                          secondary={`CH${seg.channel + 1} ${alarm ? 'Alarm' : 'Conventional'}`}
                        />
                      </ListItemButton>
                    </ListItem>
                  );
                })}
              </List>

              {/* Find: the search sheet, as a button that stays put. */}
              <Fab
                color="primary"
                size="medium"
                className={classes.dlFind}
                onClick={() => setSearchOpen(true)}
              >
                <SearchIcon />
              </Fab>

              <Dialog open={searchOpen} onClose={() => setSearchOpen(false)} fullWidth maxWidth="xs">
                <DialogTitle sx={{ textAlign: 'center', fontSize: '1rem' }}>
                  Choose what to look for
                </DialogTitle>
                <DialogContent dividers sx={{ p: 0 }}>
                  <List disablePadding>
                    <ListItem divider>
                      <ListItemText primary="Channel" />
                      <TextField
                        select
                        size="small"
                        variant="standard"
                        value={dlChannel}
                        onChange={(e) => setDlChannel(Number(e.target.value))}
                        sx={{ minWidth: 110 }}
                      >
                        <MenuItem value={-1}>All</MenuItem>
                        {channels.map((ch) => (
                          <MenuItem key={ch} value={ch}>{`CH${ch + 1}`}</MenuItem>
                        ))}
                      </TextField>
                    </ListItem>
                    <ListItem divider>
                      <ListItemText primary="Location" secondary="The camera's own card" />
                      <Typography variant="body2" color="textSecondary">
                        Terminal disk
                      </Typography>
                    </ListItem>
                    <ListItem divider>
                      <ListItemText primary="Video type" />
                      <Typography variant="body2" color="textSecondary">
                        All
                      </Typography>
                    </ListItem>
                    <ListItem divider>
                      <ListItemText primary="Date" />
                      <TextField
                        size="small"
                        type="date"
                        variant="standard"
                        value={timelineDate.format('YYYY-MM-DD')}
                        onChange={(e) => setTimelineDate(dayjs(e.target.value))}
                      />
                    </ListItem>
                    <ListItem divider>
                      <ListItemText primary="From" />
                      <TextField
                        size="small"
                        type="time"
                        variant="standard"
                        value={dlBegin}
                        onChange={(e) => setDlBegin(e.target.value)}
                      />
                    </ListItem>
                    <ListItem>
                      <ListItemText primary="To" />
                      <TextField
                        size="small"
                        type="time"
                        variant="standard"
                        value={dlEnd}
                        onChange={(e) => setDlEnd(e.target.value)}
                      />
                    </ListItem>
                  </List>
                </DialogContent>
                <DialogActions>
                  <Button onClick={() => setSearchOpen(false)}>Cancel</Button>
                  <Button
                    variant="contained"
                    onClick={() => {
                      setSearchOpen(false);
                      setDlSelected(null);
                      loadRecordings();
                    }}
                  >
                    Find
                  </Button>
                </DialogActions>
              </Dialog>

              {/* Part of a recording, rather than all of it: the camera sends
                  footage back in real time, so asking for four minutes instead
                  of ten is four minutes instead of ten. */}
              <Dialog open={Boolean(segDialog)} onClose={() => setSegDialog(null)} fullWidth maxWidth="xs">
                <DialogTitle sx={{ textAlign: 'center', fontSize: '1rem' }}>
                  Download footage
                </DialogTitle>
                {segDialog && (
                  <DialogContent dividers sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <Typography variant="body2" color="textSecondary">
                      {`${segDialog.min.format('HH:mm:ss')} to ${segDialog.max.format('HH:mm:ss')} is on the camera`}
                    </Typography>
                    {/* More than one camera of the same moment, which is what
                        an incident usually needs. They come off the vehicle one
                        after another, not at once - its uplink carries one
                        playback at a time - so the wait adds up. */}
                    <Box>
                      <Typography variant="caption" color="textSecondary">
                        Cameras
                      </Typography>
                      <Box className={classes.dlPickRow}>
                        {channels.map((ch) => {
                          const on = segDialog.picked.includes(ch);
                          return (
                            <Chip
                              key={ch}
                              label={`CH${ch + 1}`}
                              size="small"
                              color={on ? 'primary' : 'default'}
                              variant={on ? 'filled' : 'outlined'}
                              onClick={() =>
                                setSegDialog((d) => ({
                                  ...d,
                                  picked: on
                                    ? d.picked.filter((c) => c !== ch)
                                    : [...d.picked, ch].sort((a, b) => a - b),
                                }))
                              }
                            />
                          );
                        })}
                      </Box>
                    </Box>
                    <TextField
                      label="From"
                      type="datetime-local"
                      size="small"
                      inputProps={{ step: 1 }}
                      value={segDialog.start.format('YYYY-MM-DDTHH:mm:ss')}
                      onChange={(e) =>
                        setSegDialog((d) => ({ ...d, start: dayjs(e.target.value) }))
                      }
                      helperText={`Not before ${segDialog.min.format('HH:mm:ss')}`}
                    />
                    <TextField
                      label="To"
                      type="datetime-local"
                      size="small"
                      inputProps={{ step: 1 }}
                      value={segDialog.end.format('YYYY-MM-DDTHH:mm:ss')}
                      onChange={(e) => setSegDialog((d) => ({ ...d, end: dayjs(e.target.value) }))}
                      helperText={`Not after ${segDialog.max.format('HH:mm:ss')}`}
                    />
                    <Typography variant="caption" color="textSecondary">
                      {`${clockOf(Math.max(0, segDialog.end.diff(segDialog.start, 'second')))} from ${segDialog.picked.length} camera${segDialog.picked.length === 1 ? '' : 's'} — the camera plays footage back in real time, so expect about ${clockOf(Math.max(0, segDialog.end.diff(segDialog.start, 'second')) * Math.max(1, segDialog.picked.length))} and roughly ${formatMb((Math.max(0, segDialog.end.diff(segDialog.start, 'second')) * Math.max(1, segDialog.picked.length)) * 22 * 1024 * 1024 / 60)} of the vehicle's data. Each one is kept here afterwards and is instant to fetch again.`}
                    </Typography>
                  </DialogContent>
                )}
                <DialogActions>
                  <Button onClick={() => setSegDialog(null)}>Cancel</Button>
                  <Button
                    variant="contained"
                    disabled={
                      !segDialog
                      || segDialog.picked.length === 0
                      || segDialog.end.diff(segDialog.start, 'second') <= 0
                      || segDialog.start.isBefore(segDialog.min)
                      || segDialog.end.isAfter(segDialog.max)
                    }
                    onClick={() => {
                      const d = segDialog;
                      setSegDialog(null);
                      downloadSegments(
                        d.start.format('YYYY-MM-DD HH:mm:ss'),
                        d.end.format('YYYY-MM-DD HH:mm:ss'),
                        d.picked,
                      );
                    }}
                  >
                    {segDialog && segDialog.picked.length > 1
                      ? `Download ${segDialog.picked.length} clips`
                      : 'Download'}
                  </Button>
                </DialogActions>
              </Dialog>
            </>
          )}
        </>
      )}
    </div>
  );
};

export default Cmsv9VideoPage;
