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
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import VideocamIcon from '@mui/icons-material/Videocam';
import SearchIcon from '@mui/icons-material/Search';
import DownloadIcon from '@mui/icons-material/Download';
import GridViewIcon from '@mui/icons-material/GridView';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import BackIcon from '../common/components/BackIcon';
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
  },
  cellVideo: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
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
    flex: '1 1 62%',
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
  return dayjs(`20${s.slice(0, 2)}-${s.slice(2, 4)}-${s.slice(4, 6)}T${s.slice(6, 8)}:${s.slice(8, 10)}:${s.slice(10, 12)}`);
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
  });  player.on('error', (err) => console.log('[cmsv9] error:', err));
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

  const [searchParams] = useSearchParams();
  const deviceId = searchParams.get('deviceId');
  const device = useSelector((state) => state.devices.items[deviceId]);
  // Live position of this vehicle, for the map under the video.
  const position = useSelector((state) => state.session.positions[deviceId]);

  const defaultChannels = useAttributePreference('cmsv9Channels', 4);

  const cmsv9DeviceId = device?.attributes?.cmsv9DeviceId;

  const [tab, setTab] = useState(0);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [channel, setChannel] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [liveError, setLiveError] = useState(false);
  const [playbackActive, setPlaybackActive] = useState(false);
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
  useEffect(() => () => {
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
  }, [stopPlayback]);

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
  const startChannel = useCallback(async (ch, attempt = 0) => {
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
      const player = await createFlvPlayer(videoEl, data.flvUrl,
        { hasAudio: false, isResize: true });
      if (!player) {
        setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
        return;
      }
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
  }, [deviceId]);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, timelineDate, channel, cmsv9DeviceId]);

  const downloadSegment = useCallback((startStr, endStr) => {
    const url = `/api/cmsv9/download/${deviceId}/${channel}`
      + `?startTime=${encodeURIComponent(startStr)}`
      + `&endTime=${encodeURIComponent(endStr)}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }, [deviceId, channel]);

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
          <IconButton edge="start" sx={{ mr: 2 }} onClick={() => navigate(-1)}>
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
            <Tab label={t('sharedLive')} icon={<VideocamIcon />} iconPosition="start" />
            <Tab label={t('cmsv9Multi')} icon={<GridViewIcon />} iconPosition="start" />
            <Tab label="Download" icon={<DownloadIcon />} iconPosition="start" />
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
          <div className={classes.controls}>
            <TextField
              select
              size="small"
              label={t('commandIndex')}
              value={channel}
              onChange={(e) => setChannel(Number(e.target.value))}
              sx={{ minWidth: 120 }}
            >
              {channels.map((ch) => (
                <MenuItem key={ch} value={ch}>
                  {t('sharedChannel')} {ch + 1}
                </MenuItem>
              ))}
            </TextField>
            {tab === 0 && (
              <Button
                variant="contained"
                color={playing ? 'error' : 'primary'}
                startIcon={playing ? <StopIcon /> : <PlayArrowIcon />}
                disabled={loading}
                onClick={() => (playing ? doStopLive() : startLive())}
              >
                {playing ? t('sharedStop') : t('sharedPlay')}
              </Button>
            )}
            {tab === 0 && (
              <Button
                variant={singleHd ? 'contained' : 'outlined'}
                size="small"
                onClick={() => setSingleQuality(!singleHd)}
                sx={{ ml: 1 }}
                title="Toggle live quality. HD uses the DVR main stream; SD is lighter on a weak connection."
              >
                {singleHd ? 'HD' : 'SD'}
              </Button>
            )}
            {tab === 1 && (
              <Button
                variant="contained"
                color={gridActive ? 'error' : 'primary'}
                startIcon={gridActive ? <StopIcon /> : <PlayArrowIcon />}
                disabled={loading}
                onClick={() => (gridActive ? stopGrid() : startGrid())}
              >
                {gridActive ? t('sharedStop') : t('cmsv9PlayAll')}
              </Button>
            )}
            {tab === 1 && (
              <Button
                variant={gridHd ? 'contained' : 'outlined'}
                size="small"
                onClick={() => setGridQuality(!gridHd)}
                sx={{ ml: 1 }}
                title="Toggle live quality. HD uses the DVR main stream; SD (default) is lighter for multi-channel."
              >
                {gridHd ? 'HD' : 'SD'}
              </Button>
            )}
            {tab === 0 && (
              <Button
                variant="outlined"
                startIcon={<PhotoCameraIcon />}
                onClick={() => takeSnapshot(flvPlayerRef.current)}
                disabled={!playing}
              >
                {t('cmsv9Snapshot')}
              </Button>
            )}
            {loading && <CircularProgress size={20} />}
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
              {playing && !liveError && (
                <div ref={videoRef} className={classes.player} />
              )}
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
                  className={`${classes.cell}${selectedChannel === ch ? ` ${classes.cellSelected}` : ''}`}
                  onClick={() => (gridErrors[ch] ? startChannel(ch, 0) : setSelectedChannel(ch))}
                >
                  <Chip
                    label={`${device?.name ? `${device.name} - ` : ''}CH${ch + 1}`}
                    size="small"
                    className={classes.cellLabel}
                  />
                  {gridActive && !gridErrors[ch] && (
                    <div
                      ref={(el) => {
                        if (el) gridPlayers.current[ch] = { ...gridPlayers.current[ch], videoEl: el };
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
                    <IconButton
                      size="small"
                      className={classes.cellButton}
                      onClick={() => maximizeChannel(ch)}
                      disabled={!gridActive}
                    >
                      <OpenInFullIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      className={classes.cellButton}
                      onClick={() => {
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
                <MapCamera latitude={position.latitude} longitude={position.longitude} />
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
              {(playing || liveError) && (
                <Box sx={{ px: 2, pt: 2 }}>
                  <Box sx={{ position: 'relative', width: '100%', height: 320, background: '#000', borderRadius: 2, overflow: 'hidden' }}>
                    {!liveError && (
                      <div ref={videoRef} style={{ width: '100%', height: '100%' }} />
                    )}
                    {!liveError && !playbackActive && (
                      <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 1, color: '#fff' }}>
                        <CircularProgress size={28} color="inherit" />
                        <Typography variant="body2">Starting playback…</Typography>
                      </Box>
                    )}
                    {liveError && (
                      <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 0.5, color: '#fff', textAlign: 'center', px: 2 }}>
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
                    Channel {channel + 1} · {segments.length} segment{segments.length === 1 ? '' : 's'}
                  </Typography>
                </Box>
                <Box sx={{ position: 'relative', height: 44, borderRadius: 1, bgcolor: 'action.hover', overflow: 'hidden', border: '1px solid', borderColor: 'divider' }}>
                  {segments.map((seg, i) => {
                    const start = parseCnmsFileTime(seg.startTime);
                    const end = parseCnmsFileTime(seg.endTime);
                    if (!start || !end) return null;
                    const dayStart = timelineDate.startOf('day');
                    const leftPct = Math.min(100, Math.max(0, (start.diff(dayStart, 'second') / 86400) * 100));
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
                    <Typography key={h} variant="caption" color="textSecondary">{h}</Typography>
                  ))}
                </Box>
                <Typography variant="caption" color="textSecondary">
                  Select a segment to set the range, then press Preview to watch it or Download for the exact clip. The list below grabs whole segments.
                </Typography>
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
                      onClick={() => playRecording({ startTime: trimStart.format('YYYY-MM-DD HH:mm:ss'), endTime: trimEnd.format('YYYY-MM-DD HH:mm:ss') })}
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
                      onClick={() => downloadSegment(trimStart.format('YYYY-MM-DD HH:mm:ss'), trimEnd.format('YYYY-MM-DD HH:mm:ss'))}
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
                      secondaryAction={(
                        <IconButton
                          edge="end"
                          color="primary"
                          title="Download this clip"
                          onClick={() => downloadSegment(startStr, endStr)}
                        >
                          <DownloadIcon />
                        </IconButton>
                      )}
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
