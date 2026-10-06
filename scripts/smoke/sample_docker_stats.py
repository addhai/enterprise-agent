#!/usr/bin/env python3
"""生产容器资源采样器。

在索引重建等重负载操作期间后台运行，按固定间隔通过 docker stats
采集 prod 容器 CPU/内存，写 CSV 供事后分析峰值与资源竞争。

用法（PowerShell 后台）:
    python scripts/smoke/sample_docker_stats.py --duration 600 --out rebuild_stats.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import subprocess
import sys
import time


def sample_once() -> list[dict]:
    """采一次 docker stats --no-stream，返回逐容器指标行"""
    fmt = "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}"
    # 固定参数数组调用受控 docker CLI，无 shell 注入面
    proc = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "stats",
            "--no-stream",
            "--format",
            fmt,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        print(f"docker stats 失败: {proc.stderr.strip()}", file=sys.stderr)
        return []
    rows: list[dict] = []
    now = dt.datetime.now().isoformat(timespec="seconds")
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        name, cpu, mem_usage, mem_perc = parts
        rows.append(
            {
                "ts": now,
                "name": name,
                "cpu_pct": cpu.replace("%", ""),
                "mem_usage": mem_usage,
                "mem_perc": mem_perc.replace("%", ""),
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="采集 docker stats 到 CSV")
    ap.add_argument("--duration", type=int, default=600, help="采样总时长秒")
    ap.add_argument("--interval", type=int, default=10, help="采样间隔秒")
    ap.add_argument(
        "--out",
        required=True,
        help="CSV 输出路径（已存在则覆盖）",
    )
    ap.add_argument(
        "--filter",
        default="prod-",
        help="容器名前缀过滤，默认 prod-（留空采全部）",
    )
    args = ap.parse_args()

    end = time.monotonic() + args.duration
    n = 0
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["ts", "name", "cpu_pct", "mem_usage", "mem_perc"]
        )
        writer.writeheader()
        while time.monotonic() < end:
            rows = sample_once()
            for r in rows:
                if args.filter and not r["name"].startswith(args.filter):
                    continue
                writer.writerow(r)
                n += 1
            f.flush()
            time.sleep(args.interval)

    print(f"采样结束：{n} 行 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
