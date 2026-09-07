/*
 * Tachograph API client.
 *
 * Every call goes through `request`, which turns a failure response into an Error carrying the
 * server's own message. That matters here more than in most places: a tachograph download fails
 * for operational reasons an operator can act on — the card is out, the vehicle is offline, the
 * bureau refused the credential — and replacing those with a generic "request failed" would hide
 * exactly the information needed to fix it.
 */

const request = async (url, options = {}) => {
  const response = await fetch(url, {
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const text = await response.text();
      if (text) {
        try {
          const parsed = JSON.parse(text);
          message = parsed.message || parsed.error || text;
        } catch {
          message = text;
        }
      }
    } catch {
      // Keep the status line when the body cannot be read.
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }
  const text = await response.text();
  return text ? JSON.parse(text) : null;
};

const query = (params) => {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
};

// Overview -------------------------------------------------------------------

export const tachoGetSummary = () => request('/api/tachograph/summary');

// Per-vehicle configuration --------------------------------------------------

export const tachoGetConfiguration = (deviceId) =>
  request(`/api/tachograph/configuration/${deviceId}`);

export const tachoSaveConfiguration = (deviceId, data) =>
  request(`/api/tachograph/configuration/${deviceId}`, {
    method: 'POST',
    body: JSON.stringify(data),
  });

// Downloads ------------------------------------------------------------------

export const tachoRequestDownload = (deviceId, downloadType, range = {}) =>
  request('/api/tachograph/download', {
    method: 'POST',
    body: JSON.stringify({ deviceId, downloadType, ...range }),
  });

export const tachoListDownloads = (params) => request(`/api/tachograph/downloads${query(params)}`);

export const tachoGetDownload = (id) => request(`/api/tachograph/downloads/${id}`);

export const tachoCancelDownload = (id) =>
  request(`/api/tachograph/downloads/${id}/cancel`, { method: 'POST' });

// Files ----------------------------------------------------------------------

export const tachoListFiles = (params) => request(`/api/tachograph/files${query(params)}`);

export const tachoFileDownloadUrl = (id) => `/api/tachograph/files/${id}/download`;

export const tachoDeleteFile = (id) => request(`/api/tachograph/files/${id}`, { method: 'DELETE' });

// Bridges --------------------------------------------------------------------

export const tachoListBridges = () => request('/api/tachograph/bridges');

export const tachoGeneratePairingCode = (groupId, name) =>
  request('/api/tachograph/bridges/pairing-code', {
    method: 'POST',
    body: JSON.stringify({ groupId, name }),
  });

export const tachoDeleteBridge = (id) =>
  request(`/api/tachograph/bridges/${id}`, { method: 'DELETE' });

export const tachoReadCard = (id) =>
  request(`/api/tachograph/bridges/${id}/read-card`, { method: 'POST' });

// Delivery to analysis bureaux ------------------------------------------------

export const tachoListTargets = () => request('/api/tachograph/targets');

export const tachoCreateTarget = (target) =>
  request('/api/tachograph/targets', {
    method: 'POST',
    body: JSON.stringify(target),
  });

export const tachoUpdateTarget = (id, target) =>
  request(`/api/tachograph/targets/${id}`, {
    method: 'PUT',
    body: JSON.stringify(target),
  });

export const tachoDeleteTarget = (id) =>
  request(`/api/tachograph/targets/${id}`, { method: 'DELETE' });

export const tachoTestTarget = (id) =>
  request(`/api/tachograph/targets/${id}/test`, { method: 'POST' });

export const tachoListForwards = (params) => request(`/api/tachograph/forwards${query(params)}`);

export const tachoRetryForward = (id) =>
  request(`/api/tachograph/forwards/${id}/retry`, { method: 'POST' });

// Audit ----------------------------------------------------------------------

export const tachoListAudit = (params) => request(`/api/tachograph/audit${query(params)}`);

// Presentation helpers --------------------------------------------------------

/** Job statuses that mean work is still in progress. */
export const TACHO_ACTIVE_STATUSES = [
  'QUEUED',
  'WAITING_FOR_DEVICE',
  'WAITING_FOR_BRIDGE',
  'REQUESTING',
  'DOWNLOADING',
  'PROCESSING',
];

export const isTachoJobActive = (status) => TACHO_ACTIVE_STATUSES.includes(status);

/** Maps a job or delivery status onto a MUI chip colour. */
export const tachoStatusColour = (status) => {
  switch (status) {
    case 'COMPLETED':
    case 'DELIVERED':
    case 'ONLINE':
    case 'OK':
      return 'success';
    case 'FAILED':
      return 'error';
    case 'CANCELLED':
      return 'default';
    case 'DOWNLOADING':
    case 'PROCESSING':
    case 'REQUESTING':
    case 'SENDING':
      return 'info';
    default:
      return 'warning';
  }
};

/**
 * Turns an error code from the server into something an operator can act on. The raw codes are
 * stable identifiers meant for logs; these are the sentences that tell somebody what to go and do.
 */
export const tachoExplainError = (code) => {
  switch (code) {
    case 'TACHO_DEVICE_OFFLINE':
      return 'The vehicle was not reachable. It will be retried automatically when it reconnects.';
    case 'TACHO_DOWNLOAD_TIMEOUT':
      return 'The vehicle stopped responding part way through. This is usually a weak mobile signal.';
    case 'TACHO_AUTHENTICATION_FAILED':
      return 'The company card did not authenticate. Check it is properly seated in the reader.';
    case 'TACHO_CARD_UNAVAILABLE':
      return 'No company card was readable. Check the card is in the reader and the bridge is running.';
    case 'TACHO_CARD_LOCKED':
      return 'The company card is expired or locked and must be replaced before downloads can run.';
    case 'TACHO_BRIDGE_UNAVAILABLE':
      return 'No tacho bridge is online. Start the bridge application on the office machine.';
    case 'TACHO_PROTOCOL_ERROR':
      return 'The tachograph did not follow the download protocol. Retry, then check the vehicle wiring.';
    case 'TACHO_INVALID_FILE':
      return 'The data received was not a usable file, so it was not stored.';
    case 'TACHO_STORAGE_ERROR':
      return 'The file could not be written to disk. Check the server has free space.';
    case 'TACHO_ALREADY_RUNNING':
      return 'A download of this type is already running for this vehicle.';
    case 'TACHO_PROTOCOL_SPEC_MISSING':
      return 'No tachograph transport is configured. Set tacho.tunnel.port on the server.';
    case 'TACHO_FORWARD_AUTH':
      return 'The analysis bureau refused the stored credential. Re-enter it and test the connection.';
    case 'TACHO_FORWARD_HOST_KEY':
      return 'The bureau server presented an unexpected host key, so nothing was sent.';
    case 'TACHO_FORWARD_CONNECT':
      return 'The bureau could not be reached. Delivery will be retried automatically.';
    case 'TACHO_FORWARD_REJECTED':
      return 'The bureau rejected the file. Check the account and the expected file naming.';
    case 'TACHO_FORWARD_CONFIGURATION':
      return 'The delivery target is misconfigured. Check its host, path and credential.';
    default:
      return null;
  }
};

/** Human-readable byte size. */
export const tachoFormatBytes = (bytes) => {
  if (bytes === null || bytes === undefined) {
    return '';
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/** Short local date and time, or an em dash when the value is absent. */
export const tachoFormatDate = (value) => {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
};
