"""Draws the ImageLoom app icon (1024x1024 PNG) with Pillow: no external artwork needed."""
import sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 1024 * 3                       # supersampling for smooth edges
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
# macOS icon grid: the squircle fills ~80% of the canvas
m = int(S * 0.098); r = int(S * 0.18)
bg = Image.new("RGBA", (S, S))
px = bg.load()
c0, c1, c2 = (62, 76, 255), (140, 72, 255), (255, 92, 168)
for y in range(m, S - m):
    for x in range(m, S - m):
        t = ((x - m) + (y - m)) / (2 * (S - 2 * m))
        col = lerp(c0, c1, t * 2) if t < 0.5 else lerp(c1, c2, (t - 0.5) * 2)
        px[x, y] = col + (255,)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((m, m, S - m, S - m), radius=r, fill=255)
img.paste(bg, (0, 0), mask)

# soft highlight on the upper half
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(hl).ellipse((m - S * 0.2, m - S * 0.55, S - m + S * 0.2, S * 0.5), fill=(255, 255, 255, 38))
img = Image.alpha_composite(img, Image.composite(hl, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))

d = ImageDraw.Draw(img)
# photo frame
fx0, fy0, fx1, fy1 = int(S * 0.255), int(S * 0.285), int(S * 0.745), int(S * 0.715)
d.rounded_rectangle((fx0, fy0, fx1, fy1), radius=int(S * 0.045), fill=(255, 255, 255, 245))
inner = (fx0 + int(S * 0.022), fy0 + int(S * 0.022), fx1 - int(S * 0.022), fy1 - int(S * 0.022))
sky = Image.new("RGBA", (inner[2] - inner[0], inner[3] - inner[1]))
sp = sky.load()
for y in range(sky.height):
    t = y / sky.height
    col = lerp((255, 176, 120), (120, 110, 255), 1 - t)
    for x in range(sky.width):
        sp[x, y] = col + (255,)
smask = Image.new("L", sky.size, 0)
ImageDraw.Draw(smask).rounded_rectangle((0, 0, sky.width - 1, sky.height - 1), radius=int(S * 0.028), fill=255)
img.paste(sky, (inner[0], inner[1]), smask)
d = ImageDraw.Draw(img)
w, h = sky.size
# sun
sx, sy, sr = inner[0] + int(w * 0.72), inner[1] + int(h * 0.30), int(h * 0.13)
d.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=(255, 244, 214, 255))
# mountains (clipped to the picture)
layer = Image.new("RGBA", sky.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
ld.polygon([(0, h), (0, int(h * 0.74)), (int(w * 0.27), int(h * 0.40)), (int(w * 0.46), int(h * 0.66)), (int(w * 0.62), int(h * 0.50)), (w, int(h * 0.78)), (w, h)], fill=(58, 52, 140, 255))
ld.polygon([(0, h), (int(w * 0.18), int(h * 0.78)), (int(w * 0.36), int(h * 0.58)), (int(w * 0.62), int(h * 0.86)), (int(w * 0.80), int(h * 0.68)), (w, int(h * 0.88)), (w, h)], fill=(34, 30, 98, 255))
ld.polygon([(int(w * 0.27), int(h * 0.40)), (int(w * 0.21), int(h * 0.50)), (int(w * 0.27), int(h * 0.47)), (int(w * 0.31), int(h * 0.52))], fill=(255, 255, 255, 235))
img.paste(layer, (inner[0], inner[1]), ImageChops.multiply(layer.getchannel("A"), smask))
d = ImageDraw.Draw(img)

# sparkle (AI cue), top right of the frame
def sparkle(cx, cy, R, fill):
    k = 0.2
    pts = [(cx, cy - R), (cx + R * k, cy - R * k), (cx + R, cy), (cx + R * k, cy + R * k), (cx, cy + R), (cx - R * k, cy + R * k), (cx - R, cy), (cx - R * k, cy - R * k)]
    d.polygon(pts, fill=fill)
sparkle(int(S * 0.742), int(S * 0.258), int(S * 0.115), (255, 255, 255, 255))
sparkle(int(S * 0.842), int(S * 0.368), int(S * 0.052), (255, 255, 255, 235))
sparkle(int(S * 0.655), int(S * 0.215), int(S * 0.04), (255, 255, 255, 220))

# drop shadow under the squircle (kept inside the canvas)
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((m, m + int(S * 0.012), S - m, S - m + int(S * 0.012)), radius=r, fill=(20, 10, 60, 90))
shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.012))
out = Image.alpha_composite(shadow, img).resize((1024, 1024), Image.LANCZOS)
out.save(sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png")
print("icon written")
