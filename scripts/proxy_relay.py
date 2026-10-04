#!/usr/bin/env python3
"""宿主机代理转发器（仅用于本机 docker 构建/运行绕过 Clash 仅监听回环的限制）。

为什么需要它：
- 用户代理客户端（Clash 等）默认只监听 127.0.0.1:PORT，不监听 Docker 网关口。
- Docker 容器经 host.docker.internal（=192.168.65.254 等网关 IPv4）访问宿主机，
  连 127.0.0.1 自然连不上 -> Connection refused。
- 本转发器监听 0.0.0.0:<listen_port>（不与 Clash 的 7890 冲突，用 7891），
  把每个 TCP 连接原样转发到 127.0.0.1:<target_port>（Clash），实现「容器能出网」。

用法：
  python scripts/proxy_relay.py [listen_host] [listen_port] [target_host] [target_port]
默认：0.0.0.0 7891 127.0.0.1 7890

注意：仅做字节透传（TCP tunnel），完美兼容 HTTP CONNECT（HTTPS 代理）与 HTTP 代理。

安全提示（务必先读）：
- 监听 0.0.0.0 意味着**同一局域网内的其他设备也能通过这个端口借用你的代理**。
  仅在受信任的内网、或临时排查网络问题时使用；用完请 Ctrl+C 关闭。
- 若只想让本机与容器通信，可显式传 Docker 网关地址替代 0.0.0.0：
  `python scripts/proxy_relay.py 192.168.65.254 7891 127.0.0.1 7890`
- 本脚本不做任何认证，不适合长期常驻。
"""

import contextlib
import socket
import sys
import threading

# S104：绑定 0.0.0.0 是本脚本的设计意图 —— 必须监听 Docker 网关可达的
# 地址，容器才能连上。默认参数仅供本机临时排查使用，见上方安全提示。
LISTEN_HOST = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"  # noqa: S104
LISTEN_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 7891
TARGET_HOST = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
TARGET_PORT = int(sys.argv[4]) if len(sys.argv) > 4 else 7890


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        # 连接被对端重置是转发器的常态，不是错误
        pass
    finally:
        for s in (src, dst):
            with contextlib.suppress(OSError):
                s.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                s.close()


def _handle(client: socket.socket) -> None:
    try:
        upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=15)
    except OSError as exc:
        print(f"[relay] upstream connect failed: {exc}")
        with contextlib.suppress(OSError):
            client.close()
        return
    # 双向透传：client<->upstream
    t = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
    t.start()
    _pipe(client, upstream)


def main() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(128)
    print(
        f"[relay] listening on {LISTEN_HOST}:{LISTEN_PORT}"
        f" -> {TARGET_HOST}:{TARGET_PORT}"
    )
    try:
        while True:
            conn, _addr = srv.accept()
            threading.Thread(target=_handle, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        print("[relay] shutting down")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
