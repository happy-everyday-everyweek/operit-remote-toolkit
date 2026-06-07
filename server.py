#!/usr/bin/env python3
import http.server
import socketserver
import urllib.request
import urllib.parse
import os

PORT = 8924
API_HOST = 'http://127.0.0.1:8094'
DIR = '/data/user/0/com.ai.assistance.operit/files/workspace/dc071d7c-eebc-4f86-a5af-b7140bb7afb5'

# 桌面端 User-Agent，使请求的网站返回电脑版页面
DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        try:
            if self.path.startswith('/api/'):
                self._proxy()
            elif self.path.startswith('/file/'):
                self._serve_file()
            elif self.path.startswith('/browse/'):
                self._browse()
            else:
                super().do_GET()
        except Exception as e:
            import traceback; traceback.print_exc()
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Internal error')
            except: pass

    def _browse(self):
        """通过 /browse/ 端点代理访问外部网页，并改写 User-Agent 为桌面端"""
        raw_url = urllib.parse.unquote(self.path[len('/browse/'):])
        if not raw_url:
            self.send_response(400)
            self.end_headers()
            return
        if not raw_url.startswith('http://') and not raw_url.startswith('https://'):
            self.send_response(400)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bad request: need http:// or https://')
            return
        try:
            req = urllib.request.Request(raw_url)
            # 改写为桌面端 UA
            req.add_header('User-Agent', DESKTOP_UA)
            # 透传其他常用请求头
            for key in ('Accept', 'Accept-Language', 'Cookie', 'Referer'):
                if key in self.headers:
                    req.add_header(key, self.headers[key])
            # 添加参考来源
            if 'Referer' not in self.headers:
                req.add_header('Referer', 'https://www.google.com/')
            with urllib.request.urlopen(req, timeout=15) as resp:
                self.send_response(resp.status)
                # 透传响应头
                skip_headers = {'transfer-encoding', 'content-encoding', 'content-length',
                                'strict-transport-security', 'access-control-allow-origin'}
                for key, val in resp.headers.items():
                    kl = key.lower()
                    if kl in skip_headers:
                        continue
                    # 安全过滤 Set-Cookie（不过滤也行，但为避免跨站问题只透传部分）
                    self.send_header(key, val)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                data = resp.read()
                try:
                    self.wfile.write(data)
                except: pass
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                self.wfile.write(f'<h2>代理请求失败</h2><p>HTTP {e.code}: {e.reason}</p>'.encode())
            except: pass
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            try:
                self.wfile.write(f'<h2>代理请求失败</h2><p>{e}</p>'.encode())
            except: pass

    def _serve_file(self):
        """通过 /file/ 端点提供 Android 本地文件访问，解决 file:// 跨设备不可用问题"""
        import os, mimetypes
        # 解码路径并去掉 /file/ 前缀
        raw_path = urllib.parse.unquote(self.path[len('/file/'):])
        # 如果是 file:///xxx 格式转换
        if raw_path.startswith('file://'):
            raw_path = raw_path[7:]
        # 如果路径不以 / 开头，补上
        if not raw_path.startswith('/'):
            raw_path = '/' + raw_path
        # 安全检查：禁止超出 /storage 和 /data 目录
        allowed_prefixes = ('/storage/', '/data/', '/sdcard')
        if not raw_path.startswith(allowed_prefixes):
            self.send_response(403)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Forbidden')
            return
        # 尝试多种可能的实际路径
        candidates = [raw_path]
        # 如果是 /storage/emulated/0/...，补充 /sdcard/... 版本
        if raw_path.startswith('/storage/emulated/0/'):
            candidates.append('/sdcard/' + raw_path[len('/storage/emulated/0/'):])
        # 如果是 /sdcard/...，补充 /storage/emulated/0/... 版本
        if raw_path.startswith('/sdcard/'):
            candidates.append('/storage/emulated/0/' + raw_path[len('/sdcard/'):])
        # 如果是 /data/user/0/...，补充 /data/data/... 版本等常见变体
        if raw_path.startswith('/data/user/0/'):
            pkg = raw_path.split('/')[4] if len(raw_path.split('/')) > 4 else ''
            if pkg:
                candidates.append('/data/data/' + pkg + '/' + '/'.join(raw_path.split('/')[5:]))
        real_path = None
        for c in candidates:
            if os.path.exists(c) and os.path.isfile(c):
                real_path = c
                break
        if not real_path:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'File not found')
            return
        try:
            mime_type, _ = mimetypes.guess_type(real_path)
            if not mime_type:
                mime_type = 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Length', str(os.path.getsize(real_path)))
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(real_path, 'rb') as f:
                buf = f.read()
                try:
                    self.wfile.write(buf)
                except: pass
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            try:
                self.wfile.write(f'Error reading file: {e}'.encode())
            except: pass

    def do_POST(self):
        try:
            if self.path.startswith('/api/'):
                self._proxy()
            else:
                self.send_error(405)
        except Exception as e:
            import traceback; traceback.print_exc()
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Internal error')
            except: pass

    def do_PUT(self):
        try:
            if self.path.startswith('/api/'):
                self._proxy()
            else:
                self.send_error(405)
        except: pass

    def do_DELETE(self):
        try:
            if self.path.startswith('/api/'):
                self._proxy()
            else:
                self.send_error(405)
        except: pass

    def do_OPTIONS(self):
        try:
            if self.path.startswith('/api/'):
                self._proxy()
            else:
                self.send_error(405)
        except: pass

    def _proxy(self):
        try:
            url = API_HOST + self.path
            body = None
            if self.command in ('POST', 'PUT'):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)

            req = urllib.request.Request(url, data=body, method=self.command)
            for key in ('Content-Type', 'Authorization', 'Accept'):
                if key in self.headers:
                    req.add_header(key, self.headers[key])

            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                for key, val in resp.headers.items():
                    if key.lower() not in ('transfer-encoding', 'content-encoding', 'content-length'):
                        self.send_header(key, val)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                data = resp.read()
                try:
                    self.wfile.write(data)
                except: pass
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f'Proxy error: {e}'.encode())

if __name__ == '__main__':
    os.chdir(DIR)
    # 主端口 8924（本机访问）
    main_server = socketserver.ThreadingTCPServer(('0.0.0.0', 8924), ProxyHandler)
    # 尝试额外监听 8094（对外可访问端口），被占就跳过
    try:
        ext_server = socketserver.ThreadingTCPServer(('0.0.0.0', 8094), ProxyHandler)
        import threading
        t = threading.Thread(target=ext_server.serve_forever, daemon=True)
        t.start()
        print(f'Listening on 8924 + 8094 (external) - multi-threaded')
    except:
        print(f'Listening on 8924 - multi-threaded (8094 in use)')
    print(f'API proxy to {API_HOST}')
    main_server.serve_forever()
