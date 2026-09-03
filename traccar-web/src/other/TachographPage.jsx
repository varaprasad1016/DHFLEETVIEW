import { useEffect, useState } from 'react';
import { Alert, Box, Tab, Tabs, Typography } from '@mui/material';
import PageLayout from '../common/components/PageLayout';
import SettingsMenu from '../settings/components/SettingsMenu';
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
