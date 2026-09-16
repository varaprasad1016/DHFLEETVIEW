import { useCallback, useEffect, useState } from 'react';
import {
  Box, Button, Card, CardContent, Chip, Dialog, DialogTitle, DialogContent,
  DialogActions, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Paper, Tabs, Tab, List, ListItem, ListItemText,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import RefreshIcon from '@mui/icons-material/Refresh';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { activeShifts, shiftHistory, getShift } from '../common/util/shifts';

const useStyles = makeStyles()((theme) => ({
  root: { p: 2 },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 },
  tabContent: { mt: 2 },
  statusActive: { bgcolor: 'success.light', color: 'success.contrastText' },
  statusBreak: { bgcolor: 'warning.light', color: 'warning.contrastText' },
  statusOut: { bgcolor: 'grey.300', color: 'text.primary' },
  photoGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: theme.spacing(1), mt: 1 },
  photoCard: { textAlign: 'center' },
  photoImg: { width: '100%', height: 150, objectFit: 'cover', borderRadius: 4 },
}));

const ShiftDetailDialog = ({ shift, open, onClose }) => {
  const classes = useStyles();
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (shift && open) {
      getShift(shift.id).then(setDetail).catch(() => setDetail(null));
    }
  }, [shift, open]);

  if (!shift) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Shift Details — {shift.driver_name}</DialogTitle>
      <DialogContent>
        {detail && (
          <>
            <Typography variant="subtitle2" gutterBottom>Status</Typography>
            <Chip
              label={shift.status.replace('_', ' ').toUpperCase()}
              color={shift.status === 'clocked_out' ? 'default' : shift.status === 'on_break' ? 'warning' : 'success'}
              sx={{ mb: 2 }}
            />

            <Typography variant="subtitle2" gutterBottom>Timing</Typography>
            <Typography variant="body2">Clock In: {new Date(shift.clocked_in_at).toLocaleString()}</Typography>
            {shift.clocked_out_at && (
              <Typography variant="body2">Clock Out: {new Date(shift.clocked_out_at).toLocaleString()}</Typography>
            )}
            {shift.break_started_at && (
              <Typography variant="body2">Break: {new Date(shift.break_started_at).toLocaleString()}</Typography>
            )}

            <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>Readings</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
              <Card variant="outlined"><CardContent>
                <Typography variant="caption">Odometer In</Typography>
                <Typography variant="body1">{shift.odometer_km ?? '-'} km</Typography>
              </CardContent></Card>
              <Card variant="outlined"><CardContent>
                <Typography variant="caption">Odometer Out</Typography>
                <Typography variant="body1">{shift.odometer_out_km ?? '-'} km</Typography>
              </CardContent></Card>
              <Card variant="outlined"><CardContent>
                <Typography variant="caption">Fuel In</Typography>
                <Typography variant="body1">{shift.fuel_level_pct ?? '-'}%</Typography>
              </CardContent></Card>
              <Card variant="outlined"><CardContent>
                <Typography variant="caption">Fuel Out</Typography>
                <Typography variant="body1">{shift.fuel_level_out_pct ?? '-'}%</Typography>
              </CardContent></Card>
              <Card variant="outlined"><CardContent>
                <Typography variant="caption">AdBlue In</Typography>
                <Typography variant="body1">{shift.adblue_level_pct ?? '-'}%</Typography>
              </CardContent></Card>
              <Card variant="outlined"><CardContent>
                <Typography variant="caption">AdBlue Out</Typography>
                <Typography variant="body1">{shift.adblue_level_out_pct ?? '-'}%</Typography>
              </CardContent></Card>
            </Box>

            {detail.photos && detail.photos.length > 0 && (
              <>
                <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>Photos</Typography>
                <Box className={classes.photoGrid}>
                  {detail.photos.map((p) => (
                    <Card key={p.id} variant="outlined" className={classes.photoCard}>
                      <img
                        src={`/api/shifts/photos/${p.id}`}
                        alt={p.photo_type}
                        className={classes.photoImg}
                        loading="lazy"
                      />
                      <Typography variant="caption" display="block" sx={{ p: 0.5 }}>
                        {p.photo_type.replace('_', ' ')}
                      </Typography>
                    </Card>
                  ))}
                </Box>
              </>
            )}

            {detail.jobs && detail.jobs.length > 0 && (
              <>
                <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>Jobs</Typography>
                <List dense>
                  {detail.jobs.map((j) => (
                    <ListItem key={j.id}>
                      <ListItemText
                        primary={j.title}
                        secondary={
                          <Chip size="small" label={j.status} color={
                            j.status === 'accepted' ? 'success' :
                            j.status === 'completed' ? 'default' : 'warning'
                          } />
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              </>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
};

const ShiftsReportTab = () => {
  const classes = useStyles();
  const [active, setActive] = useState([]);
  const [history, setHistory] = useState([]);
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [detailShift, setDetailShift] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, h] = await Promise.all([activeShifts(), shiftHistory()]);
      setActive(a || []);
      setHistory(h || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const viewDetail = useCallback((shift) => {
    setDetailShift(shift);
    setDetailOpen(true);
  }, []);

  return (
    <Box className={classes.root}>
      <Box className={classes.header}>
        <Typography variant="h6">Shift Report</Typography>
        <Button startIcon={<RefreshIcon />} onClick={load} disabled={loading}>Refresh</Button>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label={`Active (${active.length})`} />
        <Tab label={`History (${history.length})`} />
      </Tabs>

      <Box className={classes.tabContent}>
        {tab === 0 && (
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Driver</TableCell>
                  <TableCell>Vehicle</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Odometer</TableCell>
                  <TableCell>Fuel</TableCell>
                  <TableCell>Started</TableCell>
                  <TableCell>Details</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {active.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>{s.driver_name}</TableCell>
                    <TableCell>{s.vehicle_reg || '-'}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={s.status === 'on_break' ? 'ON BREAK' : 'CLOCKED IN'}
                        color={s.status === 'on_break' ? 'warning' : 'success'}
                      />
                    </TableCell>
                    <TableCell>{s.odometer_km ?? '-'} km</TableCell>
                    <TableCell>{s.fuel_level_pct ?? '-'}%</TableCell>
                    <TableCell>{new Date(s.clocked_in_at).toLocaleString()}</TableCell>
                    <TableCell>
                      <Button size="small" onClick={() => viewDetail(s)}>
                        <VisibilityIcon fontSize="small" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {active.length === 0 && (
                  <TableRow><TableCell colSpan={7} align="center">
                    <Typography color="text.secondary">No active shifts</Typography>
                  </TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {tab === 1 && (
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Driver</TableCell>
                  <TableCell>Vehicle</TableCell>
                  <TableCell>Odometer In/Out</TableCell>
                  <TableCell>Fuel In/Out</TableCell>
                  <TableCell>AdBlue In/Out</TableCell>
                  <TableCell>Clock In</TableCell>
                  <TableCell>Clock Out</TableCell>
                  <TableCell>Details</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {history.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>{s.driver_name}</TableCell>
                    <TableCell>{s.vehicle_reg || '-'}</TableCell>
                    <TableCell>{s.odometer_km ?? '-'} / {s.odometer_out_km ?? '-'} km</TableCell>
                    <TableCell>{s.fuel_level_pct ?? '-'} / {s.fuel_level_out_pct ?? '-'}%</TableCell>
                    <TableCell>{s.adblue_level_pct ?? '-'} / {s.adblue_level_out_pct ?? '-'}%</TableCell>
                    <TableCell>{s.clocked_in_at ? new Date(s.clocked_in_at).toLocaleString() : '-'}</TableCell>
                    <TableCell>{s.clocked_out_at ? new Date(s.clocked_out_at).toLocaleString() : '-'}</TableCell>
                    <TableCell>
                      <Button size="small" onClick={() => viewDetail(s)}>
                        <VisibilityIcon fontSize="small" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {history.length === 0 && (
                  <TableRow><TableCell colSpan={8} align="center">
                    <Typography color="text.secondary">No shift history</Typography>
                  </TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>

      <ShiftDetailDialog shift={detailShift} open={detailOpen} onClose={() => setDetailOpen(false)} />
    </Box>
  );
};

export default ShiftsReportTab;
