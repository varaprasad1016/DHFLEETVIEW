import { useEffect, useState } from 'react';
import {
  Button,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useCatch } from '../reactHelper';
import { tachoListAudit, tachoFormatDate } from '../common/util/tachograph';

const ACTION_LABELS = {
  DOWNLOAD_REQUESTED: 'Download requested',
  DOWNLOAD_COMPLETED: 'Download completed',
  DOWNLOAD_FAILED: 'Download failed',
  DOWNLOAD_CANCELLED: 'Download cancelled',
  FILE_RETRIEVED: 'File downloaded by a user',
  FILE_DELETED: 'File deleted',
  FORWARD_QUEUED: 'Queued for delivery',
  FORWARD_DELIVERED: 'Delivered to bureau',
  FORWARD_FAILED: 'Delivery failed',
  TARGET_CHANGED: 'Delivery target changed',
  BRIDGE_PAIRED: 'Bridge paired',
  BRIDGE_REMOVED: 'Bridge removed',
  CARD_READ: 'Company card read',
  CONFIG_CHANGED: 'Settings changed',
};

/**
 * The audit trail.
 *
 * <p>Driver hours records are personal data, so who asked for them and who took a copy is itself
 * something that has to be answerable. This is the page that answers it.
 */
const TachographAuditTab = () => {
  const [entries, setEntries] = useState([]);

  const load = useCatch(async () => {
    setEntries((await tachoListAudit({ limit: 300 })) || []);
  });

  useEffect(() => {
    load();
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, []);

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Audit trail
        </Typography>
        <Button size="small" onClick={load}>
          Refresh
        </Button>
      </Stack>

      <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>When</TableCell>
              <TableCell>Action</TableCell>
              <TableCell>Who</TableCell>
              <TableCell>Detail</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id} hover>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  {tachoFormatDate(entry.createdAt)}
                </TableCell>
                <TableCell>{ACTION_LABELS[entry.action] || entry.action}</TableCell>
                <TableCell>
                  {entry.actor || (entry.userId ? `User ${entry.userId}` : 'system')}
                </TableCell>
                <TableCell>{entry.detail}</TableCell>
              </TableRow>
            ))}
            {entries.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} align="center">
                  <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                    Nothing recorded yet.
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

export default TachographAuditTab;
