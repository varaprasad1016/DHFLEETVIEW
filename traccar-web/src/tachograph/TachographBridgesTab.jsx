import { useEffect, useState } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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
  Typography,
} from '@mui/material';
import { useSelector } from 'react-redux';
import { useCatch } from '../reactHelper';
import {
  tachoListBridges,
  tachoGeneratePairingCode,
  tachoDeleteBridge,
  tachoReadCard,
  tachoStatusColour,
  tachoFormatDate,
} from '../common/util/tachograph';

/** A card this close to expiry gets a visible warning rather than a silent countdown. */
const EXPIRY_WARNING_DAYS = 30;

const daysUntil = (value) => {
  if (!value) {
    return null;
  }
  return Math.floor((new Date(value).getTime() - Date.now()) / (24 * 60 * 60 * 1000));
};

/**
 * Tacho bridges: the office machines that hold a company card and make it reachable to the fleet.
 *
 * <p>The expiry warning here is the most valuable thing on the page. A company card that runs out
 * does not announce itself — every scheduled download in the fleet simply starts failing
 * authentication, and by the time somebody investigates, weeks of legally required data may be
 * missing. Thirty days is enough notice to order a replacement.
 */
const TachographBridgesTab = () => {
  const groups = useSelector((state) => Object.values(state.groups.items));

  const [bridges, setBridges] = useState([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [groupId, setGroupId] = useState('0');
  const [name, setName] = useState('Tacho Bridge');
  const [pairing, setPairing] = useState(null);
  const [cardResult, setCardResult] = useState(null);

  const load = useCatch(async () => {
    setBridges((await tachoListBridges()) || []);
  });

  useEffect(() => {
    load();
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, []);

  const handleGenerate = useCatch(async () => {
    const result = await tachoGeneratePairingCode(Number(groupId), name);
    setPairing(result);
    setDialogOpen(false);
    load();
  });

  const handleDelete = useCatch(async (id) => {
    await tachoDeleteBridge(id);
    load();
  });

  const handleReadCard = useCatch(async (id) => {
    const identity = await tachoReadCard(id);
    setCardResult(identity);
    load();
  });

  const expiringBridges = bridges.filter((bridge) => {
    const days = daysUntil(bridge.cardValidityTo);
    return days !== null && days <= EXPIRY_WARNING_DAYS;
  });

  return (
    <Box>
      {expiringBridges.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <AlertTitle>Company card expiring</AlertTitle>
          {expiringBridges.map((bridge) => {
            const days = daysUntil(bridge.cardValidityTo);
            return (
              <Typography key={bridge.id} variant="body2">
                {days < 0
                  ? `${bridge.name}: the card expired on ${tachoFormatDate(bridge.cardValidityTo)}. Downloads will fail until it is replaced.`
                  : `${bridge.name}: the card expires in ${days} day${days === 1 ? '' : 's'}. Order a replacement now.`}
              </Typography>
            );
          })}
        </Alert>
      )}

      {pairing && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setPairing(null)}>
          <AlertTitle>Pairing code</AlertTitle>
          <Typography variant="h4" sx={{ letterSpacing: 4, my: 1 }}>
            {pairing.pairingCode}
          </Typography>
          <Typography variant="body2">
            On the office machine run:{' '}
            <code>{`java -jar tacho-bridge.jar pair ${pairing.pairingCode}`}</code>
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {`Single use, expires ${tachoFormatDate(pairing.expiresAt)}. It is not shown again.`}
          </Typography>
        </Alert>
      )}

      {cardResult && (
        <Alert severity="info" sx={{ mb: 2 }} onClose={() => setCardResult(null)}>
          <AlertTitle>Company card</AlertTitle>
          <Typography variant="body2">{`Card number: ${cardResult.cardNumber || 'unknown'}`}</Typography>
          <Typography variant="body2">{`Company: ${cardResult.companyName || 'unknown'}`}</Typography>
          <Typography variant="body2">{`Issued by: ${cardResult.issuingAuthority || 'unknown'}`}</Typography>
          <Typography variant="body2">{`Valid until: ${tachoFormatDate(cardResult.expiryDate)}`}</Typography>
        </Alert>
      )}

      <Paper sx={{ p: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Tacho bridges
          </Typography>
          <Button size="small" onClick={load}>
            Refresh
          </Button>
          <Button size="small" variant="contained" onClick={() => setDialogOpen(true)}>
            Pair a bridge
          </Button>
        </Stack>

        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Reader</TableCell>
                <TableCell>Card</TableCell>
                <TableCell>Card expires</TableCell>
                <TableCell>Last seen</TableCell>
                <TableCell>Machine</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {bridges.map((bridge) => {
                const days = daysUntil(bridge.cardValidityTo);
                const paired = !!bridge.lastHeartbeat;
                return (
                  <TableRow key={bridge.id} hover>
                    <TableCell>
                      <Typography variant="body2">{bridge.name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {bridge.cardIdentifier ||
                          (paired ? 'card not identified' : 'waiting to pair')}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={bridge.status}
                        color={tachoStatusColour(bridge.status)}
                      />
                    </TableCell>
                    <TableCell>{bridge.readerStatus || '—'}</TableCell>
                    <TableCell>{bridge.cardStatus || '—'}</TableCell>
                    <TableCell>
                      <Typography
                        variant="caption"
                        color={
                          days !== null && days <= EXPIRY_WARNING_DAYS ? 'error' : 'text.secondary'
                        }
                      >
                        {tachoFormatDate(bridge.cardValidityTo)}
                      </Typography>
                    </TableCell>
                    <TableCell>{tachoFormatDate(bridge.lastHeartbeat)}</TableCell>
                    <TableCell>{bridge.hostname || '—'}</TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        disabled={bridge.status !== 'ONLINE'}
                        onClick={() => handleReadCard(bridge.id)}
                      >
                        Read card
                      </Button>
                      <Button size="small" color="error" onClick={() => handleDelete(bridge.id)}>
                        Remove
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {bridges.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} align="center">
                    <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                      No bridges yet. Pair one to make a company card available for remote
                      downloads.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Pair a tacho bridge</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Generates a single-use code. Enter it on the office machine that has the company card
            reader attached.
          </Typography>
          <TextField
            label="Bridge name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            fullWidth
            sx={{ mb: 2 }}
          />
          <TextField
            select
            label="Company"
            value={groupId}
            onChange={(event) => setGroupId(event.target.value)}
            fullWidth
            helperText="Which vehicles this card may authorise downloads for"
          >
            <MenuItem value="0">All vehicles on this server</MenuItem>
            {groups.map((group) => (
              <MenuItem key={group.id} value={String(group.id)}>
                {group.name}
              </MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleGenerate}>
            Generate code
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TachographBridgesTab;
