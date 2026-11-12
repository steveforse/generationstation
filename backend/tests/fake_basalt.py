"""Stand-in for `basalt serve --config FILE` used by runtime tests. Loads no model.

FAKE_BASALT_MODE: "ok" (default) reports loading, then loaded after FAKE_BASALT_DELAY seconds;
"exit" prints an error and exits; "fail" reports a failed model.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    args = sys.argv[1:]
    config_path = args[args.index("--config") + 1]
    with open(config_path, encoding="utf-8") as file:
        config = json.load(file)
    port = config["server"]["port"]
    mode = os.environ.get("FAKE_BASALT_MODE", "ok")
    delay = float(os.environ.get("FAKE_BASALT_DELAY", "0.5"))
    print(f"[server] config {config_path} gpu={config['models'][0]['gpu']} "
          f"order={os.environ.get('CUDA_DEVICE_ORDER')}", flush=True)
    if mode == "exit":
        print("error: the pack's buffers do not fit; try --resident-budget-gib 40", flush=True)
        sys.exit(1)
    started = time.monotonic()
    alias = config["models"][0]["alias"]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/v1/models":
                self.send_response(404)
                self.end_headers()
                return
            if mode == "fail":
                status = "failed"
            else:
                status = "loaded" if time.monotonic() - started >= delay else "loading"
            body = json.dumps({"data": [{"id": alias, "status": status}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
