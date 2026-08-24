// Connects to the emulator WebView via CDP and reports what's rendered.
// Usage: node check-webview.mjs <ws-url>
const wsUrl = process.argv[2];
if (!wsUrl) {
  console.error("Usage: node check-webview.mjs <webSocketDebuggerUrl>");
  process.exit(1);
}

const ws = new WebSocket(wsUrl);
let id = 0;
const pending = new Map();

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
}

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  }
};

ws.onerror = (e) => {
  console.error("WebSocket error:", e.message || e);
  process.exit(1);
};

ws.onopen = async () => {
  try {
    const { root } = await send("DOM.getDocument", { depth: -1, pierce: true });
    // Grab key facts via Runtime.evaluate instead of walking the tree
    const evalResult = await send("Runtime.evaluate", {
      expression: `JSON.stringify({
        title: document.title,
        url: location.href,
        bodyText: (document.body ? document.body.innerText : '').slice(0, 400),
        hasLoginForm: !!document.querySelector('form'),
        loginButton: (() => { const b = document.querySelector('button[type="submit"], button.MuiButton-containedPrimary'); return b ? b.innerText : null; })(),
        logo: (() => { const i = document.querySelector('img'); return i ? i.alt || i.src.split('/').pop() : null; })(),
        errorText: (document.body ? document.body.innerText : '').match(/error|failed|refused|unavailable/i)?.[0] || null
      })`,
      returnByValue: true,
    });
    console.log(evalResult.result.value);
  } catch (err) {
    console.error("CDP error:", err.message);
  }
  ws.close();
  process.exit(0);
};
