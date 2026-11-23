#!/usr/bin/env python3
"""Render the Sentinel demo video: terminal-style screencast with real tx data.

Generates PNG frames with PIL and assembles them with ffmpeg.
Output: /root/sentinel-reactive/demo/sentinel_demo.mp4 (~2:20, 1280x720).
"""
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = 12
OUT_DIR = "/root/sentinel-reactive/demo/frames"
OUT_MP4 = "/root/sentinel-reactive/demo/sentinel_demo.mp4"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
FG = (201, 209, 217)
DIM = (110, 118, 129)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
BLUE = (88, 166, 255)
PURPLE = (188, 140, 255)

f16 = ImageFont.truetype(MONO, 16)
f18 = ImageFont.truetype(MONO, 18)
f20 = ImageFont.truetype(MONO, 20)
f20b = ImageFont.truetype(MONO_B, 20)
f28b = ImageFont.truetype(MONO_B, 28)
f40b = ImageFont.truetype(SANS_B, 40)
f24b = ImageFont.truetype(SANS_B, 24)

os.makedirs(OUT_DIR, exist_ok=True)

frame_idx = 0


def new_frame():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # top bar
    d.rectangle([0, 0, W, 42], fill=PANEL)
    d.ellipse([20, 15, 32, 27], fill=RED)
    d.ellipse([44, 15, 56, 27], fill=YELLOW)
    d.ellipse([68, 15, 80, 27], fill=GREEN)
    d.text((100, 12), "sentinel-agent — zsh", font=f18, fill=DIM)
    d.text((W - 260, 12), "Reactive Omni Buildathon", font=f16, fill=DIM)
    return img, d


def term_line(d, y, prompt, text, color=FG):
    if prompt:
        d.text((40, y), prompt, font=f20, fill=GREEN)
        x = 40 + len(prompt) * 12
    else:
        x = 40
    d.text((x, y), text, font=f20, fill=color)


def emit(scene_name, img):
    global frame_idx
    img.save(f"{OUT_DIR}/f{frame_idx:05d}.png")
    frame_idx += 1


def hold(img, seconds):
    for _ in range(int(seconds * FPS)):
        emit("", img)


