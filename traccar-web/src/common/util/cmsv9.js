/*
 * CNMS video platform client.
 *
 * Uses official CNMS Open Platform API via the Traccar backend proxy.
 *   - Config:  GET  /api/cmsv9/config
 *   - Live:    POST /api/cmsv9/live/{deviceId}/{channel}  → returns {flvUrl, rtmpUrl}
 *   - Stop:    POST /api/cmsv9/stop/{deviceId}/{channel}
 *   - Playback: POST /api/cmsv9/playback/{deviceId}/{channel}  {startTime, endTime}
 *   - History: GET  /api/cmsv9/history/{deviceId}/{channel}?from=&to=
 *   - Search:  GET  /api/cmsv9/search?deviceId=&channel=&from=&to=&type=
 */

export const cmsv9GetConfig = async () => {
  const response = await fetch('api/cmsv9/config');
  if (!response.ok) throw new Error('Failed to fetch CMSV9 config');
  return response.json();
};

export const cmsv9StartLive = async (deviceId, channel) => {
  const response = await fetch(`api/cmsv9/live/${deviceId}/${channel}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error('Failed to start live stream');
  return response.json();
};

export const cmsv9StopLive = async (deviceId, channel) => {
  const response = await fetch(`api/cmsv9/stop/${deviceId}/${channel}`, {
    method: 'POST',
  });
  if (!response.ok) return false;
  const data = await response.json();
  return data.errCode === 0;
};

export const cmsv9StartPlayback = async (deviceId, channel, startTime, endTime) => {
  const response = await fetch(`api/cmsv9/playback/${deviceId}/${channel}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ startTime, endTime }),
  });
  if (!response.ok) throw new Error('Failed to start playback');
  return response.json();
};

export const cmsv9Search = async ({ deviceId, channel, from, to, type = '1' }) => {
  const params = new URLSearchParams({
    deviceId: String(deviceId),
    channel: String(channel),
    from,
    to,
    type,
  });
  const response = await fetch(`api/cmsv9/search?${params.toString()}`);
  if (!response.ok) throw new Error('Search failed');
  return response.json();
};

export const cmsv9History = async (deviceId, channel, from, to) => {
  const params = new URLSearchParams({ from, to });
  const response = await fetch(`api/cmsv9/history/${deviceId}/${channel}?${params.toString()}`);
  if (!response.ok) throw new Error('History query failed');
  return response.json();
};
