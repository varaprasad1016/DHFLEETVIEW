/*
 * Full CMSV9 flow test: live video + recording search + recording playback.
 * Usage: CHROME=<chrome.exe> node preview/test-cmsv9-full.mjs
 */
import { spawn } from 'child_process';
import { mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const chrome = process.env.CHROME || '/c/Program Files/Google/Chrome/Application/chrome.exe';
const port = 9334;
const profile = mkdtempSync(join(tmpdir(), 'cmsv9-full-'));

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
    if (msg.method === 'Runtime.exceptionThrown') {
      consoleLogs.push('EXCEPTION: ' + (msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text));
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

  // Live play
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
  console.log('2. live video playing:', live.result.value);

  // Stop live, go to search tab
  await send('Runtime.evaluate', {
    expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Stop'); if (b) b.click(); })()`,
    returnByValue: true,
  });
  await sleep(1000);
  await send('Runtime.evaluate', {
    expression: `(() => { const t = [...document.querySelectorAll('[role="tab"]')]; if (t[1]) t[1].click(); })()`,
    returnByValue: true,
  });
  await sleep(1000);
  await send('Runtime.evaluate', {
    expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('Search')); if (b) b.click(); })()`,
    returnByValue: true,
  });
  await sleep(3000);
  const search = await send('Runtime.evaluate', {
    expression: `(() => { const body = document.body.innerText; const hasRec = body.includes('/Record/H20240101-080000'); return JSON.stringify({ recordingsFound: hasRec }); })()`,
    returnByValue: true,
  });
  console.log('3. recordings found:', search.result.value);

  // Click first recording to play it - find the clickable row (button-like element containing the path)
  const clickRes = await send('Runtime.evaluate', {
    expression: `(() => {
      const candidates = [...document.querySelectorAll('div,li,button')].filter((x) => x.innerText && x.innerText.includes('/Record/H20240101-080000'));
      const el = candidates[candidates.length - 1];
      if (!el) return 'not found';
      el.click();
      return 'clicked: ' + el.tagName + ' text=' + el.innerText.slice(0, 40);
    })()`,
    returnByValue: true,
  });
  console.log('4. recording click:', clickRes.result.value);
  await sleep(3000);
  const mid = await send('Runtime.evaluate', {
    expression: `(() => {
      const v = document.querySelector('video');
      return JSON.stringify({ hasVideo: !!v, paused: v?.paused, w: v?.videoWidth, body: document.body.innerText.slice(0, 150) });
    })()`,
    returnByValue: true,
  });
  console.log('5a. mid state:', mid.result.value);
  await sleep(5000);
  const playback = await send('Runtime.evaluate', {
    expression: `(() => {
      const v = document.querySelector('video');
      return JSON.stringify({ hasVideo: !!v, playing: !!v && !v.paused && v.videoWidth > 0, w: v?.videoWidth, h: v?.videoHeight, err: v?.error ? v.error.message : null });
    })()`,
    returnByValue: true,
  });
  console.log('5. recording playback:', playback.result.value);
  console.log('console:', consoleLogs.slice(-8));

  ws.close();
  chromeProc.kill();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  chromeProc.kill();
  process.exit(1);
});
