"""Local desktop controls for the world runtime, independent of business systems."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .store import World


def make_server(world, port=8026):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value, html=False):
            raw = value if html else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def local(self):
            port = self.server.server_port
            return self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")

        def do_GET(self):
            if not self.local():
                return self.reply(403, {"error": "Local host required."})
            if self.path == "/":
                return self.reply(200, Path(__file__).with_name("index.html").read_bytes(), True)
            if self.path != "/api/state":
                return self.reply(404, {"error": "Not found."})
            with world.db() as db:
                result = world._status(db)
                meta = world.metadata(db)
                result.update(start=meta.get("start"), settings=meta.get("settings"),
                              weather=[dict(r) for r in db.execute("SELECT * FROM days ORDER BY day DESC LIMIT 60")],
                              assets=[{**dict(r), "profile": json.loads(r["profile"])}
                                      for r in db.execute("SELECT * FROM assets ORDER BY id LIMIT 300")],
                              conditions=[dict(r) for r in db.execute("SELECT condition,COUNT(*) count FROM assets GROUP BY condition")],
                              events=[{**dict(r), "payload": json.loads(r["payload"])} for r in
                                      db.execute("SELECT * FROM events ORDER BY sequence DESC LIMIT 40")])
            return self.reply(200, result)

        def do_POST(self):
            port = self.server.server_port
            if not self.local() or self.headers.get("Origin") not in (
                    None, f"http://localhost:{port}", f"http://127.0.0.1:{port}"):
                return self.reply(403, {"error": "Local origin required."})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, {"error": "JSON required."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 64 * 1024 * 1024:
                    return self.reply(413, {"error": "Request too large or empty."})
                p = json.loads(self.rfile.read(size))
                if self.path == "/api/init":
                    result = world.initialize(p["snapshot"], p["environmentId"], p["start"], p.get("settings"))
                else:
                    if p.get("environmentId") != world.status().get("environmentId"):
                        raise ValueError("Environment mismatch.")
                    if self.path == "/api/advance":
                        result = world.advance(p["through"])
                    elif self.path == "/api/export":
                        result = world.export(p["start"], p["end"])
                    elif self.path == "/api/export-v2":
                        result = world.export_v2(p["start"], p["end"], p.get("sewerReturnFactor", "0.9"),
                                                p.get("delaySeconds", 0))
                    elif self.path == "/api/replace":
                        result = world.replace_meter(p["commandId"], p["environmentId"], p["meterId"],
                                                     p["newDeviceId"], p["workOrderId"], p["note"])
                    else:
                        return self.reply(404, {"error": "Not found."})
            except (ValueError, TypeError, KeyError) as exc:
                return self.reply(422, {"error": str(exc)})
            return self.reply(200, result)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="UtilitySim v2 world controls")
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8026)
    args = parser.parse_args()
    server = make_server(World(args.db), args.port)
    print(f"UtilitySim world: http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
