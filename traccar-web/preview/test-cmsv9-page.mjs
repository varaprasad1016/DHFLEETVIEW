/*
 * CDP test for the CMSV9 video page against the real Traccar server + mock CMSV9.
 * Usage: CHROME=<chrome.exe> node preview/test-cmsv9-page.mjs
 */
import { spawn } from 'child_process';
import { mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const chrome = process.env.CHROME || '/c/Program Files/Google/Chrome/Application/chrome.exe';
const port = 9333;
const profile = mkdtempSync(join(tmpdir(), 'cmsv9-test-'));

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
  if (!page) throw new Error('No page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const consoleLogs = [];
  const networkLogs = [];
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
    if (msg.method === 'Network.responseReceived' && msg.params.response.url.includes('8604')) {
      networkLogs.push(`${msg.params.response.status} ${msg.params.response.url.slice(0, 120)}`);
    }
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  };
  await new Promise((resolve) => (ws.onopen = resolve));
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Log.enable');

  await send('Page.navigate', { url: 'http://localhost:8082/login' });
  await sleep(2500);
  await send('Runtime.evaluate', {
    expression: `(async () => {
      await fetch('/api/session', {
        method: 'POST',
        body: new URLSearchParams({ email: 'video-test@dhgroup.local', password: 'VideoTest123!' }),
      });
    })()`,
    awaitPromise: true,
  });
  console.log('logged in');

  await send('Page.navigate', { url: 'http://localhost:8082/cmsv9-video?deviceId=1' });
  await sleep(5000);

  let enabled = false;
  for (let i = 0; i < 20; i++) {
    const r = await send('Runtime.evaluate', {
      expression: `(() => {
        const buttons = [...document.querySelectorAll('button')];
        const play = buttons.find((b) => b.innerText.trim() === 'Play');
        if (!play) return JSON.stringify({ found: false });
        return JSON.stringify({ found: true, disabled: play.disabled });
      })()`,
      returnByValue: true,
    });
    const state = JSON.parse(r.result.value);
    if (state.found && !state.disabled) {
      console.log('Play button enabled after', (i + 1) * 500, 'ms');
      enabled = true;
      break;
    }
    await sleep(500);
  }
  if (!enabled) console.log('Play button never enabled');

  await send('Runtime.evaluate', {
    expression: `(() => {
      const play = [...document.querySelectorAll('button')].find((b) => b.innerText.trim() === 'Play');
      if (play) { play.click(); return 'clicked'; }
      return 'no button';
    })()`,
    returnByValue: true,
  });
  await sleep(8000);

  const state2 = await send('Runtime.evaluate', {
    expression: `(() => {
      const v = document.querySelector('video');
      if (!v) return JSON.stringify({ video: false, body: document.body.innerText.slice(0, 300) });
      return JSON.stringify({
        video: true,
        src: (v.src || '').slice(0, 150),
        readyState: v.readyState,
        paused: v.paused,
        videoWidth: v.videoWidth,
        videoHeight: v.videoHeight,
        error: v.error ? v.error.message : null,
        networkState: v.networkState,
      });
    })()`,
    returnByValue: true,
  });
  console.log('video state:', state2.result.value);

  // Search tab: switch and trigger search, check recordings list
  await send('Runtime.evaluate', {
    expression: `(() => {
      const tabs = [...document.querySelectorAll('[role="tab"]')];
      if (tabs[1]) tabs[1].click();
      return 'tab clicked';
    })()`,
    returnByValue: true,
  });
  await sleep(1000);
  const preClick = await send('Runtime.evaluate', {
    expression: `(() => {
      const buttons = [...document.querySelectorAll('button')].map((b) => ({ text: b.innerText.slice(0, 30), disabled: b.disabled }));
      return JSON.stringify(buttons);
    })()`,
    returnByValue: true,
  });
  console.log('buttons on search tab:', preClick.result.value);
  const clickResult = await send('Runtime.evaluate', {
    expression: `(() => {
      const search = [...document.querySelectorAll('button')].find((b) => b.innerText.includes('Search'));
      if (!search) return 'no search button';
      if (search.disabled) return 'search disabled';
      search.click();
      return 'search clicked';
    })()`,
    returnByValue: true,
  });
  console.log('search:', clickResult.result.value);
  await sleep(3000);
  const state3 = await send('Runtime.evaluate', {
    expression: `(() => {
      const items = [...document.querySelectorAll('li')].map((li) => li.innerText.slice(0, 90)).filter(Boolean);
      const scripts = [...document.querySelectorAll('script[src*="8605"]')].map((s) => s.src.slice(0, 150));
      return JSON.stringify({ items: items.slice(0, 4), jsonpScripts: scripts, body: document.body.innerText.slice(0, 400) });
    })()`,
    returnByValue: true,
  });
  console.log('recordings:', state3.result.value);

  // Navigate to main page and check the StatusCard video button exists
  await send('Page.navigate', { url: 'http://localhost:8082/?deviceId=1' });
  await sleep(3500);
  const state4 = await send('Runtime.evaluate', {
    expression: `(() => {
      const buttons = [...document.querySelectorAll('button')];
      const videoBtn = buttons.filter((b) => b.querySelector('svg')).length;
      return JSON.stringify({
        title: document.title,
        hasVideocamIcon: !!document.querySelector('[data-testid="VideocamIcon"]'),
        allIcons: [...document.querySelectorAll('svg')].map((s) => s.getAttribute('data-testid')).filter(Boolean).slice(0, 20),
      });
    })()`,
    returnByValue: true,
  });
  console.log('status card icons:', state4.result.value);

  console.log('console logs:', consoleLogs.slice(-6));
  ws.close();
  chromeProc.kill();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  chromeProc.kill();
  process.exit(1);
});
