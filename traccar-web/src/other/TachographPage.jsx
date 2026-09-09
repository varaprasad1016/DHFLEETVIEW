import { useEffect, useState } from 'react';
import {
  Box, Button, Card, CardContent, Chip, FormControlLabel, Grid, MenuItem,
  Paper, Switch, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from '@mui/material';
import { useSelector } from 'react-redux';
import { t } from '../common/components/LocalizationProvider';
import PageLayout from '../common/components/PageLayout';
import SettingsMenu from '../settings/components/SettingsMenu';
import DownloadIcon from '@mui/icons-material/Download';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import AirIcon from '@mui/icons-material/Air';
import DashboardCustomizeIcon from '@mui/icons-material/DashboardCustomize';
import { useCatch, useCatchCallback } from '../reactHelper';
import {
  tachoGetConfiguration, tachoSaveConfiguration, tachoRequestDownload,
  tachoListDownloads, tachoListFiles, tachoListBridges, tachoGeneratePairingCode,
  tachoCancelDownload,
} from '../common/util/tachograph';

const TachographPage = () => {
  const [deviceId, setDeviceId] = useState('');
  const [config, setConfig] = useState(null);
  const [downloads, setDownloads] = useState([]);
  const [files, setFiles] = useState([]);
  const [bridges, setBridges] = useState([]);
  const [pairingCode, setPairingCode] = useState('');
  const [stats, setStats] = useState({ total: 0, completed: 0, pending: 0, failed: 0 });

  const devices = useSelector((state) => Object.values(state.devices.items));

  const loadConfig = useCatch(async () => {
    if (!deviceId) return;
    const data = await tachoGetConfiguration(Number(deviceId));
    setConfig(data);
  });

  const loadDownloads = useCatch(async () => {
    const data = await tachoListDownloads({ deviceId: deviceId || undefined, limit: 50 });
    const list = Array.isArray(data) ? data : [];
    setDownloads(list);
    const completed = list.filter((j) => j.status === 'COMPLETED').length;
    const pending = list.filter((j) => ['QUEUED', 'WAITING_FOR_DEVICE', 'WAITING_FOR_BRIDGE', 'REQUESTING', 'DOWNLOADING', 'PROCESSING'].includes(j.status)).length;
    const failed = list.filter((j) => j.status === 'FAILED').length;
    setStats({ total: list.length, completed, pending, failed, overdue: 0 });
  });

  const loadFiles = useCatch(async () => {
    const data = await tachoListFiles({ deviceId: deviceId || undefined, limit: 50 });
    setFiles(Array.isArray(data) ? data : []);
  });

  const loadBridges = useCatch(async () => {
    const data = await tachoListBridges();
    setBridges(Array.isArray(data) ? data : []);
  });

  useEffect(() => {
    loadBridges();
  }, []);

  useEffect(() => {
    if (deviceId) {
      loadConfig();
      loadDownloads();
      loadFiles();
    }
  }, [deviceId]);

  const handleSaveConfig = useCatchCallback(async () => {
    if (!config) return;
    await tachoSaveConfiguration(Number(deviceId), config);
  }, [config, deviceId]);

  const handleDownload = useCatchCallback(async (type) => {
    if (!deviceId) return;
    await tachoRequestDownload(Number(deviceId), type);
    await loadDownloads();
  }, [deviceId]);

  const handlePairingCode = useCatchCallback(async () => {
    // Use the first group's id as example; in a real deployment the user picks a company/group.
    const groups = await fetch('/api/groups').then((r) => r.json()).catch(() => []);
    const groupId = Array.isArray(groups) && groups.length > 0 ? groups[0].id : 1;
    const result = await tachoGeneratePairingCode(groupId, 'Tacho Bridge');
    setPairingCode(result.pairingCode || JSON.stringify(result));
  }, []);

  return (
    <PageLayout menu={<SettingsMenu />} breadcrumbs={['sharedTachograph']}>
      <Box sx={{ p: 2 }}>
        <Typography variant="h5" gutterBottom>Tachograph</Typography>

        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={6} sm={3}>
            <Card><CardContent><Typography variant="caption">Vehicles</Typography><Typography variant="h6">{devices.length}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card><CardContent><Typography variant="caption">Completed</Typography><Typography variant="h6">{stats.completed}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card><CardContent><Typography variant="caption">Pending</Typography><Typography variant="h6">{stats.pending}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={6} sm={3}>
            <Card><CardContent><Typography variant="caption">Failed</Typography><Typography variant="h6">{stats.failed}</Typography></CardContent></Card>
          </Grid>
        </Grid>

        <Paper sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" gutterBottom>Compliance</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            UK fleet compliance tools, unlocked by the monthly phone licence.
          </Typography>
          <Grid container spacing={2}>
            {[
              { label: 'Compliance hub', desc: 'All tools & licence status', href: '/tacho/compliance', icon: <DashboardCustomizeIcon /> },
              { label: 'Walkaround checks', desc: 'Driver daily vehicle check', href: '/tacho/walkaround', icon: <FactCheckIcon /> },
              { label: 'Vehicle defects', desc: 'Defects & rectification log', href: '/tacho/defects', icon: <WarningAmberIcon /> },
              { label: 'Tacho compliance', desc: "Drivers' hours & WTD, archive", href: '/tacho/hours', icon: <AccessTimeIcon /> },
              { label: 'MOT & tax reminders', desc: 'DVLA MOT, tax & Euro status', href: '/tacho/reminders', icon: <EventAvailableIcon /> },
              { label: 'Clean Air Zone', desc: 'ULEZ / CAZ charge exposure', href: '/tacho/caz', icon: <AirIcon /> },
            ].map((tool) => (
              <Grid item xs={12} sm={6} md={4} key={tool.href}>
                <Button
                  fullWidth
                  variant="outlined"
                  startIcon={tool.icon}
                  href={tool.href}
                  target="_blank"
                  rel="noopener"
                  sx={{ justifyContent: 'flex-start', textAlign: 'left', p: 1.5, height: '100%' }}
                >
                  <Box>
                    <Typography variant="subtitle2">{tool.label}</Typography>
                    <Typography variant="caption" color="text.secondary">{tool.desc}</Typography>
                  </Box>
                </Button>
              </Grid>
            ))}
          </Grid>
        </Paper>

        <Paper sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" gutterBottom>Vehicle Configuration</Typography>
          <TextField
            select
            label="Vehicle / Device"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            fullWidth
            sx={{ mb: 2 }}
          >
            {devices.map((d) => (
              <MenuItem key={d.id} value={String(d.id)}>{d.name} (ID {d.id})</MenuItem>
            ))}
          </TextField>
          {config && (
            <Box>
              <FormControlLabel
                control={<Switch checked={!!config.enabled} onChange={(e) => setConfig({ ...config, enabled: e.target.checked })} />}
                label="Tachograph enabled for this vehicle"
              />
              <Box sx={{ display: 'flex', gap: 2, mt: 2, flexWrap: 'wrap' }}>
                <TextField
                  label="Driver interval (days)"
                  type="number"
                  value={config.driverDownloadIntervalDays ?? 28}
                  onChange={(e) => setConfig({ ...config, driverDownloadIntervalDays: Number(e.target.value) })}
                />
                <TextField
                  label="Vehicle interval (days)"
                  type="number"
                  value={config.vehicleDownloadIntervalDays ?? 90}
                  onChange={(e) => setConfig({ ...config, vehicleDownloadIntervalDays: Number(e.target.value) })}
                />
              </Box>
              <Box sx={{ mt: 2, display: 'flex', gap: 1 }}>
                <Button variant="contained" onClick={handleSaveConfig}>Save Configuration</Button>
                <Button variant="outlined" onClick={() => handleDownload('DRIVER')}>Download Driver Data</Button>
                <Button variant="outlined" onClick={() => handleDownload('VEHICLE')}>Download Vehicle Data</Button>
              </Box>
            </Box>
          )}
        </Paper>

        <Paper sx={{ p: 2, mb: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="h6">Download History</Typography>
            <Button size="small" onClick={loadDownloads}>Refresh</Button>
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Device</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Progress</TableCell>
                  <TableCell>Error</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {downloads.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell>{job.id}</TableCell>
                    <TableCell>{job.deviceName || job.deviceId}</TableCell>
                    <TableCell>{job.downloadType}</TableCell>
                    <TableCell><Chip size="small" label={job.status} /></TableCell>
                    <TableCell>{job.progress}%</TableCell>
                    <TableCell>{job.errorCode || ''} {job.errorMessage || ''}</TableCell>
                    <TableCell>
                      {['QUEUED', 'WAITING_FOR_DEVICE', 'WAITING_FOR_BRIDGE', 'REQUESTING', 'DOWNLOADING'].includes(job.status) && (
                        <Button size="small" onClick={async () => { await tachoCancelDownload(job.id); loadDownloads(); }}>Cancel</Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {downloads.length === 0 && (
                  <TableRow><TableCell colSpan={7} align="center">No downloads yet</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>

        <Paper sx={{ p: 2, mb: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="h6">DDD Files</Typography>
            <Button size="small" onClick={loadFiles}>Refresh</Button>
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>File</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Size</TableCell>
                  <TableCell>SHA-256</TableCell>
                  <TableCell>Download</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {files.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell>{f.id}</TableCell>
                    <TableCell>{f.fileName}</TableCell>
                    <TableCell>{f.fileType}</TableCell>
                    <TableCell>{f.fileSize}</TableCell>
                    <TableCell sx={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.sha256}</TableCell>
                    <TableCell>
                      <Button size="small" href={`/api/tachograph/files/${f.id}/download`} target="_blank" rel="noopener">Download DDD</Button>
                    </TableCell>
                  </TableRow>
                ))}
                {files.length === 0 && (
                  <TableRow><TableCell colSpan={6} align="center">No files yet</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>

        <Paper sx={{ p: 2 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="h6">Tacho Bridges</Typography>
            <Button size="small" onClick={loadBridges}>Refresh</Button>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
            <Button
              variant="contained"
              startIcon={<DownloadIcon />}
              href="/api/tachograph/bridge/download"
            >
              Download Tacho Bridge App (Windows)
            </Button>
            <Button variant="outlined" onClick={handlePairingCode}>Generate Pairing Code</Button>
            {pairingCode && <Chip label={`Pairing code: ${pairingCode}`} color="primary" />}
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Install the Tacho Bridge App on the PC that has the company-card reader (card rack),
            generate a pairing code above, and enter it in the app to link the reader to this
            server. The app reads the company cards and relays authentication automatically
            during remote downloads.
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Bridge ID</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Reader</TableCell>
                  <TableCell>Card</TableCell>
                  <TableCell>Last Heartbeat</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {bridges.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>{b.id}</TableCell>
                    <TableCell>{b.bridgeId}</TableCell>
                    <TableCell>{b.name}</TableCell>
                    <TableCell><Chip size="small" label={b.status} color={b.status === 'ONLINE' ? 'success' : 'default'} /></TableCell>
                    <TableCell>{b.readerStatus || '-'}</TableCell>
                    <TableCell>{b.cardStatus || '-'}</TableCell>
                    <TableCell>{b.lastHeartbeat || '-'}</TableCell>
                  </TableRow>
                ))}
                {bridges.length === 0 && (
                  <TableRow><TableCell colSpan={7} align="center">No bridges registered</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>

        <Box sx={{ mt: 2 }}>
          <Typography variant="caption" color="text.secondary">
            Simulator mode: {String(JSON.stringify({ note: 'Enable tacho.simulator=true for testing without hardware' }))}
          </Typography>
        </Box>
      </Box>
    </PageLayout>
  );
};

export default TachographPage;
