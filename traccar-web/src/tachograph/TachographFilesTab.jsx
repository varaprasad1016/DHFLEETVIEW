import { Fragment, useEffect, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  Collapse,
  IconButton,
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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import { useCatch } from '../reactHelper';
import {
  tachoListFiles,
  tachoFileDownloadUrl,
  tachoListForwards,
  tachoRetryForward,
  tachoStatusColour,
  tachoFormatBytes,
  tachoFormatDate,
  tachoExplainError,
} from '../common/util/tachograph';

const TYPE_FILTERS = [
  { value: '', label: 'All types' },
  { value: 'VEHICLE', label: 'Vehicle unit' },
  { value: 'DRIVER', label: 'Driver card' },
];

/**
 * The stored DDD files, with what each one contains and where it has been sent.
 *
 * <p>Expanding a row shows its delivery record. That pairing is the point of the tab: the
 * question an operator is asked in an audit is not "did you download it" but "where did it go
 * and when", and the answer needs to be one click from the file itself.
 */
const TachographFilesTab = () => {
  const [files, setFiles] = useState([]);
  const [fileType, setFileType] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [forwards, setForwards] = useState([]);

  const load = useCatch(async (type) => {
    setFiles((await tachoListFiles({ type: type || undefined, limit: 100 })) || []);
  });

  useEffect(() => {
    load(fileType);
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, [fileType]);

  const toggle = useCatch(async (fileId) => {
    if (expanded === fileId) {
      setExpanded(null);
      return;
    }
    setExpanded(fileId);
    setForwards((await tachoListForwards({ fileId })) || []);
  });

  const handleRetry = useCatch(async (forwardId, fileId) => {
    await tachoRetryForward(forwardId);
    setForwards((await tachoListForwards({ fileId })) || []);
  });

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Stored files
        </Typography>
        <TextField
          select
          size="small"
          label="Type"
          value={fileType}
          onChange={(event) => setFileType(event.target.value)}
          sx={{ minWidth: 160 }}
        >
          {TYPE_FILTERS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {option.label}
            </MenuItem>
          ))}
        </TextField>
        <Button size="small" onClick={() => load(fileType)}>
          Refresh
        </Button>
      </Stack>

      <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell width={40} />
              <TableCell>File</TableCell>
              <TableCell>Vehicle</TableCell>
              <TableCell>Registration</TableCell>
              <TableCell>Period covered</TableCell>
              <TableCell>Size</TableCell>
              <TableCell>Downloaded</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {files.map((file) => (
              <Fragment key={file.id}>
                <TableRow hover>
                  <TableCell>
                    <IconButton size="small" onClick={() => toggle(file.id)}>
                      {expanded === file.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                    </IconButton>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{file.fileName}</Typography>
                    <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>
                      <Chip
                        size="small"
                        label={file.fileType === 'DRIVER' ? 'Driver' : 'Vehicle'}
                        variant="outlined"
                      />
                      {file.generation > 1 && (
                        <Chip size="small" label={`Gen ${file.generation}`} variant="outlined" />
                      )}
                      {file.clientType === 'SIMULATED' && (
                        <Chip size="small" label="Simulated" color="warning" variant="outlined" />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>{file.deviceName || file.deviceId}</TableCell>
                  <TableCell>{file.vehicleRegistration || '—'}</TableCell>
                  <TableCell>
                    {file.periodFrom || file.periodTo
                      ? `${tachoFormatDate(file.periodFrom)} – ${tachoFormatDate(file.periodTo)}`
                      : '—'}
                  </TableCell>
                  <TableCell>{tachoFormatBytes(file.fileSize)}</TableCell>
                  <TableCell>{tachoFormatDate(file.downloadedAt)}</TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      href={tachoFileDownloadUrl(file.id)}
                      target="_blank"
                      rel="noopener"
                    >
                      Download
                    </Button>
                  </TableCell>
                </TableRow>

                <TableRow>
                  <TableCell colSpan={8} sx={{ py: 0, border: 0 }}>
                    <Collapse in={expanded === file.id} unmountOnExit>
                      <Box sx={{ py: 2, pl: 6 }}>
                        <Typography variant="subtitle2" gutterBottom>
                          File details
                        </Typography>
                        <Typography variant="caption" display="block" color="text.secondary">
                          {`Vehicle identification number: ${file.vehicleIdentification || 'not recorded'}`}
                        </Typography>
                        <Typography variant="caption" display="block" color="text.secondary">
                          {`Vehicle unit serial: ${file.vehicleUnitSerial || 'not recorded'}`}
                        </Typography>
                        <Typography variant="caption" display="block" color="text.secondary">
                          {`Data blocks: ${file.blocks || 'not recorded'}`}
                        </Typography>
                        <Tooltip title="Digest of the bytes exactly as the vehicle produced them">
                          <Typography
                            variant="caption"
                            display="block"
                            color="text.secondary"
                            sx={{ wordBreak: 'break-all' }}
                          >
                            {`SHA-256: ${file.sha256 || '—'}`}
                          </Typography>
                        </Tooltip>
                        {file.validationMessage && (
                          <Typography variant="caption" display="block" color="warning.main">
                            {file.validationMessage}
                          </Typography>
                        )}

                        <Typography variant="subtitle2" sx={{ mt: 2 }} gutterBottom>
                          Delivery to analysis bureaux
                        </Typography>
                        {forwards.length === 0 && (
                          <Typography variant="caption" color="text.secondary">
                            This file has not been queued for delivery.
                          </Typography>
                        )}
                        {forwards.map((forward) => (
                          <Stack
                            key={forward.id}
                            direction="row"
                            spacing={1}
                            alignItems="center"
                            sx={{ mb: 0.5 }}
                          >
                            <Chip
                              size="small"
                              label={forward.status}
                              color={tachoStatusColour(forward.status)}
                            />
                            <Typography variant="caption">
                              {forward.remoteName || file.fileName}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {forward.completedAt
                                ? tachoFormatDate(forward.completedAt)
                                : `attempt ${forward.attempts}`}
                            </Typography>
                            {forward.errorCode && (
                              <Typography variant="caption" color="error">
                                {tachoExplainError(forward.errorCode) || forward.errorMessage}
                              </Typography>
                            )}
                            {forward.status === 'FAILED' && (
                              <Button size="small" onClick={() => handleRetry(forward.id, file.id)}>
                                Retry
                              </Button>
                            )}
                          </Stack>
                        ))}
                      </Box>
                    </Collapse>
                  </TableCell>
                </TableRow>
              </Fragment>
            ))}
            {files.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} align="center">
                  <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                    No files have been downloaded yet.
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

export default TachographFilesTab;
