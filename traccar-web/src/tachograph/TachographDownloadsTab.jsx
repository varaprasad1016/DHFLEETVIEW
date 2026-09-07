import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { useCatch } from '../reactHelper';
import {
  tachoListDownloads,
  tachoCancelDownload,
  isTachoJobActive,
  tachoStatusColour,
  tachoExplainError,
  tachoFormatDate,
} from '../common/util/tachograph';

/**
 * The download job list.
 *
 * <p>It polls, but only while something is actually running. A tachograph download takes minutes
 * and an operator will sit watching this page waiting for it, so it has to move; once everything
 * has settled there is nothing to watch and polling would be pure load on the server for no
 * benefit, so it stops.
 */
const ACTIVE_POLL_MILLIS = 4000;

const STATUS_FILTERS = [
  { value: '', label: 'All statuses' },
  { value: 'DOWNLOADING', label: 'Downloading' },
  { value: 'QUEUED', label: 'Queued' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

const TachographDownloadsTab = () => {
  const [jobs, setJobs] = useState([]);
  const [status, setStatus] = useState('');
  const pollTimerRef = useRef(null);

  const load = useCatch(async (selectedStatus) => {
    setJobs((await tachoListDownloads({ status: selectedStatus || undefined, limit: 100 })) || []);
  });

  const refresh = useCallback(() => load(status), [load, status]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, [status]);

  useEffect(() => {
    const anyActive = jobs.some((job) => isTachoJobActive(job.status));
    if (anyActive) {
      pollTimerRef.current = setTimeout(refresh, ACTIVE_POLL_MILLIS);
    }
    return () => clearTimeout(pollTimerRef.current);
  }, [jobs, refresh]);

  const handleCancel = useCatch(async (id) => {
    await tachoCancelDownload(id);
    refresh();
  });

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Downloads
        </Typography>
        <TextField
          select
          size="small"
          label="Status"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          sx={{ minWidth: 180 }}
        >
          {STATUS_FILTERS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {option.label}
            </MenuItem>
          ))}
        </TextField>
        <Button size="small" onClick={refresh}>
          Refresh
        </Button>
      </Stack>

      <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Job</TableCell>
              <TableCell>Vehicle</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Status</TableCell>
              <TableCell sx={{ minWidth: 200 }}>Progress</TableCell>
              <TableCell>Started</TableCell>
              <TableCell>Result</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {jobs.map((job) => {
              const active = isTachoJobActive(job.status);
              const explanation = tachoExplainError(job.errorCode);
              return (
                <TableRow key={job.id} hover>
                  <TableCell>{job.id}</TableCell>
                  <TableCell>{job.deviceName || job.deviceId}</TableCell>
                  <TableCell>
                    {job.downloadType === 'DRIVER' ? 'Driver card' : 'Vehicle unit'}
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={job.status} color={tachoStatusColour(job.status)} />
                  </TableCell>
                  <TableCell>
                    {active ? (
                      <Box>
                        <LinearProgress variant="determinate" value={job.progress || 0} />
                        <Typography variant="caption" color="text.secondary">
                          {`${job.progress || 0}% · ${job.progressDetail || ''}`}
                        </Typography>
                      </Box>
                    ) : (
                      <Typography variant="caption" color="text.secondary">
                        {job.progressDetail || '—'}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>{tachoFormatDate(job.startedAt)}</TableCell>
                  <TableCell sx={{ maxWidth: 320 }}>
                    {job.errorCode ? (
                      <Tooltip title={job.errorMessage || ''}>
                        <Typography variant="caption" color="error">
                          {explanation || job.errorCode}
                        </Typography>
                      </Tooltip>
                    ) : (
                      <Typography variant="caption" color="text.secondary">
                        {job.status === 'COMPLETED' ? 'Stored' : '—'}
                      </Typography>
                    )}
                    {job.retryCount > 0 && job.status !== 'COMPLETED' && (
                      <Typography variant="caption" display="block" color="text.secondary">
                        {`Retry ${job.retryCount}, next ${tachoFormatDate(job.nextRetryAt)}`}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {active && (
                      <Button size="small" onClick={() => handleCancel(job.id)}>
                        Cancel
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {jobs.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} align="center">
                  <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                    No downloads yet. Start one from the Vehicles tab.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
};

export default TachographDownloadsTab;
