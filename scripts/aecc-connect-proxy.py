#!/usr/bin/env python3
import socket
import socketserver

ALLOWED = {("opencode.ai", 443)}

class ProxyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline().decode("utf-8", "replace").strip()
        if not line:
            return

        parts = line.split()
        if len(parts) < 3 or parts[0].upper() != "CONNECT":
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        hostport = parts[1]
        if ":" not in hostport:
            self.wfile.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return

        host, port_text = hostport.rsplit(":", 1)

        try:
            port = int(port_text)
        except ValueError:
            self.wfile.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return

        target = (host, port)

        while True:
            header = self.rfile.readline()
            if header in (b"\r\n", b"\n", b""):
                break

        if target not in ALLOWED:
            print(f"DENY {host}:{port}", flush=True)
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return

        print(f"ALLOW {host}:{port}", flush=True)

        try:
            upstream = socket.create_connection(target, timeout=15)
        except Exception:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return

        self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self.wfile.flush()

        client = self.connection
        client.setblocking(False)
        upstream.setblocking(False)

        import select

        sockets = [client, upstream]

        try:
            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 60)

                if exceptional:
                    break

                if not readable:
                    continue

                for sock in readable:
                    other = upstream if sock is client else client
                    try:
                        data = sock.recv(65536)
                    except BlockingIOError:
                        continue

                    if not data:
                        return

                    other.sendall(data)
        finally:
            upstream.close()


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ThreadingTCPServer(("0.0.0.0", 3128), ProxyHandler) as server:
        print("AECC_PROXY_READY 0.0.0.0:3128", flush=True)
        server.serve_forever()
