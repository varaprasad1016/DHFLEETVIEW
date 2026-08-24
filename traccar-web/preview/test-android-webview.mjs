/*
 * Test CMSV9 video page in the Android emulator's WebView (DH FleetView app).
 * Requires: adb forward tcp:9223 localabstract:webview_devtools_remote_<pid>
 * Usage: node preview/test-android-webview.mjs
 */
const wsUrl = 'ws://127.0.0.1:9223/devtools/page/1';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  // Find the page target
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

  // The app's login page: fill the form. Try API login first (same origin)
  const login = await send('Runtime.evaluate', {
    expression: `(async () => {
      const res = await fetch('/api/session', {
        method: 'POST',
        body: new URLSearchParams({ email: 'video-test@dhgroup.local', password: 'VideoTest123!' }),
      });
      return res.status + ' ' + (await res.text()).slice(0, 60);
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  console.log('login via API:', login.result.value);

  // Navigate to the video page
  await send('Page.navigate', { url: 'http://10.0.2.2:8082/cmsv9-video?deviceId=1' });
  await sleep(6000);

  const state1 = await send('Runtime.evaluate', {
    expression: `JSON.stringify({ url: location.href, body: document.body.innerText.slice(0, 250) })`,
    returnByValue: true,
  });
  console.log('video page:', state1.result.value);

  // Wait for Play enabled, click it
  for (let i = 0; i < 20; i++) {
    const r = await send('Runtime.evaluate', {
      expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Play'); return b ? !b.disabled : false; })()`,
      returnByValue: true,
    });
    if (r.result.value) {
      console.log('Play enabled after', (i + 1) * 500, 'ms');
      break;
    }
    await sleep(500);
  }
  await send('Runtime.evaluate', {
    expression: `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Play'); if (b) b.click(); return 'clicked'; })()`,
    returnByValue: true,
  });
  await sleep(8000);

  const state2 = await send('Runtime.evaluate', {
    expression: `(() => {
      const v = document.querySelector('video');
      return JSON.stringify({
        hasVideo: !!v,
        playing: !!v && !v.paused && v.videoWidth > 0,
        w: v?.videoWidth,
        h: v?.videoHeight,
        err: v?.error ? v.error.message : null,
        body: document.body.innerText.slice(0, 120),
      });
    })()`,
    returnByValue: true,
  });
  console.log('live playback:', state2.result.value);

  ws.close();
  process.exit(0);
}

main().catch((e) => {
  console.error('TEST FAILED:', e.message);
  process.exit(1);
});
