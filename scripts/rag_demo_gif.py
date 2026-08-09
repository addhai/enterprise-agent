"""生成 RAG 演示 GIF：真实 WS 对话驱动的 RAG 检索增强动画。

读取 scripts/.cache/rag_api_best.json（rag_capture.py 抓取的命中知识库术语的真实回复），
渲染「CloudSync 智能客服 · RAG 检索增强」工作台动画：用户输入 -> 知识库检索中 ->
AI 流式逐字回复 -> 引用知识片段标注。

用法：
  1) python scripts/rag_capture.py      # 抓取真实 RAG 对话
  2) python scripts/rag_demo_gif.py     # 读取素材渲染 rag_demo.gif
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT = os.path.join(HERE, "..", "rag_demo.gif")
W, H = 900, 640


def _font(size):
    for p in [r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\msyh.ttc",
              r"C:\Windows\Fonts\simsun.ttc"]:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


TITLE = _font(21)
BODY = _font(17)
SMALL = _font(14)

with open(os.path.join(CACHE, "rag_api_best.json"), encoding="utf-8") as f:
    data = json.load(f)
USER_Q = data["question"]
AI_REPLY = data["reply"]

COL = {
    "bg": (245, 246, 248), "bar": (31, 42, 68), "bar_text": (235, 240, 250),
    "user": (59, 130, 246), "user_text": (255, 255, 255),
    "ai": (255, 255, 255), "ai_text": (33, 37, 41), "ai_border": (220, 224, 230),
    "avatar": (37, 99, 235), "input_bg": (255, 255, 255), "muted": (120, 128, 140),
    "rag_tag": (22, 138, 95), "rag_tag_bg": (224, 245, 235),
}


def wrap(text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if font.getlength(cur + ch) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def round_rect(draw, box, r, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def draw_scene(draw, user_shown, ai_text, typing, phase, show_ref):
    draw.rectangle([0, 0, W, H], fill=COL["bg"])
    # 标题栏
    draw.rectangle([0, 0, W, 56], fill=COL["bar"])
    draw.text((20, 16), "CloudSync 智能客服 · RAG 检索增强", font=TITLE, fill=COL["bar_text"])
    draw.ellipse([W - 150, 18, W - 138, 30], fill=(46, 204, 113))
    draw.text((W - 132, 17), "在线 · 多租户隔离", font=SMALL, fill=COL["bar_text"])
    # 知识库检索阶段标签（仅检索中显示，固定占用 56~88 区域）
    if phase == "retrieving":
        draw.rectangle([0, 56, W, 88], fill=COL["rag_tag_bg"])
        draw.text((20, 64), "检索中：HybridRetriever（向量 + 关键词混合）正在召回知识库片段...",
                  font=SMALL, fill=COL["rag_tag"])
    # 用户气泡（固定起点 96，避免阶段切换时跳动）
    top = 96
    if user_shown:
        u_lines = wrap(user_shown, BODY, 560)
        bh = len(u_lines) * 24 + 20
        bx = W - 30 - (max(BODY.getlength(l) for l in u_lines) + 28)
        round_rect(draw, [bx, top, W - 30, top + bh], 14, COL["user"])
        ty = top + 12
        for l in u_lines:
            draw.text((bx + 14, ty), l, font=BODY, fill=COL["user_text"])
            ty += 24
        top = top + bh + 18
    # AI 头像 + 气泡
    if ai_text or typing or phase == "retrieving":
        ax, ay = 24, top
        draw.ellipse([ax, ay, ax + 34, ay + 34], fill=COL["avatar"])
        draw.text((ax + 9, ay + 7), "AI", font=SMALL, fill=(255, 255, 255))
        ai_lines = wrap(ai_text, BODY, 560) if ai_text else []
        if typing:
            ai_lines = ai_lines + ["", "● ● ●"]
        ref_h = 26 if show_ref else 0
        bh = len(ai_lines) * 24 + 22 + ref_h
        bx = ax + 46
        bw = W - bx - 30
        round_rect(draw, [bx, ay, bx + bw, ay + bh], 14, COL["ai"], outline=COL["ai_border"], width=1)
        ty = ay + 12
        for l in ai_lines:
            draw.text((bx + 14, ty), l, font=BODY, fill=COL["ai_text"])
            ty += 24
        if show_ref:
            draw.text((bx + 14, ty), "引用知识片段：api_pagination_versioning.md",
                      font=SMALL, fill=COL["rag_tag"])
    # 底部输入栏
    draw.rectangle([0, 572, W, H], fill=(228, 231, 237))
    round_rect(draw, [20, 584, W - 110, 620], 16, COL["input_bg"], outline=COL["ai_border"], width=1)
    draw.text((36, 595), "输入消息，Enter 发送…", font=BODY, fill=COL["muted"])
    round_rect(draw, [W - 96, 584, W - 30, 620], 16, COL["user"])
    draw.text((W - 80, 595), "发送", font=BODY, fill=COL["user_text"])


def make():
    frames = []
    # 1) 空界面
    for _ in range(3):
        img = Image.new("RGB", (W, H), COL["bg"])
        d = ImageDraw.Draw(img)
        draw_scene(d, "", "", False, "idle", False)
        frames.append(img)
    # 2) 用户问题逐字输入
    for i in range(0, len(USER_Q) + 1, 3):
        img = Image.new("RGB", (W, H), COL["bg"])
        d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q[:i], "", False, "idle", False)
        frames.append(img)
    # 3) 知识库检索中（体现 RAG 检索步骤）
    for _ in range(4):
        img = Image.new("RGB", (W, H), COL["bg"])
        d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, "", True, "retrieving", False)
        frames.append(img)
    # 4) AI 流式逐字回复
    for i in range(0, len(AI_REPLY) + 1, 3):
        img = Image.new("RGB", (W, H), COL["bg"])
        d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, AI_REPLY[:i], False, "reply", False)
        frames.append(img)
    # 5) 引用知识片段标注出现
    for _ in range(4):
        img = Image.new("RGB", (W, H), COL["bg"])
        d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, AI_REPLY, False, "reply", True)
        frames.append(img)
    # 6) 结尾静止
    for _ in range(4):
        img = Image.new("RGB", (W, H), COL["bg"])
        d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, AI_REPLY, False, "reply", True)
        frames.append(img)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=300, loop=0, disposal=2)
    print("WROTE", os.path.abspath(OUT), "frames=", len(frames))


if __name__ == "__main__":
    make()
