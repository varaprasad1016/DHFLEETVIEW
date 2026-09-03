import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
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
  tachoListTargets,
  tachoCreateTarget,
  tachoUpdateTarget,
  tachoDeleteTarget,
  tachoTestTarget,
  tachoListForwards,
  tachoRetryForward,
  tachoStatusColour,
  tachoFormatDate,
  tachoExplainError,
} from '../common/util/tachograph';

const emptyTarget = {
  name: '',
  provider: 'CONVEY',
  transport: 'SFTP',
  enabled: true,
  groupId: 0,
  host: '',
  port: 22,
  username: '',
  secretInput: '',
  remotePath: '',
  url: '',
  hostKey: '',
  fileNamePattern: '',
  forwardDriver: true,
  forwardVehicle: true,
};

/**
 * Where finished DDD files are sent, and whether they got there.
 *
 * <p>A credential that has been saved is never sent back to the browser, so the form shows
 * whether one is stored rather than its value, and leaving the field blank on an edit keeps the
 * existing one. That avoids the trap where changing a schedule silently wipes a password.
 */
const TachographDeliveryTab = () => {
  const groups = useSelector((state) => Object.values(state.groups.items));

  const [targets, setTargets] = useState([]);
  const [forwards, setForwards] = useState([]);
  const [editing, setEditing] = useState(null);
  const [testResult, setTestResult] = useState(null);

  const load = useCatch(async () => {
    setTargets((await tachoListTargets()) || []);
    setForwards((await tachoListForwards({ limit: 50 })) || []);
  });

  useEffect(() => {
    load();
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, []);

  const handleSave = useCatch(async () => {
    if (editing.id) {
      await tachoUpdateTarget(editing.id, editing);
    } else {
      await tachoCreateTarget(editing);
    }
    setEditing(null);
    load();
  });

  const handleDelete = useCatch(async (id) => {
    await tachoDeleteTarget(id);
    load();
  });

  const handleTest = useCatch(async (id) => {
    setTestResult(await tachoTestTarget(id));
    load();
  });

  const handleRetry = useCatch(async (id) => {
    await tachoRetryForward(id);
    load();
  });

  const update = (changes) => setEditing((current) => ({ ...current, ...changes }));
  const isSftp = editing?.transport === 'SFTP';

  return (
    <Box>
      {testResult && (
        <Alert
          severity={testResult.success ? 'success' : 'error'}
          sx={{ mb: 2 }}
          onClose={() => setTestResult(null)}
        >
          {testResult.success
            ? 'Connection succeeded. Files will be delivered to this target.'
            : tachoExplainError(testResult.errorCode) || testResult.message}
        </Alert>
      )}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Analysis bureaux
          </Typography>
          <Button size="small" onClick={load}>
            Refresh
          </Button>
          <Button size="small" variant="contained" onClick={() => setEditing({ ...emptyTarget })}>
            Add target
          </Button>
        </Stack>

        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Transport</TableCell>
                <TableCell>Destination</TableCell>
                <TableCell>Sends</TableCell>
                <TableCell>Last result</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {targets.map((target) => (
                <TableRow key={target.id} hover>
                  <TableCell>
                    <Typography variant="body2">{target.name}</Typography>
                    <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>
                      <Chip size="small" variant="outlined" label={target.provider} />
                      {!target.enabled && <Chip size="small" color="default" label="Disabled" />}
                      {!target.hasSecret && (
                        <Chip size="small" color="warning" label="No credential" />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>{target.transport}</TableCell>
                  <TableCell sx={{ maxWidth: 280, wordBreak: 'break-all' }}>
                    {target.transport === 'SFTP'
                      ? `${target.username || '?'}@${target.host || '?'}:${target.port || 22}${target.remotePath || '/'}`
                      : target.url}
                  </TableCell>
                  <TableCell>
                    {[target.forwardVehicle && 'Vehicle', target.forwardDriver && 'Driver']
                      .filter(Boolean)
                      .join(', ') || 'Nothing'}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={target.lastStatus || 'UNTESTED'}
                      color={tachoStatusColour(target.lastStatus)}
                    />
                    <Typography variant="caption" display="block" color="text.secondary">
                      {tachoFormatDate(target.lastAttemptAt)}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => handleTest(target.id)}>
                      Test
                    </Button>
                    <Button size="small" onClick={() => setEditing({ ...target, secretInput: '' })}>
                      Edit
                    </Button>
                    <Button size="small" color="error" onClick={() => handleDelete(target.id)}>
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {targets.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                      No delivery targets. Add one so downloaded files reach your analysis bureau
                      automatically.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>
          Recent deliveries
        </Typography>
        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>File</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Attempts</TableCell>
                <TableCell>Completed</TableCell>
                <TableCell>Result</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {forwards.map((forward) => (
                <TableRow key={forward.id} hover>
                  <TableCell>{forward.remoteName || forward.fileId}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={forward.status}
                      color={tachoStatusColour(forward.status)}
                    />
                  </TableCell>
                  <TableCell>{forward.attempts}</TableCell>
                  <TableCell>{tachoFormatDate(forward.completedAt)}</TableCell>
                  <TableCell sx={{ maxWidth: 320 }}>
                    <Typography
                      variant="caption"
                      color={forward.errorCode ? 'error' : 'text.secondary'}
                    >
                      {forward.errorCode
                        ? tachoExplainError(forward.errorCode) || forward.errorMessage
                        : '—'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    {forward.status === 'FAILED' && (
                      <Button size="small" onClick={() => handleRetry(forward.id)}>
                        Retry
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {forwards.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                      Nothing has been delivered yet.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Dialog open={!!editing} onClose={() => setEditing(null)} fullWidth maxWidth="sm">
        <DialogTitle>{editing?.id ? 'Edit delivery target' : 'Add delivery target'}</DialogTitle>
        <DialogContent>
          {editing && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                label="Name"
                value={editing.name}
                onChange={(event) => update({ name: event.target.value })}
                fullWidth
              />
              <TextField
                select
                label="Bureau"
                value={editing.provider}
                onChange={(event) => update({ provider: event.target.value })}
              >
                <MenuItem value="CONVEY">Convey Reporting</MenuItem>
                <MenuItem value="GENERIC">Other bureau or archive</MenuItem>
              </TextField>
              <TextField
                select
                label="Transport"
                value={editing.transport}
                onChange={(event) => update({ transport: event.target.value })}
                helperText="Most bureaux accept files over SFTP"
              >
                <MenuItem value="SFTP">SFTP</MenuItem>
                <MenuItem value="HTTPS">HTTPS upload</MenuItem>
              </TextField>
              <TextField
                select
                label="Company"
                value={String(editing.groupId ?? 0)}
                onChange={(event) => update({ groupId: Number(event.target.value) })}
                helperText="Which vehicles' files go to this target"
              >
                <MenuItem value="0">All vehicles on this server</MenuItem>
                {groups.map((group) => (
                  <MenuItem key={group.id} value={String(group.id)}>
                    {group.name}
                  </MenuItem>
                ))}
              </TextField>

              <Divider />

              {isSftp ? (
                <>
                  <TextField
                    label="Host"
                    value={editing.host || ''}
                    onChange={(event) => update({ host: event.target.value })}
                  />
                  <TextField
                    label="Port"
                    type="number"
                    value={editing.port || 22}
                    onChange={(event) => update({ port: Number(event.target.value) })}
                  />
                  <TextField
                    label="Remote directory"
                    value={editing.remotePath || ''}
                    onChange={(event) => update({ remotePath: event.target.value })}
                    helperText="Created if it does not exist"
                  />
                  <TextField
                    label="Expected host key"
                    value={editing.hostKey || ''}
                    onChange={(event) => update({ hostKey: event.target.value })}
                    multiline
                    minRows={2}
                    helperText="Paste the bureau's SSH host key. Without it, any server answering that address is trusted."
                  />
                </>
              ) : (
                <TextField
                  label="Upload URL"
                  value={editing.url || ''}
                  onChange={(event) => update({ url: event.target.value })}
                  helperText="Must be https"
                />
              )}

              <TextField
                label="Username"
                value={editing.username || ''}
                onChange={(event) => update({ username: event.target.value })}
                helperText={isSftp ? '' : 'Leave blank to send the credential as a bearer token'}
              />
              <TextField
                label={editing.hasSecret ? 'Replace password or key' : 'Password or private key'}
                value={editing.secretInput || ''}
                onChange={(event) => update({ secretInput: event.target.value })}
                type={editing.secretInput?.includes('BEGIN') ? 'text' : 'password'}
                multiline={editing.secretInput?.includes('BEGIN')}
                minRows={editing.secretInput?.includes('BEGIN') ? 4 : 1}
                helperText={
                  editing.hasSecret
                    ? 'A credential is stored. Leave blank to keep it.'
                    : 'A password, or paste a private key'
                }
              />

              <Divider />

              <TextField
                label="Remote file name pattern"
                value={editing.fileNamePattern || ''}
                onChange={(event) => update({ fileNamePattern: event.target.value })}
                helperText="Blank keeps the original name. Supports {name} {device} {registration} {vin} {card} {type} {timestamp}"
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={!!editing.forwardVehicle}
                    onChange={(event) => update({ forwardVehicle: event.target.checked })}
                  />
                }
                label="Send vehicle unit files"
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={!!editing.forwardDriver}
                    onChange={(event) => update({ forwardDriver: event.target.checked })}
                  />
                }
                label="Send driver card files"
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={!!editing.enabled}
                    onChange={(event) => update({ enabled: event.target.checked })}
                  />
                }
                label="Target enabled"
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleSave}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default TachographDeliveryTab;
