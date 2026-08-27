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
} from '../common/util/cmsv9';
import { useCatch, useCatchCallback } from '../reactHelper';

const useStyles = makeStyles()((theme) => ({
  root: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
  },
  title: {
    flexGrow: 1,
  },
  video: {
    flexGrow: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#000',
    minHeight: 240,
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
  },
  grid: {
    flexGrow: 1,
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
    gap: theme.spacing(1),
    padding: theme.spacing(1, 2),
    overflow: 'auto',
    backgroundColor: '#000',
    alignContent: 'start',
  },
  cell: {
    position: 'relative',
    backgroundColor: '#0a0a0a',
    borderRadius: 8,
    overflow: 'hidden',
    aspectRatio: '16 / 9',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: `1px solid ${theme.palette.divider}`,
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
}));

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

async function createFlvPlayer(container, url) {
  const Jessibuca = await loadJessibuca();
  const player = new Jessibuca({
    container,
    videoBuffer: 0.6,
    decoder: '/decoder.js',
    hasAudio: true,
    isFlv: true,
    useMSE: false,
    autoWasm: true,
    debug: true,
    showBandwidth: false,
    isResize: false,
    useWebFullScreen: false,
    timeout: 20,
    loadingTimeout: 30,
  });
  player.on('error', (err) => console.log('[cmsv9] error:', err));
  player.on('videoInfo', (d) => console.log('[cmsv9] videoInfo:', d));
  player.on('audioInfo', (d) => console.log('[cmsv9] audioInfo:', d));
  player.on('load', () => console.log('[cmsv9] load'));
  player.on('play', () => console.log('[cmsv9] play'));
  player.on('start', () => console.log('[cmsv9] start'));
  player.on('timeout', () => console.log('[cmsv9] timeout'));
  player.on('loadingTimeout', () => console.log('[cmsv9] loadingTimeout'));
  player.play(url).then(
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

async function waitForStream(url, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      const res = await fetch(url, { signal: controller.signal, cache: 'no-store' });
      clearTimeout(timer);
      if (res.ok) return true;
    } catch (e) {
      // keep polling while device starts pushing
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
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

  const defaultChannels = useAttributePreference('cmsv9Channels', 4);

  const cmsv9DeviceId = device?.attributes?.cmsv9DeviceId;

  const [tab, setTab] = useState(0);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [channel, setChannel] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [liveError, setLiveError] = useState(false);
  const [playerMsg, setPlayerMsg] = useState('');

  const [gridActive, setGridActive] = useState(false);
  const [gridErrors, setGridErrors] = useState({});

  const [from, setFrom] = useState(dayjs().subtract(1, 'hour'));
  const [to, setTo] = useState(dayjs());
  const [searching, setSearching] = useState(false);
  const [recordings, setRecordings] = useState([]);

  const channels = useMemo(() => {
    const n = config?.channels || Number(defaultChannels) || 4;
    return Array.from({ length: Math.min(Math.max(Number(n), 1), 16) }, (_, i) => i);
  }, [config, defaultChannels]);

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

  const startLive = useCallback(async () => {
    setLiveError(false);
    setPlayerMsg('');
    stopPlayback();
    await ensureConfig();
    if (!cmsv9DeviceId) return;

    setLoading(true);
    try {
      const data = await cmsv9StartLive(deviceId, channel);
      if (data.errCode !== 0 && data.errCode !== -1) {
        throw new Error(data.resultMsg || 'Failed to start live');
      }
      const { flvUrl } = data;
      if (!flvUrl) throw new Error('No stream URL returned');
      setPlaying(true);
      const found = await waitForStream(flvUrl);
      if (!found) {
        setLiveError(true);
        setPlaying(false);
        return;
      }
      if (!videoRef.current) return;
      const player = await createFlvPlayer(videoRef.current, flvUrl);
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
  }, [ensureConfig, cmsv9DeviceId, channel, stopPlayback]);

  const doStopLive = useCallback(async () => {
    stopPlayback();
    if (cmsv9DeviceId) {
      try {
        await cmsv9StopLive(deviceId, channel);
      } catch (e) {
        // ignore
      }
    }
  }, [cmsv9DeviceId, channel, stopPlayback]);

  useEffect(() => () => stopPlayback(), [stopPlayback]);

  const [pendingMaximize, setPendingMaximize] = useState(null);

  const autoPlayedRef = useRef(false);
  useEffect(() => {
    if (config && cmsv9DeviceId && !autoPlayedRef.current && tab === 0 && !playing) {
      autoPlayedRef.current = true;
      startLive();
    }
  }, [config, cmsv9DeviceId, tab, playing, startLive]);

  const stopGrid = useCallback(() => {
    channels.forEach((ch) => {
      destroyFlvPlayer(gridPlayers.current[ch]?.player);
      delete gridPlayers.current[ch];
    });
    setGridActive(false);
    setGridErrors({});
  }, [channels]);

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
    setGridErrors({});
    setGridActive(true);
  }, [ensureConfig, cmsv9DeviceId]);

  useEffect(() => {
    if (!gridActive || !config) return;
    const timers = [];
    const cancelled = new Set();
    channels.forEach(async (ch) => {
      const videoEl = gridPlayers.current[ch]?.videoEl;
      if (!videoEl || videoEl.dataset.attached) return;
      try {
        let data = await cmsv9StartLive(deviceId, ch);
        if (data.errCode !== 0 && data.errCode !== -1) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'novideo' }));
          return;
        }
        if (!data.flvUrl) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'novideo' }));
          return;
        }
        let found = await waitForStream(data.flvUrl, 120000);
        if (!found) {
          data = await cmsv9StartLive(deviceId, ch);
          found = data.flvUrl ? await waitForStream(data.flvUrl, 90000) : false;
        }
        if (!found) {
          setGridErrors((prev) => ({ ...prev, [ch]: 'novideo' }));
          return;
        }
        if (cancelled.has(ch)) return;
        const player = await createFlvPlayer(videoEl, data.flvUrl);
        gridPlayers.current[ch] = { player, videoEl };
        videoEl.dataset.attached = '1';
        if (player) {
          const timer = setTimeout(() => {
            setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
            destroyFlvPlayer(player);
            delete gridPlayers.current[ch];
          }, 120000);
          timers.push(timer);
          player.on('videoInfo', () => {
            clearTimeout(timer);
          });
          player.on('error', () => {
            clearTimeout(timer);
            setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
          });
        } else {
          setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
        }
      } catch (e) {
        setGridErrors((prev) => ({ ...prev, [ch]: 'error' }));
      }
    });
    return () => {
      channels.forEach((ch) => cancelled.add(ch));
      timers.forEach(clearTimeout);
      channels.forEach((ch) => {
        destroyFlvPlayer(gridPlayers.current[ch]?.player);
        if (gridPlayers.current[ch]?.videoEl) {
          delete gridPlayers.current[ch].videoEl.dataset.attached;
        }
        delete gridPlayers.current[ch];
      });
    };
  }, [gridActive, config, cmsv9DeviceId, channels]);

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

  const playRecording = useCallback(
    async (item) => {
      setLiveError(false);
      stopPlayback();
      if (!cmsv9DeviceId) return;
      setLoading(true);
      try {
        const data = await cmsv9StartPlayback(
          deviceId,
          channel,
          item.startTime || from.format('YYYY-MM-DD HH:mm:ss'),
          item.endTime || to.format('YYYY-MM-DD HH:mm:ss'),
        );
        if (data.errCode !== 0) {
          throw new Error(data.resultMsg || 'Failed to start playback');
        }
        const { flvUrl } = data;
        if (!flvUrl) throw new Error('No playback URL returned');
        setPlaying(true);
        const found = await waitForStream(flvUrl);
        if (!found) {
          setLiveError(true);
          setPlaying(false);
          return;
        }
        if (!videoRef.current) return;
        const player = await createFlvPlayer(videoRef.current, flvUrl);
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
          <Tabs value={tab} onChange={(_, value) => setTab(value)} className={classes.tab}>
            <Tab label={t('sharedLive')} icon={<VideocamIcon />} iconPosition="start" />
            <Tab label={t('cmsv9Multi')} icon={<GridViewIcon />} iconPosition="start" />
            <Tab label={t('reportTitle')} icon={<SearchIcon />} iconPosition="start" />
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
            <div className={classes.video}>
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
          {tab === 1 && (
            <div className={classes.grid}>
              {channels.map((ch) => (
                <div key={ch} className={classes.cell}>
                  <Chip
                    label={`${t('sharedChannel')} ${ch + 1}`}
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
                      {gridErrors[ch] === 'novideo' && t('cmsv9NoVideo')}
                      {gridErrors[ch] === 'error' && t('errorConnection')}
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
          {tab === 2 && (
            <>
              <div className={classes.search}>
                <TextField
                  size="small"
                  type="datetime-local"
                  label={t('reportFrom')}
                  value={from.format('YYYY-MM-DDTHH:mm')}
                  onChange={(e) => setFrom(dayjs(e.target.value))}
                />
                <TextField
                  size="small"
                  type="datetime-local"
                  label={t('reportTo')}
                  value={to.format('YYYY-MM-DDTHH:mm')}
                  onChange={(e) => setTo(dayjs(e.target.value))}
                />
                <Button
                  variant="contained"
                  startIcon={<SearchIcon />}
                  onClick={doSearch}
                  disabled={searching || !config}
                >
                  {t('sharedSearch')}
                </Button>
                {searching && <CircularProgress size={20} />}
              </div>
              <List dense className={classes.list}>
                {recordings.length === 0 && !searching && (
                  <ListItem>
                    <ListItemText primary={t('sharedNoData')} />
                  </ListItem>
                )}
                {recordings.map((item, index) => {
                  const label = item.dName
                    ? `${item.dName} - ${t('sharedFile')} ${index + 1}`
                    : `${t('sharedFile')} ${index + 1}`;
                  const time = item.startTime
                    ? `${item.startTime} - ${item.endTime}`
                    : '';
                  return (
                    <ListItemButton key={`${index}`} onClick={() => playRecording(item)}>
                      <ListItemText primary={label} secondary={time} />
                    </ListItemButton>
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
