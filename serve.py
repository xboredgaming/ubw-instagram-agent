"""
Serves architecture.html on localhost:8080 and opens the browser automatically.
Usage: python serve.py
"""

import http.server
import os
import threading
import webbrowser
from pathlib import Path

PORT = 8080
ROOT = Path(__file__).parent

os.chdir(ROOT)


def open_browser():
    webbrowser.open(f"http://localhost:{PORT}/architecture.html")


handler = http.server.SimpleHTTPRequestHandler

threading.Timer(0.5, open_browser).start()

print(f"Serving at http://localhost:{PORT}/architecture.html")
print("Press Ctrl+C to stop.\n")

with http.server.HTTPServer(("", PORT), handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
