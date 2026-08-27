/*
 * Tachograph frontend API client.
 */
export const tachoGetConfiguration = async (deviceId) => {
  const response = await fetch(`/api/tachograph/configuration/${deviceId}`);
  if (!response.ok) throw new Error('Failed to fetch tachograph configuration');
  return response.json();
};

export const tachoSaveConfiguration = async (deviceId, data) => {
  const response = await fetch(`/api/tachograph/configuration/${deviceId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to save tachograph configuration');
  return response.json();
};

export const tachoRequestDownload = async (deviceId, downloadType) => {
  const response = await fetch('/api/tachograph/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deviceId, downloadType }),
  });
  if (response.status === 202 || response.ok) return response.json();
  const text = await response.text();
  throw new Error(text || 'Failed to request download');
};

export const tachoListDownloads = async (params = {}) => {
  const query = new URLSearchParams();
  if (params.deviceId) query.set('deviceId', String(params.deviceId));
  if (params.status) query.set('status', params.status);
  if (params.limit) query.set('limit', String(params.limit));
  const response = await fetch(`/api/tachograph/downloads?${query.toString()}`);
  if (!response.ok) throw new Error('Failed to list downloads');
  return response.json();
};

export const tachoGetDownload = async (id) => {
  const response = await fetch(`/api/tachograph/downloads/${id}`);
  if (!response.ok) throw new Error('Failed to fetch download');
  return response.json();
};

export const tachoCancelDownload = async (id) => {
  const response = await fetch(`/api/tachograph/downloads/${id}/cancel`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to cancel download');
  return response.json();
};

export const tachoListFiles = async (params = {}) => {
  const query = new URLSearchParams();
  if (params.deviceId) query.set('deviceId', String(params.deviceId));
  if (params.limit) query.set('limit', String(params.limit));
  const response = await fetch(`/api/tachograph/files?${query.toString()}`);
  if (!response.ok) throw new Error('Failed to list files');
  return response.json();
};

export const tachoListBridges = async () => {
  const response = await fetch('/api/tachograph/bridges');
  if (!response.ok) throw new Error('Failed to list bridges');
  return response.json();
};

export const tachoGeneratePairingCode = async (groupId, name) => {
  const response = await fetch('/api/tachograph/bridges/pairing-code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ groupId, name }),
  });
  if (!response.ok) throw new Error('Failed to generate pairing code');
  return response.json();
};