def typewriter(lines, cps=28, hold_last=1.5):
    """lines: list of (prompt, text, color). Types them one by one."""
    done = []
    total_chars = sum(len(t) for _, t, _ in lines)
    chars_done = 0
    # pre-render completed lines progressively
    li = 0
    for prompt, text, color in lines:
        shown = 0
        while shown <= len(text):
            img, d = new_frame()
            y = 70
            for p2, t2, c2 in done:
                term_line(d, y, p2, t2, c2)
                y += 30
            term_line(d, y, prompt, text[:shown], color)
            # blinking cursor
            cx = 40 + (len(prompt or "") + shown) * 12
            if (frame_idx // 4) % 2 == 0:
                d.rectangle([cx, y + 2, cx + 10, y + 22], fill=FG)
            emit("", img)
            shown += 2
        done.append((prompt, text, color))
    # final full frame held
    img, d = new_frame()
    y = 70
    for p2, t2, c2 in done:
        term_line(d, y, p2, t2, c2)
        y += 30
    hold(img, hold_last)


def title_scene():
    img, d = new_frame()
    d.text((90, 200), "SENTINEL", font=f40b, fill=FG)
    d.text((92, 260), "AI Risk Responder on Reactive Network", font=f24b, fill=BLUE)
    d.text((92, 330), "Reactive Omni Buildathon — Track: Reactive Meets AI", font=f20, fill=DIM)
    d.text((92, 420), "oracle event  →  reactive pre-filter  →  local LLM  →  on-chain decision  →  callback", font=f18, fill=GREEN)
    hold(img, 4)


def arrow(d, x1, y1, x2, y2, color, width=3):
    d.line([x1, y1, x2, y2], fill=color, width=width)
    # arrowhead
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    for s in (+1, -1):
        d.line([x2, y2, x2 - 12 * math.cos(ang + s * 0.5),
                y2 - 12 * math.sin(ang + s * 0.5)], fill=color, width=width)


def box(d, x, y, w, h, title, lines, title_color, body_color=FG):
    d.rounded_rectangle([x, y, x + w, y + h], 10, fill=PANEL,
                        outline=title_color, width=2)
    d.text((x + 14, y + 10), title, font=f20b, fill=title_color)
    yy = y + 44
    for ln in lines:
        d.text((x + 14, yy), ln, font=f16, fill=body_color)
        yy += 24


def arch_scene():
    # frames 1..18: draw boxes one by one, then arrows, then agent box
    steps = []

    def base():
        img, d = new_frame()
        return img, d

    # step 1: three chain boxes
    img, d = base()
    box(d, 40, 80, 340, 210, "BASE SEPOLIA (84532)",
        ["MockOracle", "setPrice()", "PriceUpdated", "", "origin feed"], BLUE)
    box(d, 470, 80, 340, 260, "REACTIVE LASNA (5318007)",
        ["SentinelReactive", "EMA pre-filter", "AnomalyDetected", "submitDecision()",
         "requestCallbackV_1_0", "SYSTEM 0x8888…8888"], PURPLE)
    box(d, 900, 80, 340, 210, "BASE SEPOLIA (84532)",
        ["SentinelDestination", "AbstractCallback", "executeDecision()", "", "protective action"], GREEN)
    emit("", img)
    img2 = img.copy()
    hold(img2, 1.5)

    # step 2: arrows
    img, d = base()
    box(d, 40, 80, 340, 210, "BASE SEPOLIA (84532)",
        ["MockOracle", "setPrice()", "PriceUpdated", "", "origin feed"], BLUE)
    box(d, 470, 80, 340, 260, "REACTIVE LASNA (5318007)",
        ["SentinelReactive", "EMA pre-filter", "AnomalyDetected", "submitDecision()",
         "requestCallbackV_1_0", "SYSTEM 0x8888…8888"], PURPLE)
    box(d, 900, 80, 340, 210, "BASE SEPOLIA (84532)",
        ["SentinelDestination", "AbstractCallback", "executeDecision()", "", "protective action"], GREEN)
    # event arrow: oracle -> RC
    arrow(d, 380, 150, 470, 150, GREEN)
    d.text((395, 122), "event", font=f16, fill=GREEN)
    # agent decision arrow: agent -> RC submitDecision
    arrow(d, 640, 560, 640, 340, YELLOW)
    d.text((652, 440), "AI decision tx", font=f16, fill=YELLOW)
    # callback arrow: SYSTEM -> destination
    arrow(d, 810, 290, 900, 200, PURPLE)
    d.text((820, 230), "callback", font=f16, fill=PURPLE)
    emit("", img)
    hold(img, 1.5)

    # step 3: agent box
    img, d = base()
    box(d, 40, 80, 340, 210, "BASE SEPOLIA (84532)",
        ["MockOracle", "setPrice()", "PriceUpdated", "", "origin feed"], BLUE)
    box(d, 470, 80, 340, 260, "REACTIVE LASNA (5318007)",
        ["SentinelReactive", "EMA pre-filter", "AnomalyDetected", "submitDecision()",
         "requestCallbackV_1_0", "SYSTEM 0x8888…8888"], PURPLE)
    box(d, 900, 80, 340, 210, "BASE SEPOLIA (84532)",
        ["SentinelDestination", "AbstractCallback", "executeDecision()", "", "protective action"], GREEN)
    arrow(d, 380, 150, 470, 150, GREEN)
    d.text((395, 122), "event", font=f16, fill=GREEN)
    arrow(d, 640, 560, 640, 340, YELLOW)
    d.text((652, 440), "AI decision tx", font=f16, fill=YELLOW)
    arrow(d, 810, 290, 900, 200, PURPLE)
    d.text((820, 230), "callback", font=f16, fill=PURPLE)
    box(d, 470, 560, 340, 110, "AI AGENT (self-hosted)",
        ["listener → prompt", "local LLM (Ollama)", "decision → commit tx"], YELLOW)
    # agent listens to RC events
    arrow(d, 560, 340, 560, 560, DIM)
    d.text((430, 470), "AnomalyDetected", font=f16, fill=DIM)
    emit("", img)
    hold(img, 5)


def oracle_scene():
    typewriter([
        ("$ ", 'cast send 0x6cb2…BA42 "setPrice(uint256)" 2000 --rpc-url sepolia.base.org', FG),
        ("  ", "status: 1  ✅ price seeded", DIM),
        ("$ ", 'cast send 0x6cb2…BA42 "setPrice(uint256)" 1995 --rpc-url sepolia.base.org', FG),
        ("  ", "status: 1  ✅ EMA baseline forming…", DIM),
        ("$ ", 'cast send 0x6cb2…BA42 "setPrice(uint256)" 980  --rpc-url sepolia.base.org', FG),
        ("  ", "status: 1  💥 CRASH: 980 vs EMA 1247  (-21.4%)", RED),
    ], hold_last=2.5)


def reactive_scene():
    typewriter([
        ("$ ", "cast logs SentinelReactive --rpc-url lasna-rpc.rnk.dev", FG),
        ("  ", "event AnomalyDetected(", BLUE),
        ("      ", "eventId:      3", FG),
        ("      ", "price:        980", RED),
        ("      ", "ema:          1247", FG),
        ("      ", "deviationBps: 2141   ← band 1200 bps breached", YELLOW),
        ("  ", ")  emitted in reactive tx — react() executed by SYSTEM", DIM),
        ("$ ", "cast call RC 'eventsSeen()(uint256)'  →  4   # all origin events seen", FG),
    ], hold_last=2.5)


def agent_scene():
    typewriter([
        ("$ ", "python3 agent/sentinel_agent.py 0x6cb2…BA42", FG),
        ("[agent] ", "watching 0x6cb2…BA42 on lasna-rpc.rnk.dev", DIM),
        ("[agent] ", "anomaly #3 price=980 ema=1247 dev=2141bps", YELLOW),
        ("[agent] ", "prompt → local LLM (ollama qwen2.5:0.5b, 100% self-hosted)", DIM),
        ("[agent] ", '{"action": "ALERT", "confidence": 100,', PURPLE),
        ("         ", ' "reason": "price anomaly with a sharp drop"}', PURPLE),
        ("[agent] ", "decision: ALERT  conf=100  model=1963ms", GREEN),
    ], hold_last=2.5)


def commit_scene():
    typewriter([
        ("$ ", "cast send RC 'submitDecision(uint256,uint8,bytes32,uint64)' …", FG),
        ("  ", "eventId:  3", FG),
        ("  ", "action:   2 (ALERT)", RED),
        ("  ", "decHash:  0xc81a6dabcf0dc16b71651c2eff523f0bd32837c…", FG),
        ("  ", "latency:  1963 ms  ← model timing committed on-chain", YELLOW),
        ("  ", "tx: 0xcc3ffe646c618a61c0d6ead8a4adefcfc7ae8a6577…", GREEN),
        ("  ", "✅ DecisionCommitted + CallbackDispatched on Lasna", GREEN),
    ], hold_last=2.5)


def callback_scene():
    typewriter([
        ("$ ", "cast logs SentinelDestination --rpc-url sepolia.base.org", FG),
        ("  ", "event DecisionExecuted(", BLUE),
        ("      ", "reactiveContract: 0x6cb2…BA42", FG),
        ("      ", "eventId:          3", FG),
        ("      ", "action:           ALERT", RED),
        ("      ", "decisionHash:     0xc81a6dab…  ✅ matches commit", GREEN),
        ("      ", "modelLatencyMs:   1963", FG),
        ("      ", "exposureAfter:    5000 bps   (was 10000)", YELLOW),
        ("  ", ")  tx: 0x968acf380d9578c3ff4695f7b40d13c93fadcee…", GREEN),
        ("$ ", "cast call DEST 'exposureBps()(uint256)'  →  5000", FG),
        ("  ", "✅ AI decision executed on destination chain in ~2s", GREEN),
    ], hold_last=3)


def closing_scene():
    img, d = new_frame()
    lines = [
        ("SENTINEL — every hop is a verifiable transaction", f24b, FG),
        ("", f18, FG),
        ("MockOracle        0x6cb2896ea1a58277F4F62b5c7F4d54235f25BA42 (Base Sepolia)", f18, FG),
        ("SentinelReactive  0x6cb2896ea1a58277F4F62b5c7F4d54235f25BA42 (Lasna)", f18, FG),
        ("SentinelDestin.   0x146602dE80026F4442DE45D30071227130a1da3f (Base Sepolia)", f18, FG),
        ("", f18, FG),
        ("All contracts verified on Sourcify — loop verified on-chain", f18, GREEN),
        ("github.com/Alfonova-Node/sentinel-reactive", f18, BLUE),
    ]
    y = 180
    for text, font, color in lines:
        d.text((80, y), text, font=font, fill=color)
        y += 44
    hold(img, 6)


title_scene()
arch_scene()
oracle_scene()
reactive_scene()
agent_scene()
commit_scene()
callback_scene()
closing_scene()

# assemble with ffmpeg
subprocess.run([
    "/root/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg", "-y",
    "-framerate", str(FPS), "-i", f"{OUT_DIR}/f%05d.png",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
    OUT_MP4,
], check=True, capture_output=True)
print("frames:", frame_idx)
print("duration:", frame_idx / FPS, "s")
print("size:", os.path.getsize(OUT_MP4))
