/*
 * Verify: device form shows "Camera device" checkbox -> sets cmsv9DeviceId,
 * and the video page + grid work end to end.
 * Usage: CHROME=<chrome.exe> node preview/test-camera-checkbox.mjs
 */
import { spawn } from 'child_process';
import { mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const chrome = process.env.CHROME || '/c/Program Files/Google/Chrome/Application/chrome.exe';
const port = 9337;
const profile = mkdtempSync(join(tmpdir(), 'cmsv9-cb-'));

const chromeProc = spawn(chrome, [
  '--headless',
  '--disable-gpu',
  '--autoplay-policy=no-user-gesture-required',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  '--no-first-run',
  'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getJson(url) {
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return res.json();
    } catch (e) {}
    await sleep(500);
  }
  throw new Error(`Could not reach ${url}`);
}

async function main() {
  await sleep(2000);
  const targets = await getJson(`http://127.0.0.1:${port}/json`);
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  };
  await new Promise((resolve) => (ws.onopen = resolve));

  // Login
  await send('Page.navigate', { url: 'http://localhost:8082/login' });
  await sleep(2500);
  await send('Runtime.evaluate', {
    expression: `fetch('/api/session', { method: 'POST', body: new URLSearchParams({ email: 'video-test@dhgroup.local', password: 'VideoTest123!' }) })`,
    awaitPromise: true,
  });
  console.log('1. logged in');

  // 2. Check the device form has the Camera device checkbox
  await send('Page.navigate', { url: 'http://localhost:8082/settings/device/3' });
  await sleep(4000);
  const form = await send('Runtime.evaluate', {
    expression: `(() => {
      const body = document.body.innerText;
      return JSON.stringify({
        hasCameraCheckbox: body.includes('Camera device'),
        hasDeviceIdField: body.includes('CMSV9 Device ID'),
      });
    })()`,
    returnByValue: true,
  });
  console.log('2. device form:', form.result.value);

  // 3. Video page: live playback
  await send('Page.navigate', { url: 'http://localhost:8082/cmsv9-video?deviceId=3' });
  await sleep(5000);
  for (let i = 0; i < 20; i++) {
    const r = await send('Runtime.evaluate', {
      expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Play'); return b ? !b.disabled : false; })()`,
      returnByValue: true,
    });
    if (r.result.value) break;
    await sleep(500);
  }
  await send('Runtime.evaluate', {
    expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Play'); if (b) b.click(); })()`,
    returnByValue: true,
  });
  await sleep(7000);
  const live = await send('Runtime.evaluate', {
    expression: `(() => { const v = document.querySelector('video'); return JSON.stringify({ playing: !!v && !v.paused && v.videoWidth > 0, w: v?.videoWidth, h: v?.videoHeight }); })()`,
    returnByValue: true,
  });
  console.log('3. live video:', live.result.value);

  // 4. Multi grid
  await send('Runtime.evaluate', {
    expression: `(() => { const tabs = [...document.querySelectorAll('[role="tab"]')]; if (tabs[1]) tabs[1].click(); })()`,
    returnByValue: true,
  });
  await sleep(800);
  await send('Runtime.evaluate', {
    expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('Play all')); if (b) b.click(); })()`,
    returnByValue: true,
  });
  await sleep(10000);
  const grid = await send('Runtime.evaluate', {
    expression: `(() => { const vids = [...document.querySelectorAll('video')]; return JSON.stringify({ count: vids.length, playing: vids.filter((v) => !v.paused && v.videoWidth > 0).length }); })()`,
    returnByValue: true,
  });
  console.log('4. grid:', grid.result.value);

  ws.close();
  chromeProc.kill();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  chromeProc.kill();
  process.exit(1);
});
