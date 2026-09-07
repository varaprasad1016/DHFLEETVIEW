import { useEffect, useState } from 'react';
import { Alert, Box, Tab, Tabs, Typography } from '@mui/material';
import PageLayout from '../common/components/PageLayout';
import SettingsMenu from '../settings/components/SettingsMenu';
import DownloadIcon from '@mui/icons-material/Download';
import { useCatch, useCatchCallback } from '../reactHelper';
import {
  tachoGetConfiguration, tachoSaveConfiguration, tachoRequestDownload,
  tachoListDownloads, tachoListFiles, tachoListBridges, tachoGeneratePairingCode,
  tachoCancelDownload,
} from '../common/util/tachograph';

import { useCatch } from '../reactHelper';
import { tachoGetSummary } from '../common/util/tachograph';
import TachographStatCards from '../tachograph/TachographStatCards';
import TachographVehiclesTab from '../tachograph/TachographVehiclesTab';
import TachographDownloadsTab from '../tachograph/TachographDownloadsTab';
import TachographFilesTab from '../tachograph/TachographFilesTab';
import TachographBridgesTab from '../tachograph/TachographBridgesTab';
import TachographDeliveryTab from '../tachograph/TachographDeliveryTab';
import TachographAuditTab from '../tachograph/TachographAuditTab';

const TABS = [
  { key: 'vehicles', label: 'Vehicles', component: TachographVehiclesTab },
  { key: 'downloads', label: 'Downloads', component: TachographDownloadsTab },
  { key: 'files', label: 'Files', component: TachographFilesTab },
  { key: 'bridges', label: 'Bridges', component: TachographBridgesTab },
  { key: 'delivery', label: 'Delivery', component: TachographDeliveryTab },
  { key: 'audit', label: 'Audit', component: TachographAuditTab },
];

/**
 * The tachograph section.
 *
 * <p>The summary strip stays visible across every tab because the two numbers that matter — is
 * anything failing, and is anything stuck undelivered — are the ones an operator would otherwise
 * only discover by going looking. Failures are highlighted rather than merely counted.
 */
const TachographPage = () => {
  const [tab, setTab] = useState('vehicles');
  const [summary, setSummary] = useState(null);

  const loadSummary = useCatch(async () => {
    setSummary(await tachoGetSummary());
  });

  useEffect(() => {
    loadSummary();
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, [tab]);

  const ActiveTab = TABS.find((entry) => entry.key === tab)?.component ?? TachographVehiclesTab;

  const stats = summary
    ? [
        { label: 'In progress', value: summary.activeDownloads },
        { label: 'Completed', value: summary.completedDownloads },
        {
          label: 'Failed',
          value: summary.failedDownloads,
          alert: summary.failedDownloads > 0,
        },
        { label: 'Files stored', value: summary.files },
        {
          label: 'Bridges ready',
          value: `${summary.bridgesReady}/${summary.bridges}`,
          alert: summary.bridges > 0 && summary.bridgesReady === 0,
          detail: summary.bridges === 0 ? 'none paired' : undefined,
        },
        {
          label: 'Awaiting delivery',
          value: summary.pendingDeliveries,
        },
        {
          label: 'Delivery failures',
          value: summary.failedDeliveries,
          alert: summary.failedDeliveries > 0,
        },
      ]
    : [];

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
        <Typography variant="h5" gutterBottom>
          Tachograph
        </Typography>

        {summary?.simulator && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Simulator mode is on. Downloads are produced by a built-in emulator and are not real
            tachograph data. Turn off <code>tacho.simulator</code> before using this in production.
          </Alert>
        )}

        {summary && !summary.simulator && !summary.tunnelPort && (
          <Alert severity="info" sx={{ mb: 2 }}>
            No tachograph tunnel port is configured, so vehicles cannot connect for a download. Set{' '}
            <code>tacho.tunnel.port</code> on the server and point the vehicles&apos; remote
            tachograph server setting at it.
          </Alert>
        )}

        {summary && <TachographStatCards stats={stats} />}

        <Tabs
          value={tab}
          onChange={(event, value) => setTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
        >
          {TABS.map((entry) => (
            <Tab key={entry.key} value={entry.key} label={entry.label} />
          ))}
        </Tabs>

        <ActiveTab />
      </Box>
    </PageLayout>
  );
};

export default TachographPage;
