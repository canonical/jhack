import time
from http.server import HTTPServer, BaseHTTPRequestHandler


class MyRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
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


if __name__ == "__main__":
    while True:
        try:
            httpd = HTTPServer(("", 65301), MyRequestHandler)
        except OSError as e:
            if e.errno == 98:
                print("waiting for port...")
                time.sleep(0.1)
                continue
            raise
        print("serving...")
        httpd.serve_forever()
