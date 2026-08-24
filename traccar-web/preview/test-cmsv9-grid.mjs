/*
 * Test the CMSV9 multi-camera grid view: all channels play at once.
 * Usage: CHROME=<chrome.exe> node preview/test-cmsv9-grid.mjs
 */
import { spawn } from 'child_process';
import { mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const chrome = process.env.CHROME || '/c/Program Files/Google/Chrome/Application/chrome.exe';
const port = 9336;
const profile = mkdtempSync(join(tmpdir(), 'cmsv9-grid-'));

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
  const consoleLogs = [];
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.method === 'Runtime.consoleAPICalled') {
      consoleLogs.push(msg.params.args.map((a) => a.value || a.description).join(' '));
    }
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  };
  await new Promise((resolve) => (ws.onopen = resolve));
  await send('Runtime.enable');

  // Login
  await send('Page.navigate', { url: 'http://localhost:8082/login' });
  await sleep(2500);
  await send('Runtime.evaluate', {
    expression: `fetch('/api/session', { method: 'POST', body: new URLSearchParams({ email: 'video-test@dhgroup.local', password: 'VideoTest123!' }) })`,
    awaitPromise: true,
  });
  console.log('1. logged in');

  // Video page
  await send('Page.navigate', { url: 'http://localhost:8082/cmsv9-video?deviceId=1' });
  await sleep(5000);

  // Wait for session
  for (let i = 0; i < 20; i++) {
    const r = await send('Runtime.evaluate', {
      expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Play'); return b ? !b.disabled : false; })()`,
      returnByValue: true,
    });
    if (r.result.value) break;
    await sleep(500);
  }

  // Switch to Multi tab (index 1)
  await send('Runtime.evaluate', {
    expression: `(() => { const tabs = [...document.querySelectorAll('[role="tab"]')]; if (tabs[1]) tabs[1].click(); return 'tab clicked'; })()`,
    returnByValue: true,
  });
  await sleep(1000);

  // Click "Play all cameras"
  const playAll = await send('Runtime.evaluate', {
    expression: `(() => {
      const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('Play all'));
      if (!b) return 'no button: ' + document.body.innerText.slice(0, 150);
      if (b.disabled) return 'disabled';
      b.click();
      return 'clicked';
    })()`,
    returnByValue: true,
  });
  console.log('2. play all:', playAll.result.value);
  await sleep(10000);

  const state = await send('Runtime.evaluate', {
    expression: `(() => {
      const vids = [...document.querySelectorAll('video')];
      return JSON.stringify({
        videoCount: vids.length,
        playing: vids.filter((v) => !v.paused && v.videoWidth > 0).length,
        dimensions: vids.map((v) => (v.videoWidth ? v.videoWidth + 'x' + v.videoHeight : 'not-ready')),
      });
    })()`,
    returnByValue: true,
  });
  console.log('3. grid state:', state.result.value);
  console.log('console:', consoleLogs.slice(-6));

  ws.close();
  chromeProc.kill();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  chromeProc.kill();
  process.exit(1);
});
