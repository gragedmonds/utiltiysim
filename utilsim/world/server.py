"""Local desktop controls for the world runtime, independent of business systems."""

import argparse
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import (
    contacts,
    cruise,
    customer_finance,
    development,
    field_cancellation,
    field_execution,
    field_reporting,
    field_travel,
    field_water_mains,
    hazards,
    network_faults,
    occupancy,
    sewer,
    storms,
    water_faults,
    water_mains,
)
from .map_view import WorldMap
from .store import World


def make_server(world, port=8026, viewer_dir=None, field_db=None, cruise_worker=True):
    viewer = Path(viewer_dir or Path(__file__).resolve().parents[2] / "packages/town-viewer/dist").resolve()
    map_view = WorldMap(world)
    field = field_execution.FieldExecution(world, field_db) if field_db is not None else None

    class WorldServer(ThreadingHTTPServer):
        """Own the local worker's lifetime, including the current durable day."""
        def __init__(self, address, handler):
            super().__init__(address, handler)
            self.cruise_stop = threading.Event()
            self.cruise_thread = None
            self.cruise_worker_error = None

        def _work(self):
            while not self.cruise_stop.is_set():
                try:
                    cruise.tick(world, field, max_days=1)
                except cruise.BusyError:
                    # Another local controller holds this world's execution
                    # lock; persistent domain failures stop within the controller.
                    pass
                except Exception as exc:
                    # Expose unexpected worker loss; never claim the run is
                    # progressing or silently replace it with another policy.
                    self.cruise_worker_error = type(exc).__name__
                    return
                self.cruise_stop.wait(0.2)

        def serve_forever(self, poll_interval=0.5):
            self.cruise_stop.clear()
            self.cruise_worker_error = None
            if cruise_worker:
                self.cruise_thread = threading.Thread(target=self._work, name="world-cruise", daemon=True)
                self.cruise_thread.start()
            try:
                super().serve_forever(poll_interval)
            finally:
                self.cruise_stop.set()
                if self.cruise_thread is not None:
                    self.cruise_thread.join()

        def server_close(self):
            self.cruise_stop.set()
            if self.cruise_thread is not None and self.cruise_thread is not threading.current_thread():
                self.cruise_thread.join()
            super().server_close()

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
            if url.path in ("/cruise", "/cruise.js"):
                return self.static(Path(__file__).with_name("cruise.html" if url.path == "/cruise" else "cruise.js"))
            if url.path == "/api/cruise":
                if url.query:
                    return self.reply(422, {"error": "Cruise status takes no query parameters."})
                try:
                    return self.reply(200, {**cruise.inspect(world, field),
                        "workerEnabled": bool(cruise_worker), "workerError": self.server.cruise_worker_error})
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/field-execution", "/field-execution.js"):
                return self.static(Path(__file__).with_name("field_execution.html" if url.path == "/field-execution" else "field_execution.js"))
            if url.path in ("/field-reporting", "/field-reporting.js"):
                return self.static(Path(__file__).with_name("field_reporting.html" if url.path == "/field-reporting" else "field_reporting.js"))
            if url.path in ("/field-travel", "/field-travel.js"):
                return self.static(Path(__file__).with_name("field_travel.html" if url.path == "/field-travel" else "field_travel.js"))
            if url.path == "/api/field-reporting":
                if field is None:
                    return self.reply(503, {"error": "Field reporting requires a separate --field-db database."})
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args)-{"after", "limit"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one optional field cursor and limit.")
                    return self.reply(200, field_reporting.inspect(field, limit=int(args.get("limit", ["25"])[0]),
                                                                   after=int(args.get("after", ["0"])[0])))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path == "/api/field-execution":
                if field is None:
                    return self.reply(503, {"error": "Field execution is not configured. Start with --field-db pointing to a separate field database."})
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args)-{"after", "limit"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one optional field cursor and limit.")
                    return self.reply(200, field_execution.inspect(field, int(args.get("after", ["0"])[0]), int(args.get("limit", ["25"])[0])))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
            if url.path in ("/customer-finance", "/customer-finance.js", "/development", "/development.js"):
                names = {"/customer-finance": "customer-finance.html", "/customer-finance.js": "customer-finance.js",
                         "/development": "development.html", "/development.js": "development.js"}
                return self.static(Path(__file__).with_name(names[url.path]))
            if url.path in ("/api/customer-finance", "/api/payment-intents", "/api/development"):
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    allowed = ({"premise"} if url.path == "/api/customer-finance" else
                               {"after", "limit"} if url.path == "/api/payment-intents" else {"projectId", "offset", "limit"})
                    if set(args)-allowed or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use only the supported selection and page parameters.")
                    if url.path == "/api/customer-finance":
                        result = customer_finance.inspect(world, args["premise"][0])
                    elif url.path == "/api/payment-intents":
                        result = customer_finance.ready(world, int(args.get("after", ["0"])[0]), int(args.get("limit", ["25"])[0]))
                    else:
                        result = development.inspect(world, args.get("projectId", [None])[0],
                                                     int(args.get("offset", ["0"])[0]), int(args.get("limit", ["25"])[0]))
                    return self.reply(200, result)
                except (ValueError, TypeError, KeyError) as exc:
                    return self.reply(422, {"error": str(exc)})
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
            if url.path in ("/storms", "/storms.js"):
                return self.static(Path(__file__).with_name("storms.html" if url.path == "/storms" else "storms.js"))
            if url.path == "/api/storms":
                try:
                    args = parse_qs(url.query, keep_blank_values=True)
                    if set(args)-{"before", "eventsBefore"} or any(len(v) != 1 for v in args.values()):
                        raise ValueError("Use one optional storm history cursor.")
                    return self.reply(200, storms.inspect(world, before=args.get("before", [None])[0],
                                                         events_before=args.get("eventsBefore", [None])[0]))
                except (ValueError, TypeError) as exc:
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
            result["cruise"] = cruise.inspect(world, field)
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
                    if self.path == "/api/cruise":
                        if p.get("action") in ("start", "resume") and (not cruise_worker or self.server.cruise_worker_error):
                            return self.reply(503, {"error": "Cruise worker is unavailable. Restart the local server before changing this run."})
                        result = cruise.command(world, p, field)
                    elif self.path == "/api/field-travel/quote":
                        if field is None:
                            return self.reply(503, {"error": "Field travel requires a separate --field-db database."})
                        result = field_travel.quote(field, p)
                    elif self.path == "/api/field-assignment-lifecycle":
                        if field is None:
                            return self.reply(503, {"error": "Field assignment lifecycle requires a separate --field-db database."})
                        result = field_cancellation.command(field, p)
                    elif self.path == "/api/field-main-phases":
                        if field is None:
                            return self.reply(503, {"error": "Field main phases require a separate --field-db database."})
                        result = field_water_mains.command(field, p)
                    elif self.path == "/api/field-reporting":
                        if field is None:
                            return self.reply(503, {"error": "Field reporting requires a separate --field-db database."})
                        result = field_reporting.command(field, p)
                    elif self.path in ("/api/field-execution", "/api/field-execution/run-due"):
                        if field is None:
                            return self.reply(503, {"error": "Field execution requires a separate --field-db database."})
                        if p.get("schemaVersion") == field_water_mains.VERSION:
                            raise ValueError("Accept main phases through /api/field-main-phases.")
                        if self.path.endswith("/run-due"):
                            if set(p) != {"environmentId", "worldFingerprint", "effectiveDate"}:
                                raise ValueError("Provide the world identity and current date when running due field work.")
                            with cruise.manual_control(world, field):
                                result = field_execution.run_due(field, p)
                        else:
                            if p.get("action") == "execute":
                                with cruise.manual_control(world, field):
                                    result = field_execution.command(field, p)
                            else:
                                result = field_execution.command(field, p)
                    elif self.path == "/api/customer-finance":
                        result = customer_finance.command(world, p)
                    elif self.path == "/api/development":
                        result = development.command(world, p)
                    elif self.path == "/api/contacts":
                        result = contacts.command(world, p)
                    elif self.path == "/api/water-mains":
                        result = water_mains.command(world, p)
                    elif self.path == "/api/hazards":
                        result = hazards.command(world, p)
                    elif self.path == "/api/storms":
                        with cruise.manual_control(world, field):
                            result = storms.command(world, p)
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
                        with cruise.manual_control(world, field):
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

    return WorldServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="UtilitySim v2 world controls")
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8026)
    parser.add_argument("--viewer-dir", help="Existing town-viewer dist directory with vendored Three.js")
    parser.add_argument("--field-db", help="Optional separate SQLite field/workforce store for administrator field controls")
    parser.add_argument("--open-map", action="store_true", help="Open the durable world map in the default browser")
    args = parser.parse_args()
    server = make_server(World(args.db), args.port, args.viewer_dir, args.field_db)
    print(f"UtilitySim world: http://127.0.0.1:{server.server_port}/", flush=True)
    if args.open_map:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/map")
    server.serve_forever()


if __name__ == "__main__":
    main()
