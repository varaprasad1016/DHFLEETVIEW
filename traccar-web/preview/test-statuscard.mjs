/*
 * Verify the StatusCard video button appears for a device with cmsv9DeviceId.
 * Usage: CHROME=<chrome.exe> node preview/test-statuscard.mjs
 */
import { spawn } from 'child_process';
import { mkdtempSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const chrome = process.env.CHROME || '/c/Program Files/Google/Chrome/Application/chrome.exe';
const port = 9335;
const profile = mkdtempSync(join(tmpdir(), 'cmsv9-status-'));

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
  console.log('logged in');

  // Main page - auto-select the device via uniqueId param (Navigation.jsx supports this)
  await send('Page.navigate', { url: 'http://localhost:8082/?uniqueId=CMSV9TEST001' });
  await sleep(6000);

  // Check for the videocam icon in the status card
  const check = await send('Runtime.evaluate', {
    expression: `(() => {
      const buttons = [...document.querySelectorAll('button')];
      const withPath = buttons.filter((b) => b.querySelector('path')).map((b) => ({ title: b.getAttribute('title') || b.getAttribute('aria-label') || '', paths: b.querySelectorAll('path').length }));
      return JSON.stringify({
        svgCount: document.querySelectorAll('svg').length,
        buttons: withPath.slice(0, 10),
        body: document.body.innerText.slice(0, 150),
      });
    })()`,
    returnByValue: true,
  });
  console.log('status card:', check.result.value);

  ws.close();
  chromeProc.kill();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  chromeProc.kill();
  process.exit(1);
});
