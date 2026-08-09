"""生成 demo GIF：用真实 WS 对话（ws_capture.py 抓取的 a1）渲染 AI 客服工作台界面动画。

数据驱动：读取 scripts/.cache/ws_reply.json 的 q1/a1，用户问题与 AI 回复均来自真实后端对话，
不再硬编码文案。若 AI 回复中出现了工单 ID（TKT-xxxx），则在气泡下方高亮工单卡片，体现工具调用。

用法：
  1) python scripts/ws_capture.py      # 生成真实对话素材
  2) python scripts/make_demo_gif.py   # 读取素材渲染 demo.gif
"""
import json
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT = os.path.join(HERE, "..", "demo.gif")
W, H = 900, 640


def _font(size):
    """优先中文字体，跨平台兜底，避免 Windows 之外崩溃。"""
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

# 真实对话内容（由 ws_capture.py 抓取，落盘 scripts/.cache/ws_reply.json）
with open(os.path.join(CACHE, "ws_reply.json"), encoding="utf-8") as f:
    _data = json.load(f)
USER_Q = _data["q1"]
AI_REPLY = _data["a1"]
_m = re.search(r"TKT-[0-9A-Fa-f]+", AI_REPLY)
TICKET_ID = _m.group(0) if _m else None

COL = {
    "bg": (245, 246, 248), "bar": (31, 42, 68), "bar_text": (235, 240, 250),
    "user": (59, 130, 246), "user_text": (255, 255, 255),
    "ai": (255, 255, 255), "ai_text": (33, 37, 41), "ai_border": (220, 224, 230),
    "avatar": (37, 99, 235), "card": (232, 240, 254), "card_border": (150, 190, 250),
    "card_title": (23, 78, 178), "input_bg": (255, 255, 255), "muted": (120, 128, 140),
}


def wrap(text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if font.getlength(cur + ch) > max_w:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def round_rect(draw, box, r, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def draw_scene(draw, user_shown, ai_text, typing, show_card):
    draw.rectangle([0, 0, W, H], fill=COL["bg"])
    draw.rectangle([0, 0, W, 56], fill=COL["bar"])
    draw.text((20, 16), "CloudSync 智能客服工作台", font=TITLE, fill=COL["bar_text"])
    draw.ellipse([W - 150, 18, W - 138, 30], fill=(46, 204, 113))
    draw.text((W - 132, 17), "在线 · 工具调用", font=SMALL, fill=COL["bar_text"])
    top = 76
    if user_shown:
        u_lines = wrap(user_shown, BODY, 560)
        bh = len(u_lines) * 24 + 20
        bx = W - 30 - (max(BODY.getlength(l) for l in u_lines) + 28)
        by = top
        round_rect(draw, [bx, by, W - 30, by + bh], 14, COL["user"])
        ty = by + 12
        for l in u_lines:
            draw.text((bx + 14, ty), l, font=BODY, fill=COL["user_text"]); ty += 24
        top = by + bh + 18
    if ai_text or typing:
        ax, ay = 24, top
        draw.ellipse([ax, ay, ax + 34, ay + 34], fill=COL["avatar"])
        draw.text((ax + 9, ay + 7), "AI", font=SMALL, fill=(255, 255, 255))
        ai_lines = wrap(ai_text, BODY, 560) if ai_text else []
        if typing:
            ai_lines = ai_lines + ["", "● ● ●"]
        card_h = 52 if (show_card and TICKET_ID) else 0
        bh = len(ai_lines) * 24 + 22 + card_h
        bx = ax + 46
        bw = W - bx - 30
        round_rect(draw, [bx, ay, bx + bw, ay + bh], 14, COL["ai"], outline=COL["ai_border"], width=1)
        ty = ay + 12
        for l in ai_lines:
            draw.text((bx + 14, ty), l, font=BODY, fill=COL["ai_text"]); ty += 24
        if show_card and TICKET_ID:
            cy = ty + 2
            round_rect(draw, [bx + 12, cy, bx + bw - 12, cy + 44], 10, COL["card"], outline=COL["card_border"], width=1)
            draw.text((bx + 24, cy + 8), f"工单卡片 {TICKET_ID}", font=SMALL, fill=COL["card_title"])
            draw.text((bx + 24, cy + 26), "open · 已创建 · 工具调用落库", font=SMALL, fill=COL["muted"])
    draw.rectangle([0, 572, W, H], fill=(228, 231, 237))
    round_rect(draw, [20, 584, W - 110, 620], 16, COL["input_bg"], outline=COL["ai_border"], width=1)
    draw.text((36, 595), "输入消息，Enter 发送…", font=BODY, fill=COL["muted"])
    round_rect(draw, [W - 96, 584, W - 30, 620], 16, COL["user"])
    draw.text((W - 80, 595), "发送", font=BODY, fill=COL["user_text"])


def make():
    frames = []
    for _ in range(3):
        img = Image.new("RGB", (W, H), COL["bg"]); d = ImageDraw.Draw(img)
        draw_scene(d, "", "", False, False); frames.append(img)
    step = 3
    for i in range(0, len(USER_Q) + 1, step):
        img = Image.new("RGB", (W, H), COL["bg"]); d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q[:i], "", False, False); frames.append(img)
    for _ in range(3):
        img = Image.new("RGB", (W, H), COL["bg"]); d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, "", True, False); frames.append(img)
    for i in range(0, len(AI_REPLY) + 1, step):
        done = i >= len(AI_REPLY)
        img = Image.new("RGB", (W, H), COL["bg"]); d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, AI_REPLY[:i], False, done); frames.append(img)
    for _ in range(4):
        img = Image.new("RGB", (W, H), COL["bg"]); d = ImageDraw.Draw(img)
        draw_scene(d, USER_Q, AI_REPLY, False, True); frames.append(img)
    frames[0].save(
        OUT, save_all=True, append_images=frames[1:],
        duration=80, loop=0, disposal=2,
    )
    print("WROTE", os.path.abspath(OUT), "frames=", len(frames), "ticket=", TICKET_ID)


if __name__ == "__main__":
    make()
