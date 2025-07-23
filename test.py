import os
import re
import requests
import shutil
from urllib.parse import urljoin, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import subprocess
from collections import OrderedDict

PORT = 8888
CACHE_SIZE = 5

def strip_png_header(data):
    png_sig = b'\x89PNG\r\n\x1a\n'
    if data.startswith(png_sig):
        idx = data.find(b'\x47', 8)
        if idx != -1:
            return data[idx:]
    return data

class SegmentCache:
    def __init__(self, max_size):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, key):
        return self.cache.get(key)

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

segment_cache = SegmentCache(CACHE_SIZE)
segment_url_map = {}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/seg_"):
            seg_name = self.path.lstrip("/")
            url = segment_url_map.get(seg_name)
            if not url:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return
            data = segment_cache.get(seg_name)
            if data is None:
                # Download and strip
                print(f"Downloading: {url}")
                resp = requests.get(url, timeout=20)
                data = strip_png_header(resp.content)
                segment_cache.put(seg_name, data)
            self.send_response(200)
            self.send_header("Content-Type", "video/MP2T")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/fixed.m3u8":
            with open("fixed.m3u8", "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

def process_m3u8(m3u8_path, new_m3u8="fixed.m3u8"):
    with open(m3u8_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Xác định base URL nếu là m3u8 online
    base_url = ""
    if re.match(r"^https?://", m3u8_path):
        base_url = m3u8_path.rsplit("/", 1)[0] + "/"

    seg_idx = 0
    new_lines = []
    for line in lines:
        line_strip = line.strip()
        if line_strip and not line_strip.startswith("#"):
            seg_url = line_strip
            if not re.match(r"^https?://", seg_url):
                if base_url:
                    seg_url = urljoin(base_url, seg_url)
                else:
                    seg_url = os.path.join(os.path.dirname(m3u8_path), seg_url)
            seg_name = f"seg_{seg_idx:04d}.ts"
            segment_url_map[seg_name] = seg_url
            new_lines.append(f"http://localhost:{PORT}/{seg_name}\n")
            seg_idx += 1
        else:
            new_lines.append(line)
    with open(new_m3u8, "w", encoding="utf-8") as f:
        for l in new_lines:
            f.write(l)
    print(f"Đã tạo file m3u8 mới: {new_m3u8}")

def run_server():
    httpd = HTTPServer(("localhost", PORT), Handler)
    print(f"Serving on http://localhost:{PORT}")
    httpd.serve_forever()

def play_with_ffplay(m3u8_url):
    subprocess.run([
        "ffplay",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto,data",
        "-autoexit",
        "-loglevel", "warning",
        m3u8_url
    ])

if __name__ == "__main__":
    m3u8_file = "0.m3u8"
    process_m3u8(m3u8_file)
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    play_with_ffplay(f"http://localhost:{PORT}/fixed.m3u8")