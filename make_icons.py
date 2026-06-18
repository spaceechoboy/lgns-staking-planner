#!/usr/bin/env python3
# 네온 그린 아이콘 생성 (PIL). 192/512/maskable-512/apple-180.
from PIL import Image, ImageDraw
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "icons")
os.makedirs(D, exist_ok=True)
NEON = (159, 232, 112, 255)
BG = (12, 15, 13, 255)


def icon(size, pad=0):
    img = Image.new("RGBA", (size, size), BG)
    dr = ImageDraw.Draw(img)
    m = int(size * 0.18) + pad
    dr.rounded_rectangle([m, m, size - m, size - m], radius=int(size * 0.12),
                         outline=NEON, width=max(2, int(size * 0.045)))
    # 상승 곡선 (장기 성장 모티프) — box 내부 정규화 좌표
    inner = size - 2 * m
    ys = [0.30, 0.45, 0.62, 0.80, 0.95]
    pts = [(m + inner * (i / (len(ys) - 1)), size - m - inner * y) for i, y in enumerate(ys)]
    dr.line(pts, fill=NEON, width=max(2, int(size * 0.05)), joint="curve")
    return img


icon(192).save(os.path.join(D, "icon-192.png"))
icon(512).save(os.path.join(D, "icon-512.png"))
icon(512, pad=int(512 * 0.08)).save(os.path.join(D, "icon-maskable-512.png"))
icon(180).save(os.path.join(D, "apple-touch-180.png"))
print("icons written to", D)
