import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

PROBE = os.getenv("SERVER_PROBE")


class MyRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if PROBE == "pebble":
            # this is the health endpoint pinged by pebble

            if "liveness" in self.requestline:
                probe_name = "livenessroot"
            elif "readiness" in self.requestline:
                probe_name = "readinessroot"
            else:
                self.log_error(f"invalid request path: {self.requestline}")
                return

            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"OK: probe {probe_name}".encode())
            return

        elif PROBE == "kubernetes":
            # this is the health endpoint pinged by kubernetes
            if "health" in self.requestline:
                pass
            else:
                self.log_error(f"invalid request path: {self.requestline}")
                return

            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                '{"type":"sync","status-code":200,"status":"OK","result":{"healthy":true}}'.encode()
            )

        else:
            raise ValueError(PROBE)


if __name__ == "__main__":
    while True:
        try:
            httpd = HTTPServer(("", int(os.getenv("SERVER_PORT"))), MyRequestHandler)
        except OSError as e:
            if e.errno == 98:
                print("waiting for port...")
                time.sleep(0.1)
                continue
            raise
        print("serving...")
        httpd.serve_forever()
