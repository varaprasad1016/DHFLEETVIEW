/*
 * Test the multi-camera grid in the Android emulator WebView.
 * Requires: adb forward tcp:9223 localabstract:webview_devtools_remote_<pid>
 * Usage: node preview/test-android-grid.mjs
 */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const targets = await (await fetch('http://127.0.0.1:9223/json')).json();
  const page = targets.find((t) => t.type === 'page');
  if (!page) throw new Error('No page target');
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

  // Login (page is on login route after restart)
  await send('Runtime.evaluate', {
    expression: `fetch('/api/session', { method: 'POST', body: new URLSearchParams({ email: 'video-test@dhgroup.local', password: 'VideoTest123!' }) })`,
    awaitPromise: true,
  });
  console.log('logged in');

  await send('Page.navigate', { url: 'http://10.0.2.2:8082/cmsv9-video?deviceId=1' });

  // Wait for the SPA to boot and the Play button to be enabled
  let booted = false;
  for (let i = 0; i < 40; i++) {
    const r = await send('Runtime.evaluate', {
      expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Play'); return b ? !b.disabled : false; })()`,
      returnByValue: true,
    });
    if (r.result.value) { booted = true; break; }
    await sleep(500);
  }
  console.log('page booted:', booted);
  await send('Runtime.evaluate', {
    expression: `(() => { const tabs = [...document.querySelectorAll('[role="tab"]')]; if (tabs[1]) tabs[1].click(); })()`,
    returnByValue: true,
  });
  await sleep(800);
  const playAll = await send('Runtime.evaluate', {
    expression: `(() => {
      const b = [...document.querySelectorAll('button')].find((x) => x.innerText.includes('Play all'));
      if (!b) return 'no button';
      b.click();
      return 'clicked';
    })()`,
    returnByValue: true,
  });
  console.log('play all:', playAll.result.value);
  await sleep(12000);

  const state = await send('Runtime.evaluate', {
    expression: `(() => {
      const vids = [...document.querySelectorAll('video')];
      return JSON.stringify({
        videoCount: vids.length,
        playing: vids.filter((v) => !v.paused && v.videoWidth > 0).length,
        body: document.body.innerText.slice(0, 120),
      });
    })()`,
    returnByValue: true,
  });
  console.log('grid state:', state.result.value);

  ws.close();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  process.exit(1);
});
