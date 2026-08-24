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
import { default as Hls, Events } from 'hls.js/light';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import DownloadIcon from '@mui/icons-material/Download';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import VideocamIcon from '@mui/icons-material/Videocam';
import SearchIcon from '@mui/icons-material/Search';
import GridViewIcon from '@mui/icons-material/GridView';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import BackIcon from '../common/components/BackIcon';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useAttributePreference } from '../common/util/preferences';
import {
  cmsv9Login,
  cmsv9LiveHlsUrl,
  cmsv9Search,
  cmsv9PlaybackUrl,
  cmsv9DownloadUrl,
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

const Cmsv9VideoPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const t = useTranslation();

  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const gridRefs = useRef({});

  const [searchParams] = useSearchParams();
  const deviceId = searchParams.get('deviceId');
  const device = useSelector((state) => state.devices.items[deviceId]);

  // Configuration: server-level attributes set in Settings -> Server (custom attributes)
  const serverUrl = useAttributePreference('cmsv9Url', '');
  const mediaPort = useAttributePreference('cmsv9MediaPort', 6604);
  const account = useAttributePreference('cmsv9Account', '');
  const password = useAttributePreference('cmsv9Password', '');
  const defaultChannels = useAttributePreference('cmsv9Channels', 4);

  // Per-device mapping: device attribute "cmsv9DeviceId" links Traccar device -> CMSV9 devIdno
  const cmsv9DeviceId = device?.attributes?.cmsv9DeviceId;

  const [tab, setTab] = useState(0);
  const [session, setSession] = useState(null);
  const [loginError, setLoginError] = useState(null);
  const [loggingIn, setLoggingIn] = useState(false);

  const [channel, setChannel] = useState(0);
  const [streamType, setStreamType] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [liveError, setLiveError] = useState(false);
  const [playUrl, setPlayUrl] = useState(null);

  const [gridActive, setGridActive] = useState(false);
  const [gridErrors, setGridErrors] = useState({});

  const [from, setFrom] = useState(dayjs().subtract(1, 'hour'));
  const [to, setTo] = useState(dayjs());
  const [searching, setSearching] = useState(false);
  const [recordings, setRecordings] = useState([]);

  const channels = useMemo(() => Array.from({ length: Number(defaultChannels) || 4 }, (_, i) => i), [defaultChannels]);

  const ensureSession = useCallback(async () => {
    if (session) return session;
    setLoggingIn(true);
    setLoginError(null);
    try {
      const jsession = await cmsv9Login({ serverUrl, account, password });
      setSession(jsession);
      return jsession;
    } catch (error) {
      setLoginError(error.message);
      return null;
    } finally {
      setLoggingIn(false);
    }
  }, [serverUrl, account, password, session]);

  useEffect(() => {
    if (serverUrl && cmsv9DeviceId) {
      ensureSession();
    }
  }, [serverUrl, cmsv9DeviceId, ensureSession]);

  const stopPlayback = useCallback(() => {
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.removeAttribute('src');
      videoRef.current.load();
    }
    setPlayUrl(null);
    setPlaying(false);
  }, []);

  // Single player: attach HLS once the <video> element renders
  useEffect(() => {
    if (!playUrl || !videoRef.current) return;
    setLiveError(false);
    let hls = null;
    if (Hls.isSupported()) {
      hls = new Hls();
      hlsRef.current = hls;
      hls.loadSource(playUrl);
      hls.attachMedia(videoRef.current);
      hls.on(Events.MANIFEST_PARSED, () => videoRef.current.play());
      hls.on(Events.ERROR, (_, data) => {
        console.error('HLS error', data.type, data.details, data.fatal, data.networkDetails?.status, data.response?.url);
        if (data.fatal) {
          setLiveError(true);
          setPlaying(false);
        }
      });
    } else if (videoRef.current.canPlayType('application/vnd.apple.mpegurl')) {
      videoRef.current.src = playUrl;
      videoRef.current.play();
    } else {
      setLiveError(true);
      setPlaying(false);
    }
    return () => {
      if (hls) {
        hls.destroy();
        hlsRef.current = null;
      }
    };
  }, [playUrl]);

  const startLive = useCallback(async () => {
    setLiveError(false);
    stopPlayback();
    const jsession = await ensureSession();
    if (!jsession) return;
    const url = cmsv9LiveHlsUrl({
      serverUrl,
      mediaPort,
      jsession,
      deviceId: cmsv9DeviceId,
      channel,
      streamType,
    });
    setPlaying(true);
    setPlayUrl(url);
  }, [serverUrl, mediaPort, ensureSession, cmsv9DeviceId, channel, streamType, stopPlayback]);

  // Grid: attach one HLS instance per channel cell
  useEffect(() => {
    if (!gridActive) return;
    Object.entries(gridRefs.current).forEach(([ch, videoEl]) => {
      if (!videoEl || videoEl.dataset.attached) return;
      const url = cmsv9LiveHlsUrl({
        serverUrl,
        mediaPort,
        jsession: session,
        deviceId: cmsv9DeviceId,
        channel: Number(ch),
        streamType,
      });
      let hls = null;
      if (Hls.isSupported()) {
        hls = new Hls();
        videoEl.hls = hls;
        hls.loadSource(url);
        hls.attachMedia(videoEl);
        hls.on(Events.MANIFEST_PARSED, () => videoEl.play());
        hls.on(Events.ERROR, (_, data) => {
          if (data.fatal) {
            setGridErrors((prev) => ({ ...prev, [ch]: true }));
          }
        });
      } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
        videoEl.src = url;
        videoEl.play();
      } else {
        setGridErrors((prev) => ({ ...prev, [ch]: true }));
      }
      videoEl.dataset.attached = '1';
    });
    return () => {
      Object.values(gridRefs.current).forEach((videoEl) => {
        if (videoEl?.hls) {
          videoEl.hls.destroy();
          videoEl.hls = null;
        }
        if (videoEl) {
          delete videoEl.dataset.attached;
        }
      });
    };
  }, [gridActive, serverUrl, mediaPort, session, cmsv9DeviceId, streamType]);

  const startGrid = useCallback(async () => {
    const jsession = await ensureSession();
    if (!jsession) return;
    setGridErrors({});
    setGridActive(true);
  }, [ensureSession]);

  const stopGrid = useCallback(() => {
    setGridActive(false);
    setGridErrors({});
  }, []);

  const maximizeChannel = useCallback(
    (ch) => {
      stopGrid();
      setChannel(ch);
      setTab(0);
      setTimeout(() => startLive(), 50);
    },
    [stopGrid, startLive],
  );

  const takeSnapshot = useCatch(async (videoEl) => {
    if (!videoEl || !videoEl.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = videoEl.videoWidth;
    canvas.height = videoEl.videoHeight;
    canvas.getContext('2d').drawImage(videoEl, 0, 0);
    const link = document.createElement('a');
    link.download = `cmsv9-${cmsv9DeviceId}-${dayjs().format('YYYYMMDD-HHmmss')}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }, [cmsv9DeviceId]);

  const doSearch = useCatchCallback(
    async () => {
      const jsession = await ensureSession();
      if (!jsession) return;
      setSearching(true);
      try {
        const data = await cmsv9Search({
          serverUrl,
          jsession,
          deviceId: cmsv9DeviceId,
          channel,
          beginTime: from.format('YYYY-MM-DD HH:mm:ss'),
          endTime: to.format('YYYY-MM-DD HH:mm:ss'),
        });
        const list = data?.data?.list || data?.list || (Array.isArray(data?.data) ? data.data : []);
        setRecordings(list);
      } finally {
        setSearching(false);
      }
    },
    [serverUrl, ensureSession, cmsv9DeviceId, channel, from, to],
  );

  const playRecording = useCallback(
    (item) => {
      setLiveError(false);
      stopPlayback();
      const filePath = item.filePath || item.FPATH || item.videoFile;
      const fileBeg = item.fileBeg ?? item.FILEBEG ?? 0;
      const fileEnd = item.fileEnd ?? item.FILEEND ?? 0;
      const url = cmsv9PlaybackUrl({
        serverUrl,
        mediaPort,
        jsession: session,
        deviceId: cmsv9DeviceId,
        channel,
        filePath,
        fileBeg,
        fileEnd,
      });
      setPlaying(true);
      setPlayUrl(url);
    },
    [serverUrl, mediaPort, session, cmsv9DeviceId, channel, stopPlayback],
  );

  const downloadRecording = useCatchCallback(
    (item) => {
      const filePath = item.filePath || item.FPATH || item.videoFile;
      const fileLength = item.fileLength ?? item.FLENGTH ?? 0;
      const url = cmsv9DownloadUrl({
        serverUrl,
        mediaPort,
        jsession: session,
        deviceId: cmsv9DeviceId,
        filePath,
        fileLength,
        saveName: item.saveName,
      });
      window.open(url, '_blank');
    },
    [serverUrl, mediaPort, session, cmsv9DeviceId],
  );

  useEffect(() => () => stopPlayback(), [stopPlayback]);

  const configured = Boolean(serverUrl && cmsv9DeviceId);

  return (
    <div className={classes.root}>
      <AppBar position="static" color="transparent" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
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
            <TextField
              select
              size="small"
              label={t('cmsv9StreamType')}
              value={streamType}
              onChange={(e) => setStreamType(Number(e.target.value))}
              sx={{ minWidth: 130 }}
            >
              <MenuItem value={0}>{t('cmsv9MainStream')}</MenuItem>
              <MenuItem value={1}>{t('cmsv9SubStream')}</MenuItem>
            </TextField>
            {tab === 0 && (
              <Button
                variant="contained"
                color={playing ? 'error' : 'primary'}
                startIcon={playing ? <StopIcon /> : <PlayArrowIcon />}
                disabled={loggingIn || !session}
                onClick={() => (playing ? stopPlayback() : startLive())}
              >
                {playing ? t('sharedStop') : t('sharedPlay')}
              </Button>
            )}
            {tab === 1 && (
              <Button
                variant="contained"
                color={gridActive ? 'error' : 'primary'}
                startIcon={gridActive ? <StopIcon /> : <PlayArrowIcon />}
                disabled={loggingIn || !session}
                onClick={() => (gridActive ? stopGrid() : startGrid())}
              >
                {gridActive ? t('sharedStop') : t('cmsv9PlayAll')}
              </Button>
            )}
            {tab === 0 && (
              <Button
                variant="outlined"
                startIcon={<PhotoCameraIcon />}
                onClick={() => takeSnapshot(videoRef.current)}
                disabled={!playing}
              >
                {t('cmsv9Snapshot')}
              </Button>
            )}
            {loggingIn && <CircularProgress size={20} />}
          </div>
          {loginError && (
            <Typography color="error" variant="body2" sx={{ px: 2 }}>
              {t('cmsv9LoginFailed')}: {loginError}
            </Typography>
          )}
          {tab === 0 && (
            <div className={classes.video}>
              {playing && !liveError && <video ref={videoRef} className={classes.player} autoPlay muted controls />}
              {liveError && <Typography className={classes.overlay}>{t('errorConnection')}</Typography>}
              {!playing && !liveError && <Typography className={classes.overlay}>{t('sharedPlay')}</Typography>}
            </div>
          )}
          {tab === 1 && (
            <div className={classes.grid}>
              {channels.map((ch) => (
                <div key={ch} className={classes.cell}>
                  <Chip label={`${t('sharedChannel')} ${ch + 1}`} size="small" className={classes.cellLabel} />
                  {gridActive && !gridErrors[ch] && (
                    <video
                      ref={(el) => {
                        gridRefs.current[ch] = el;
                      }}
                      className={classes.cellVideo}
                      autoPlay
                      muted
                      playsInline
                    />
                  )}
                  {(!gridActive || gridErrors[ch]) && (
                    <Typography className={classes.cellPlaceholder}>
                      {gridErrors[ch] ? t('errorConnection') : t('sharedPlay')}
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
                      onClick={() => takeSnapshot(gridRefs.current[ch])}
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
                <Button variant="contained" startIcon={<SearchIcon />} onClick={doSearch} disabled={searching || !session}>
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
                  const label = item.filePath || item.FPATH || item.videoFile || `${t('sharedFile')} ${index + 1}`;
                  return (
                    <ListItemButton key={`${label}-${index}`} onClick={() => playRecording(item)}>
                      <ListItemText
                        primary={label}
                        secondary={item.startTime || item.begintime || item.fileBeg || ''}
                      />
                      <IconButton
                        edge="end"
                        onClick={(e) => {
                          e.stopPropagation();
                          downloadRecording(item);
                        }}
                      >
                        <DownloadIcon />
                      </IconButton>
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
