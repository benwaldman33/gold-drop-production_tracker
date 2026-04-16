import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { request as httpRequest } from "node:http";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..");
const port = Number(process.env.PORT || 4173);
const backendUrl = new URL(process.env.BACKEND_URL || "http://127.0.0.1:5050");

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

function resolveFile(urlPath) {
  const clean = urlPath === "/" ? "/index.html" : urlPath;
  const target = path.normalize(path.join(root, clean));
  if (!target.startsWith(root)) return null;
  return target;
}

function proxyRequest(req, res) {
  const upstreamPath = req.url || "/";
  const proxy = httpRequest(
    {
      protocol: backendUrl.protocol,
      hostname: backendUrl.hostname,
      port: backendUrl.port,
      method: req.method,
      path: upstreamPath,
      headers: {
        ...req.headers,
        host: backendUrl.host,
      },
    },
    (upstream) => {
      const headers = { ...upstream.headers, "Cache-Control": "no-store" };
      res.writeHead(upstream.statusCode || 502, headers);
      upstream.pipe(res);
    }
  );

  proxy.on("error", () => {
    res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: "Unable to reach Gold Drop backend.", backend: backendUrl.origin }));
  });

  req.pipe(proxy);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "127.0.0.1"}`);
  if (url.pathname.startsWith("/api/")) {
    proxyRequest(req, res);
    return;
  }
  const file = resolveFile(url.pathname);
  if (!file || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
    return;
  }

  const ext = path.extname(file).toLowerCase();
  res.writeHead(200, {
    "Content-Type": contentTypes[ext] || "application/octet-stream",
    "Cache-Control": "no-store",
  });
  res.end(fs.readFileSync(file));
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Gold Drop Purchasing Agent App running at http://127.0.0.1:${port}`);
  console.log(`Proxying /api/* to ${backendUrl.origin}`);
});
