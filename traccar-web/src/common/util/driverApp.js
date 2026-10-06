// Drivers sign in on the normal login screen with their name (or driver ID) and
// PIN, and land in the driver screens served by the tacho server. The session
// keys match the ones the driver screens read (`drv:` prefix, JSON values).
const TOKEN_KEY = 'drv:token';
const NAME_KEY = 'drv:driver';
const LAST_NAME_KEY = 'drv:lastName';
export const DRIVER_HOME = '/tacho/driver#/live';
const ACCOUNTS_API = '/tacho/api/driver-accounts';

const readJson = (key) => {
  try {
    return JSON.parse(window.localStorage.getItem(key) || 'null');
  } catch {
    return null;
  }
};

export const hasDriverSession = () => typeof readJson(TOKEN_KEY) === 'string';

export const openDriverHome = () => window.location.replace(DRIVER_HOME);

export const looksLikeEmail = (value) => /\S+@\S+/.test(value || '');

const readDetail = async (response) => {
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') return { message: body.detail, code: null };
    return { message: body.detail?.message || null, code: body.detail?.error || null };
  } catch {
    return { message: null, code: null };
  }
};

const detailMessage = async (response) => (await readDetail(response)).message;

// { ok: true } when signed in as a driver.
// { ok: false, fallback: true } when this isn't a driver login (try the normal login).
// { ok: false, message } when it is a driver but sign-in was refused (locked, disabled...).
export const tryDriverLogin = async (identifier, pin) => {
  let response;
  try {
    response = await fetch('/tacho/api/driver/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: identifier.trim(), pin: pin.trim() }),
    });
  } catch {
    return { ok: false, fallback: true };
  }
  if (response.ok) {
    const { token, driver } = await response.json();
    window.localStorage.setItem(TOKEN_KEY, JSON.stringify(token));
    window.localStorage.setItem(NAME_KEY, JSON.stringify(driver.name));
    window.localStorage.setItem(LAST_NAME_KEY, JSON.stringify(driver.name));
    return { ok: true };
  }
  const message = await detailMessage(response);
  if (response.status === 401 && message && message.startsWith('More than one')) {
    return { ok: false, message };
  }
  if (response.status === 403 || response.status === 429) {
    return { ok: false, message };
  }
  return { ok: false, fallback: true, message };
};

const accountsRequestAt = async (url, init) => {
  const response = await fetch(url, init);
  if (!response.ok) {
    const { message, code } = await readDetail(response);
    const error = new Error(message || `Driver app service error (${response.status})`);
    error.code = code;
    throw error;
  }
  return response.json();
};

const accountsRequest = (path, init) => accountsRequestAt(`${ACCOUNTS_API}${path}`, init);

export const getDriverAppAccount = (driverId) => accountsRequest(`/traccar/${driverId}`);

export const listDriverAppAccounts = () => accountsRequest('/traccar');

export const saveDriverAppAccount = (driverId, { pin, active }) =>
  accountsRequest(`/traccar/${driverId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin: pin || null, active }),
  });

// Compliance modules this user may see (set per user by the super administrator).
// Resolves to { enabled: { key: bool }, can_manage, modules } or null when the
// tacho service can't say.
export const getModuleAccess = async () => {
  try {
    const response = await fetch('/tacho/api/modules');
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
};

export const getEnabledModules = async () => (await getModuleAccess())?.enabled || null;

// Super administrator: another user's modules.
export const getUserModules = (userId) => accountsRequestAt(`/tacho/api/modules/users/${userId}`);

export const saveUserModules = (userId, enabled) =>
  accountsRequestAt(`/tacho/api/modules/users/${userId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(enabled),
  });

export const syncDriverAppAccounts = () =>
  accountsRequest('/traccar-sync', { method: 'POST' }).catch(() => null);
