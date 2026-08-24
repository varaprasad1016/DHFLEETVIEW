/*
 * CMSV9 / 808gps platform client.
 *
 * Based on the platform's published open-API documentation (webApi.html):
 *   - All API calls are JSONP (callback=<name>) on the web server port
 *   - Login:  StandardApiAction_loginEx.action?account=..&password=..
 *       -> { result: 0, jsession: ".." }
 *   - Video search: StandardApiAction_queryAudioOrVideo.action
 *       ?jsession=..&devIdno=..&type=..&filetype=..&begintime=..&endtime=..&currentPage=1&pageRecords=..
 *   - Live video (HLS on media server port, default 6604):
 *       http://[mediaHost]:6604/hls/1_[devIdno]_[channel]_[streamType].m3u8?JSESSIONID=[jsession]
 *       (request type 1 = live; streamType 0 = main, 1 = sub)
 *   - Playback / download: media server URLs with DownType (5 = playback, 3 = download)
 *   - RTSP: rtsp://[mediaHost]:6604/[base64(jsession,type,devIdno,channel,byteType,rec,bl)]
 *   - RTMP: http://[mediaHost]:6604/rtmp/[ts]/[base64(jsession,1,devIdno,0,1,0,0)]
 */

const jsonp = (url, timeout = 20000) =>
  new Promise((resolve, reject) => {
    const callbackName = `cmsv9cb_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
    const script = document.createElement('script');
    const timer = setTimeout(() => {
      delete window[callbackName];
      script.remove();
      reject(new Error('Timeout'));
    }, timeout);
    window[callbackName] = (data) => {
      clearTimeout(timer);
      delete window[callbackName];
      script.remove();
      resolve(data);
    };
    script.onerror = () => {
      clearTimeout(timer);
      delete window[callbackName];
      script.remove();
      reject(new Error('Network error'));
    };
    script.src = `${url}${url.includes('?') ? '&' : '?'}callback=${callbackName}`;
    document.head.appendChild(script);
  });

const buildBase = (serverUrl) => {
  const url = new URL(serverUrl);
  return `${url.origin}${url.pathname.replace(/\/$/, '')}`;
};

export const cmsv9Login = async ({ serverUrl, account, password }) => {
  const base = buildBase(serverUrl);
  const data = await jsonp(
    `${base}/StandardApiAction_loginEx.action?account=${encodeURIComponent(account)}&password=${encodeURIComponent(password)}`,
  );
  if (data && data.result === 0 && data.jsession) {
    return data.jsession;
  }
  const message = { 1: 'Client does not exist', 2: 'Wrong password', 3: 'User deactivated', 4: 'User expired', 28: 'Already logged in elsewhere' }[data?.result];
  throw new Error(message || 'Login failed');
};

const getMediaOrigin = (serverUrl, mediaPort) => {
  const url = new URL(serverUrl);
  return `${url.protocol}//${url.hostname}${mediaPort ? `:${mediaPort}` : ''}`;
};

// Live HLS URL
export const cmsv9LiveHlsUrl = ({ serverUrl, mediaPort, jsession, deviceId, channel = 0, streamType = 0 }) =>
  `${getMediaOrigin(serverUrl, mediaPort)}/hls/1_${deviceId}_${channel}_${streamType}.m3u8?JSESSIONID=${jsession}`;

// Live RTSP URL (base64 of jsession,type,devIdno,channel,byteType,rec,bl)
export const cmsv9LiveRtspUrl = ({ serverUrl, mediaPort, jsession, deviceId, channel = 0 }) => {
  const param = btoa(`${jsession},3,${deviceId},${channel},1,0,0,0`);
  return `rtsp://${new URL(serverUrl).hostname}${mediaPort ? `:${mediaPort}` : ''}/${param}`;
};

// Live RTMP URL
export const cmsv9LiveRtmpUrl = ({ serverUrl, mediaPort, jsession, deviceId, channel = 0 }) => {
  const param = btoa(`${jsession},1,${deviceId},${channel},1,0,0`);
  return `${getMediaOrigin(serverUrl, mediaPort)}/rtmp/${Date.now()}/${param}`;
};

// Search recorded files. Returns the raw JSONP payload (list + pagination).
export const cmsv9Search = async ({ serverUrl, jsession, deviceId, channel = 0, beginTime, endTime, currentPage = 1, pageRecords = 50 }) => {
  const base = buildBase(serverUrl);
  const params = new URLSearchParams({
    jsession,
    devIdno: String(deviceId),
    type: '1',
    filetype: '2',
    begintime: beginTime,
    endtime: endTime,
    currentPage: String(currentPage),
    pageRecords: String(pageRecords),
  });
  return jsonp(`${base}/StandardApiAction_queryAudioOrVideo.action?${params.toString()}`);
};

// Build a playback URL for a recording (DownType=5)
export const cmsv9PlaybackUrl = ({
  serverUrl,
  mediaPort,
  jsession,
  deviceId,
  filePath,
  fileBeg,
  fileEnd,
  channel = 0,
}) => {
  const params = new URLSearchParams({
    DownType: '5',
    jsession,
    DevIDNO: String(deviceId),
    FILELOC: '1',
    FILESVR: '0',
    FILECHN: String(channel),
    FILEBEG: String(fileBeg || 0),
    FILEEND: String(fileEnd || 0),
    PLAYIFRM: '0',
    PLAYFILE: filePath,
    PLAYBEG: String(fileBeg || 0),
    PLAYEND: String(fileEnd || 0),
    PLAYCHN: String(channel),
  });
  return `${getMediaOrigin(serverUrl, mediaPort)}/3/5?${params.toString()}`;
};

// Build a download URL for a recording (DownType=3)
export const cmsv9DownloadUrl = ({
  serverUrl,
  mediaPort,
  jsession,
  deviceId,
  filePath,
  fileLength,
  saveName,
}) => {
  const params = new URLSearchParams({
    DownType: '3',
    jsession,
    DevIDNO: String(deviceId),
    FLENGTH: String(fileLength || 0),
    FOFFSET: '0',
    MTYPE: '1',
    FPATH: filePath,
    SAVENAME: saveName || filePath.split('/').pop(),
  });
  return `${getMediaOrigin(serverUrl, mediaPort)}/3/5?${params.toString()}`;
};
