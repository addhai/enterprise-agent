"""知识库文件编码验证与标准化：确保 data/docs/ 下所有 .md 均为 UTF-8

检测逻辑：
    1. 读取原始字节，检查 BOM（UTF-8 BOM / UTF-16 LE/BE）
    2. 无 BOM 时尝试严格 UTF-8 解码；失败则按 GBK 回退判定
    3. 非 UTF-8（或带 BOM）的文件原地重写为无 BOM 的 UTF-8
"""

import sys
from pathlib import Path

DOCS_DIR = Path(__file__).parent.parent / "data" / "docs"


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gbk")
        return "gbk"
    except UnicodeDecodeError:
        return "unknown"


def main():
    files = sorted(DOCS_DIR.glob("*.md"))
    print(f"Found {len(files)} markdown files in {DOCS_DIR}\n")
    changed = 0
    for f in files:
        raw = f.read_bytes()
        enc = detect_encoding(raw)
        status = "OK"
        if enc != "utf-8":
            text = raw.decode(enc if enc != "unknown" else "utf-8", errors="replace")
            f.write_bytes(text.encode("utf-8"))
            status = f"CONVERTED ({enc} -> utf-8)"
            changed += 1
        print(f"  {f.name:<40} {enc:<10} {status}")
    print(f"\nDone. {changed} file(s) converted, {len(files) - changed} already UTF-8.")


if __name__ == "__main__":
    sys.exit(main())
