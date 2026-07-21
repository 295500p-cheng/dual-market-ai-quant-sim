const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = "/tmp/quant-site-public";
const PORT = 4174;
const HOST = "127.0.0.1";

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
};

function send(res, status, body, type = "text/plain; charset=utf-8") {
  res.writeHead(status, {
    "content-type": type,
    "cache-control": "no-store",
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const rawPath = decodeURIComponent(new URL(req.url, `http://${HOST}:${PORT}`).pathname);
  const normalized = path.normalize(rawPath).replace(/^(\.\.[/\\])+/, "");
  let filePath = path.join(ROOT, normalized);

  if (!filePath.startsWith(ROOT)) {
    send(res, 403, "Forbidden");
    return;
  }

  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, "index.html");
  }

  fs.readFile(filePath, (error, data) => {
    if (error) {
      send(res, 404, "Not found");
      return;
    }
    send(res, 200, data, contentTypes[path.extname(filePath)] || "application/octet-stream");
  });
});

server.listen(PORT, HOST, () => {
  console.log(`Serving ${ROOT} at http://${HOST}:${PORT}/quant-dual-market-site/`);
});
