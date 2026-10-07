from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import time
import json
from urllib.parse import urlparse, parse_qs

class SimpleRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        t_recv = time.monotonic()
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        delay_seconds = 0.0
        if 'delay' in query_params:
            try:
                delay_seconds = float(query_params['delay'][0])
            except ValueError:
                pass  

        if delay_seconds > 0:
            time.sleep(delay_seconds)

        response_bytes = json.dumps({"delay": delay_seconds, "t_recv": t_recv}).encode("utf-8")
        
        content_length = len(response_bytes)

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-Length", str(content_length))
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, format, *args):
        pass

def run_server():
    server_address = ('127.0.0.1', 8080)
    httpd = ThreadingHTTPServer(server_address, SimpleRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()

if __name__ == '__main__':
    run_server()
