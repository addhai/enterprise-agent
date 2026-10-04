#!/usr/bin/env python3
"""基准脚本共用的入口地址校验。

为什么需要它：
`urllib.request.urlopen` 默认接受 `file:` / `ftp:` 等任意协议。基准脚本的
`--base-url` 由操作者在命令行传入，一旦误传（例如 `--base-url file:///etc`），
后续拼出的路径会被当成本地文件读取，测出「延迟 0.2ms」这种毫无意义的数字，
还可能把本地文件内容回显到结果里。

在 `main()` 里统一校验一次协议，比在每个 `urlopen` 上加 `noqa` 更能说明意图：
本目录下的脚本只允许打 HTTP(S)，其他协议一律拒绝。

用法：
    from _endpoint import require_http_url
    require_http_url(args.base_url, "--base-url")
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

#: 允许的协议。基准脚本只打本地/内网 HTTP 服务，不接受 file: / ftp: 等。
ALLOWED_SCHEMES = ("http", "https")


def require_http_url(url: str, flag_name: str = "url") -> str:
    """校验 url 是 http(s) 地址，非法则直接退出。

    Args:
        url: 待校验的地址。
        flag_name: 出错时提示用的参数名，便于用户知道是哪个参数传错了。

    Returns:
        原样返回 url，方便写成 `base_url = require_http_url(args.base_url)`。

    Raises:
        SystemExit: 协议不在白名单内，或缺少主机名时打印错误并退出（码 2）。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        print(
            f"[error] {flag_name} 只支持 {'/'.join(ALLOWED_SCHEMES)} 协议，"
            f"收到 {parsed.scheme or '(空)'}：{url}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not parsed.netloc:
        print(f"[error] {flag_name} 缺少主机名：{url}", file=sys.stderr)
        raise SystemExit(2)
    return url


if __name__ == "__main__":
    # 自检：python _endpoint.py http://localhost:8000 file:///etc/passwd
    for candidate in sys.argv[1:] or ["http://localhost:8000", "file:///etc/passwd"]:
        try:
            result = require_http_url(candidate)
        except SystemExit as exc:
            print(f"  REJECT({exc.code}) {candidate}")
        else:
            print(f"  ACCEPT {result}")
