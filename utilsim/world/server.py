"""Local desktop controls for the world runtime, independent of business systems."""

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import contacts, hazards, network_faults, occupancy, sewer, water_faults, water_mains
from .map_view import WorldMap
from .store import World


def make_server(world, port=8026, viewer_dir=None):
    viewer = Path(viewer_dir or Path(__file__).resolve().parents[2] / "packages/town-viewer/dist").resolve()
    map_view = WorldMap(world)
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
            url = urlsplit(self.path)
            if url.path in ("/contacts", "/contacts.js"):
                return self.static(Path(__file__).with_name("contacts.html" if url.path == "/contacts" else "contacts.js"))
            if url.path in ("/api/contacts", "/api/contact-intents"):
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args)-{"after", "limit"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one optional contact cursor and limit.")
                    limit = int(args.get("limit", ["25"])[0])
                    result = (contacts.inspect(world, int(args.get("after", ["0"])[0]), limit) if url.path == "/api/contacts" else
                              contacts.ready(world, args.get("after", [None])[0], limit))
                    return self.reply(200, result)
                except (ValueError, TypeError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/water-mains", "/water-mains.js"):
                return self.static(Path(__file__).with_name("water_mains.html" if url.path == "/water-mains" else "water_mains.js"))
            if url.path == "/api/water-mains":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args)-{"edgeId", "after", "before", "serviceAfter", "beforeDay"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one main ID and optional page cursors.")
                    return self.reply(200, water_mains.inspect(world, args.get("edgeId", [None])[0],
                        args.get("after", [""])[0], int(args["before"][0]) if "before" in args else None,
                        args.get("serviceAfter", [""])[0], args.get("beforeDay", [None])[0]))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/hazards", "/hazards.js"):
                return self.static(Path(__file__).with_name("hazards.html" if url.path == "/hazards" else "hazards.js"))
            if url.path == "/api/hazards":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args)-{"before"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one optional history cursor.")
                    return self.reply(200, hazards.inspect(world, args.get("before", [None])[0]))
                except (ValueError, TypeError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/sewer", "/sewer.js"):
                return self.static(Path(__file__).with_name("sewer.html" if url.path == "/sewer" else "sewer.js"))
            if url.path == "/api/sewer":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args) - {"waterAssetId", "before", "beforeDay"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one source water service and optional history cursors.")
                    return self.reply(200, sewer.inspect(world, args["waterAssetId"][0],
                        int(args["before"][0]) if "before" in args else None, args.get("beforeDay", [None])[0]))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/network-faults", "/network-faults.js"):
                return self.static(Path(__file__).with_name("network_faults.html" if url.path == "/network-faults" else "network_faults.js"))
            if url.path == "/api/network-faults":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args) - {"commodity", "edgeId", "after", "before", "serviceAfter"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one commodity, edge ID and optional page cursors.")
                    return self.reply(200, network_faults.inspect(world, args.get("commodity", ["electric"])[0],
                        args.get("edgeId", [None])[0], args.get("after", [""])[0],
                        int(args["before"][0]) if "before" in args else None,
                        service_after=args.get("serviceAfter", [""])[0]))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/water-faults", "/water-faults.js"):
                return self.static(Path(__file__).with_name("water_faults.html" if url.path == "/water-faults" else "water_faults.js"))
            if url.path == "/api/water-faults":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args) - {"assetId", "before"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use a single water service meter and optional history cursor.")
                    return self.reply(200, water_faults.inspect(world, args["assetId"][0],
                                                               int(args["before"][0]) if "before" in args else None))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/occupancy", "/occupancy.js"):
                return self.static(Path(__file__).with_name("occupancy.html" if url.path == "/occupancy" else "occupancy.js"))
            if url.path == "/api/occupancy":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args) - {"premiseId", "before"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use a single premise ID and optional history cursor.")
                    return self.reply(200, occupancy.inspect(world, args["premiseId"][0],
                                                            int(args["before"][0]) if "before" in args else None))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/map", "/map.js"):
                if not (viewer / "vendor/three.module.js").is_file():
                    return self.reply(503, {"error": "Map assets unavailable. Run npm install in packages/town-viewer, or provide --viewer-dir."})
                name = "map.html" if url.path == "/map" else "map.js"
                return self.static(Path(__file__).with_name(name))
            if url.path.startswith("/viewer/"):
                target = (viewer / unquote(url.path.removeprefix("/viewer/"))).resolve()
                atlas = target == viewer / "iso/atlas.json"
                if not target.is_relative_to(viewer) or (not atlas and target.suffix.lower() not in (
                        ".js", ".css", ".png", ".svg", ".webp", ".jpg")):
                    return self.reply(403, {"error": "Invalid map asset."})
                return self.static(target)
            if url.path.startswith("/api/map/"):
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if url.path == "/api/map/snapshot" and not args:
                        return self.reply(200, map_view.snapshot())
                    if url.path == "/api/map/status" and not args:
                        return self.reply(200, map_view.status())
                    if url.path == "/api/map/premise" and set(args) == {"id"} and len(args["id"]) == 1:
                        return self.reply(200, map_view.premise(args["id"][0]))
                    raise ValueError("Use the snapshot or a single premise ID.")
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if self.path != "/api/state":
                return self.reply(404, {"error": "Not found."})
            with world.db() as db:
                result = world._status(db)
                meta = world.metadata(db)
                result.update(start=meta.get("start"), settings=meta.get("settings"), worldFingerprint=meta.get("fingerprint"),
                              managedDelivery=db.execute("SELECT 1 FROM observation_delivery_configuration").fetchone() is not None,
                              weather=[dict(r) for r in db.execute("SELECT * FROM days ORDER BY day DESC LIMIT 60")],
                              assets=[{**dict(r), "profile": json.loads(r["profile"])}
                                      for r in db.execute("SELECT * FROM assets ORDER BY id LIMIT 300")],
                              conditions=[dict(r) for r in db.execute("SELECT condition,COUNT(*) count FROM assets GROUP BY condition")],
                              events=[{**dict(r), "payload": json.loads(r["payload"])} for r in
                                      db.execute("SELECT * FROM events ORDER BY sequence DESC LIMIT 40")])
            return self.reply(200, result)

        def static(self, path):
            if not path.is_file():
                return self.reply(404, {"error": "Map asset not found."})
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript" if path.suffix == ".js" else
                             mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

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
                if not isinstance(p, dict):
                    raise ValueError("JSON object required.")
                if self.path == "/api/init":
                    result = world.initialize(p["snapshot"], p["environmentId"], p["start"], p.get("settings"))
                else:
                    if p.get("environmentId") != world.status().get("environmentId"):
                        raise ValueError("Environment mismatch.")
                    if self.path == "/api/contacts":
                        result = contacts.command(world, p)
                    elif self.path == "/api/water-mains":
                        result = water_mains.command(world, p)
                    elif self.path == "/api/hazards":
                        result = hazards.command(world, p)
                    elif self.path == "/api/sewer":
                        result = sewer.command(world, p)
                    elif self.path == "/api/network-faults":
                        result = network_faults.command(world, p)
                    elif self.path == "/api/water-faults":
                        result = water_faults.command(world, p)
                    elif self.path == "/api/occupancy":
                        result = occupancy.command(world, p)
                    elif self.path == "/api/advance":
                        with world.db() as db:
                            if db.execute("SELECT 1 FROM observation_delivery_configuration").fetchone():
                                raise ValueError("This world uses shared delivery. Advance it from the shared runtime control panel.")
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
    parser.add_argument("--viewer-dir", help="Existing town-viewer dist directory with vendored Three.js")
    parser.add_argument("--open-map", action="store_true", help="Open the durable world map in the default browser")
    args = parser.parse_args()
    server = make_server(World(args.db), args.port, args.viewer_dir)
    print(f"UtilitySim world: http://127.0.0.1:{server.server_port}/", flush=True)
    if args.open_map:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/map")
    server.serve_forever()


if __name__ == "__main__":
    main()
