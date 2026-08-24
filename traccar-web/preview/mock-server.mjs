// UI preview server: serves the built web app and fakes the minimal API
// endpoints needed to render the login and main screens, so you can preview
// UI changes without running the Traccar Java backend.
//
// Usage:
//   node preview/mock-server.mjs            # login screen (unauthenticated)
//   MOCK_USER=1 node preview/mock-server.mjs # main map screen (fake user + devices)
// Then open http://localhost:4173

import http from 'node:http';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..', 'build');
const port = process.env.PORT || 4173;

const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.mp3': 'audio/mpeg',
  '.webmanifest': 'application/manifest+json',
};

const renderIndex = (data) =>
  Buffer.from(
    data
      .toString('utf8')
      .replaceAll('${title}', 'DH FleetView')
      .replaceAll('${description}', 'Tracking and Live View')
      .replaceAll('${colorPrimary}', '#4f46e5'),
  );

const json = (res, body, status = 200) => {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname.startsWith('/api/')) {
    if (url.pathname === '/api/server') {
      json(res, {
        id: 1,
        registration: true,
        emailEnabled: true,
        openIdEnabled: false,
        openIdForce: false,
        announcement: null,
        attributes: {},
      });
      return;
    }
    if (url.pathname === '/api/session') {
      if (process.env.MOCK_USER) {
        json(res, {
          id: 1,
          name: 'Preview User',
          email: 'preview@example.com',
          administrator: true,
          readonly: false,
          temporary: false,
          deviceLimit: -1,
          attributes: {},
        });
        return;
      }
      res.writeHead(401, { 'Content-Type': 'text/plain' });
      res.end('Unauthorized');
      return;
    }
    if (url.pathname === '/api/devices') {
      json(res, [
        {
          id: 1,
          name: 'Delivery Van 1',
          uniqueId: 'VAN001',
          status: 'online',
          category: 'van',
          disabled: false,
          lastUpdate: new Date().toISOString(),
          attributes: {},
        },
        {
          id: 2,
          name: 'Company Car',
          uniqueId: 'CAR002',
          status: 'offline',
          category: 'car',
          disabled: false,
          lastUpdate: new Date(Date.now() - 3600000).toISOString(),
          attributes: {},
        },
        {
          id: 3,
          name: 'Fleet Truck',
          uniqueId: 'TRK003',
          status: 'unknown',
          category: 'truck',
          disabled: false,
          lastUpdate: null,
          attributes: {},
        },
      ]);
      return;
    }
    // Default: empty collection for other GET endpoints
    if (req.method === 'GET') {
      json(res, []);
      return;
    }
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found');
    return;
  }

  let path = decodeURIComponent(url.pathname);
  if (path === '/') {
    path = '/index.html';
  }
  const filePath = normalize(join(root, path));
  if (!filePath.startsWith(root)) {
    res.writeHead(403);
    res.end();
    return;
  }

  try {
    const data = await readFile(filePath);
    res.writeHead(200, { 'Content-Type': mime[extname(filePath)] || 'application/octet-stream' });
    res.end(filePath.endsWith('index.html') ? renderIndex(data) : data);
  } catch {
    try {
      const data = await readFile(join(root, 'index.html'));
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(renderIndex(data));
    } catch {
      res.writeHead(404);
      res.end('Not found');
    }
  }
});

// Accept websocket upgrades and silently keep them open so the app thinks it
// is connected to the live feed (no reconnects, no errors).
server.on('upgrade', (req, socket) => {
  const key = req.headers['sec-websocket-key'];
  const accept = createHash('sha1')
    .update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
    .digest('base64');
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
      'Upgrade: websocket\r\n' +
      'Connection: Upgrade\r\n' +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  socket.on('data', () => {});
});

server.listen(port, () => console.log(`Mock UI preview: http://localhost:${port}`));
