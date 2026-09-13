/*
 * Mock CMSV9 / 808gps server for testing the ${title} video integration.
 *
 * Implements the platform's open-API surface decoded from webApi.html:
 *   - JSONP login:  /StandardApiAction_loginEx.action?account=..&password=..&callback=..
 *       -> { result: 0, jsession: "..." }
 *   - JSONP video search: /StandardApiAction_queryAudioOrVideo.action?jsession=..&devIdno=..&callback=..
 *       -> { result: 0, data: { list: [ { filePath, fileBeg, fileEnd, ... } ] } }
 *   - HLS live: /hls/1_<devIdno>_<channel>_<stream>.m3u8?JSESSIONID=..
 *       (serves a real playable HLS test stream so the player actually renders)
 *   - Playback/download URLs on the media port (returned by search)
 *
 * Run:  node preview/mock-cmsv9.mjs        (web API on 8605, media/HLS on 8604)
 * The web app is configured with cmsv9Url=http://localhost:8605, cmsv9MediaPort=8604.
 */

import http from 'http';

const WEB_PORT = 8605;
const MEDIA_PORT = 8604;
const JSESSION = 'cf6b70a3-c82b-4392-8ab6-bbddce336222';

// A real, playable HLS media playlist (public Mux test asset) the media server redirects to.
const HLS_MEDIA_PLAYLIST = 'https://test-streams.mux.dev/x36xhzz/url_6/193039199_mp4_h264_aac_hq_7.m3u8';

const searchDb = [
  {
    filePath: '/Record/H20240101-080000P2N2P0.264',
    fileBeg: 0,
    fileEnd: 1800000,
    startTime: '2024-01-01 08:00:00',
    fileLength: 52428800,
    saveName: 'H20240101-080000.264',
  },
  {
    filePath: '/Record/H20240101-090000P2N2P0.264',
    fileBeg: 0,
    fileEnd: 1800000,
    startTime: '2024-01-01 09:00:00',
    fileLength: 52428800,
    saveName: 'H20240101-090000.264',
  },
];

const jsonp = (res, callback, data) => {
  const body = `${callback}(${JSON.stringify(data)});`;
  res.writeHead(200, { 'Content-Type': 'application/javascript; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
  res.end(body);
};

const webServer = http.createServer((req, res) => {
  console.log('WEB REQ:', req.url.slice(0, 150));
  const url = new URL(req.url, `http://localhost:${WEB_PORT}`);
  const callback = url.searchParams.get('callback') || 'getData';

  if (url.pathname.endsWith('/StandardApiAction_loginEx.action')) {
    const account = url.searchParams.get('account');
    const password = url.searchParams.get('password');
    if (account === 'admin' && password === 'admin') {
      jsonp(res, callback, { result: 0, jsession: JSESSION });
    } else {
      jsonp(res, callback, { result: 2, message: 'Wrong password' });
    }
    return;
  }

  if (url.pathname.endsWith('/StandardApiAction_queryAudioOrVideo.action')) {
    const jsession = url.searchParams.get('jsession');
    if (jsession !== JSESSION) {
      jsonp(res, callback, { result: 5, message: 'Session not exist' });
      return;
    }
    const devIdno = url.searchParams.get('devIdno');
    const list = searchDb.map((item) => ({ ...item, devIdno }));
    jsonp(res, callback, { result: 0, data: { list, total: list.length } });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

const mediaServer = http.createServer((req, res) => {
  console.log('MEDIA REQ:', req.url.slice(0, 150));
  const url = new URL(req.url, `http://localhost:${MEDIA_PORT}`);

  if (url.pathname.match(/^\/hls\/.*\.m3u8$/)) {
    // Redirect to a real playable HLS media playlist (public test stream, CORS enabled)
    res.writeHead(302, {
      Location: HLS_MEDIA_PLAYLIST,
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-cache',
    });
    res.end();
    return;
  }

  if (url.pathname.startsWith('/3/5')) {
    // Playback or download URL (DownType=5 playback, 3 download) - redirect to the media playlist
    res.writeHead(302, {
      Location: HLS_MEDIA_PLAYLIST,
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-cache',
    });
    res.end();
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

webServer.listen(WEB_PORT, () => console.log(`Mock CMSV9 web API on http://localhost:${WEB_PORT}`));
mediaServer.listen(MEDIA_PORT, () => console.log(`Mock CMSV9 media/HLS on http://localhost:${MEDIA_PORT}`));
