import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
KEYWORD = os.environ.get("FEISHU_KEYWORD", "告警")
PORT = int(os.environ.get("ADAPTER_PORT", "8060"))


class GrafanaWebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {
                "alerts": [],
                "status": "unknown",
                "raw": raw.decode("utf-8", errors="replace"),
            }

        alerts = payload.get("alerts", [])
        status = payload.get("status", "unknown").upper()
        external_url = payload.get("externalURL", "")

        lines = [f"【{KEYWORD}】Grafana {status}，共 {len(alerts)} 条"]
        for i, a in enumerate(alerts, 1):
            labels = a.get("labels", {})
            annos = a.get("annotations", {})
            name = labels.get("alertname", labels.get("alert_name", "未命名告警"))
            sev = labels.get("severity", "warning")
            summary = annos.get("summary", "")
            desc = annos.get("description", "")
            starts = a.get("startsAt", "")
            fingerprint = a.get("fingerprint", "")
            lines.append(f"[{i}] [{sev}] {name}")
            if summary:
                lines.append(f"    {summary}")
            if desc:
                lines.append(f"    {desc}")
            if starts:
                lines.append(f"    触发: {starts}")
            if fingerprint:
                lines.append(f"    ID: {fingerprint[:12]}")
        if external_url:
            lines.append(f"面板: {external_url}")

        text = "\n".join(lines)
        feishu_body = json.dumps(
            {"msg_type": "text", "content": {"text": text}}, ensure_ascii=False
        ).encode("utf-8")

        feishu_status = 0
        feishu_resp = ""
        try:
            # S310: webhook 地址由部署时的环境变量提供，非请求输入
            req = urllib.request.Request(  # noqa: S310
                FEISHU_WEBHOOK,
                data=feishu_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                feishu_status = resp.status
                feishu_resp = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            feishu_resp = str(e)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "ok": True,
                    "alerts_received": len(alerts),
                    "feishu_status": feishu_status,
                    "feishu_response": feishu_resp[:200],
                }
            ).encode("utf-8")
        )

    def log_message(self, format, *args):
        print(f"[adapter] {args[0]}", flush=True)


if __name__ == "__main__":
    # 不打印 webhook 原文：飞书机器人 URL 本身就是凭据，
    # 截断输出仍足以让人直接向群里发消息，等同凭据泄露。
    print(
        f"[adapter] starting on 0.0.0.0:{PORT}, "
        f"webhook configured: {bool(FEISHU_WEBHOOK)}",
        flush=True,
    )
    # S104: 容器内服务必须绑 0.0.0.0 才能被 Grafana 容器访问
    HTTPServer(("0.0.0.0", PORT), GrafanaWebhookHandler).serve_forever()  # noqa: S104
