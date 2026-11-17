/**
 * Shift and job management API client.
 *
 * Provides clock in/out with photo capture, break toggling,
 * and job accept/deny/complete operations.
 */

const BASE = '/api/shifts';

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

// --- Clock In/Out ---

export const clockIn = (data) => api('POST', '/clock-in', data);
export const clockOut = (shiftId, data) => api('POST', `/${shiftId}/clock-out`, data);
export const toggleBreak = (shiftId, breakType) =>
  api('POST', `/${shiftId}/break`, { break_type: breakType });

// --- Shift queries ---

export const activeShifts = () => api('GET', '/active');
export const shiftHistory = (driverName) => {
  const params = driverName ? `?driver_name=${encodeURIComponent(driverName)}` : '';
  return api('GET', `/history${params}`);
};
export const getShift = (shiftId) => api('GET', `/${shiftId}`);

// --- Jobs ---

export const createJob = (data) => api('POST', '/jobs', data);
export const listJobs = (status, driverName) => {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (driverName) params.set('driver_name', driverName);
  const qs = params.toString();
  return api('GET', `/jobs${qs ? '?' + qs : ''}`);
};
export const getJob = (jobId) => api('GET', `/jobs/${jobId}`);
export const acceptJob = (jobId) => api('POST', `/jobs/${jobId}/accept`);
export const denyJob = (jobId, reason) => api('POST', `/jobs/${jobId}/deny`, { reason });
export const completeJob = (jobId) => api('POST', `/jobs/${jobId}/complete`);
export const cancelJob = (jobId) => api('POST', `/jobs/${jobId}/cancel`);
