"""Chroma-key a generated product shot on flat green into a cutout PNG (alpha + despill + crop).
usage: key_green.py in.png out.png [t0 t1]"""
import sys
import numpy as np
from PIL import Image
src, dst = sys.argv[1], sys.argv[2]
t0 = float(sys.argv[3]) if len(sys.argv) > 3 else 18
t1 = float(sys.argv[4]) if len(sys.argv) > 4 else 60
im = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
r, g, b = im[..., 0], im[..., 1], im[..., 2]
green = g - np.maximum(r, b)
a = 1 - np.clip((green - t0) / (t1 - t0), 0, 1)
# despill: pull green down toward the other channels where it dominates
g2 = np.where(green > 0, np.maximum(r, b) + np.clip(green, 0, None) * 0.15 * a, g)
out = np.dstack([r, g2, b, a * 255]).clip(0, 255).astype(np.uint8)
img = Image.fromarray(out, "RGBA")
# erode alpha edge by 1px to kill the green fringe
from PIL import ImageFilter
al = img.split()[3].filter(ImageFilter.MinFilter(3))
img.putalpha(al)
bbox = img.getbbox()
img = img.crop(bbox)
img.save(dst)
print(dst, img.size, "opaque%", round((np.asarray(al) > 128).mean() * 100, 1))
