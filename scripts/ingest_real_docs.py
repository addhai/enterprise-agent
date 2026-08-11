"""灌入真实知识库文档，让 RAG 真正命中。

流程：
  1. 用 admin 账号登录拿 token
  2. 新建一个专用知识库（或复用同名已有）
  3. 遍历 data/docs/*.md，按 source_type=text 调用
     POST /admin/knowledge/{kb_id}/documents
     —— 该端点在 server 进程内真正调用 embedder 向量化，并持久化到 ./chroma_data
  4. 打印每篇入库结果与最终统计

说明：
  - 检索只按 tenant_id 隔离（agent 的 search_knowledge_base 不含 kb_id 过滤），
    灌进 default 租户即可被对话命中。
  - embedding 走 .env 里的 OPENAI_API_KEY（阿里云百炼兼容接口），
    本脚本只在本地触发，密钥不上公网，符合安全红线。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "docs"
KB_NAME = "CloudSync产品文档库"
ADMIN = ("admin", "admin123")


def _req(method: str, ep: str, token: str | None = None, data: dict | None = None,
         timeout: int = 180) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(BASE + ep, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def main() -> None:
    t0 = time.time()
    # 1. 登录
    st, body = _req("POST", "/auth/login", data={"username": ADMIN[0], "password": ADMIN[1]})
    assert st == 200 and "token" in body, f"登录失败 {st} {body}"
    token = body["token"]
    print(f"[OK] 登录 admin 成功 (耗时 {time.time()-t0:.1f}s)")

    # 2. 取或建知识库
    _, kb_list = _req("GET", "/admin/knowledge", token=token)
    existing = next((k for k in kb_list.get("knowledge_bases", [])
                     if k.get("name") == KB_NAME), None)
    if existing:
        kb_id = existing["id"]
        print(f"[OK] 复用已有知识库 {KB_NAME} (id={kb_id})")
    else:
        st, kb = _req("POST", "/admin/knowledge", token=token, data={
            "name": KB_NAME,
            "description": "CloudSync 产品真实文档（账户/API/计费/安全/迁移/SDK/Webhook 等）",
            "kb_version": "standard",
            "kb_type": "document",
            "similarity_threshold": 0.2,
            "weight": 1.0,
        })
        assert st == 200 and "kb" in kb, f"建库失败 {st} {kb}"
        kb_id = kb["kb"]["id"]
        print(f"[OK] 新建知识库 {KB_NAME} (id={kb_id})")

    # 3. 逐篇灌入
    md_files = sorted(DOCS_DIR.glob("*.md"))
    md_files = [f for f in md_files if f.name != ".gitkeep"]
    print(f"\n== 待入库文档 {len(md_files)} 篇 ==\n")
    ok = fail = 0
    for f in md_files:
        content = f.read_text(encoding="utf-8")
        title = f.stem
        st, resp = _req("POST", f"/admin/knowledge/{kb_id}/documents", token=token, data={
            "source_type": "text",
            "title": title,
            "content": content,
            "upload_method": "batch",
        }, timeout=240)
        if st == 200 and resp.get("success"):
            doc = resp.get("document", {})
            ok += 1
            print(f"  [OK] {title:<28} chunks={doc.get('chunk_count')} status={doc.get('status')}")
        else:
            fail += 1
            print(f"  [XX] {title:<28} -> {st} {str(resp)[:120]}")

    # 4. 统计
    _, kb_list = _req("GET", "/admin/knowledge", token=token)
    kb_now = next((k for k in kb_list.get("knowledge_bases", []) if k["id"] == kb_id), {})
    print(f"\n=== 入库完成: {ok} 成功 / {fail} 失败 (总耗时 {time.time()-t0:.1f}s) ===")
    print(f"知识库 {KB_NAME}: 文档数={kb_now.get('document_count')} 切片数={kb_now.get('total_chunks')}")
    print("下一步验证：POST /admin/knowledge/%s/hit_test 或对话测试。" % kb_id)


if __name__ == "__main__":
    main()
