#!/usr/bin/env python3
"""frame_mask.py <image> (--id ID | --platform P) [-o OUT] [--tile 270x480] -- draw what the phone hides onto a frame or a
contact/storyboard sheet, for the short's routed platform (kit/platforms/frames.json). Row 6, 29 Sep 2026.

  dark + red hatch   outside the platform's VISIBLE rect: the phone crops it away (solid hatch = measured/derived, sparse = estimated)
  orange             UI overlays: header, action rail, caption/CTA (they sit on top of the video)
  green dashed       TEXT-SAFE rect; green dotted notch = the rail corner text must also clear

A 9:16 image is treated as one frame; any other image as a sheet of --tile tiles (default 270x480, storyboard.py's tile).
Library use: mask_image(PIL.Image, profile) and mask_sheet(path, profile, out, tile=(270, 480)).
"""
import argparse, os, sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "platforms"))
import platforms  # noqa: E402

W, H = 1080, 1920


def _font(px):
    for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            continue
    return ImageFont.load_default()


def mask_image(im, p, label=True):
    """Returns a new RGB image the size of `im` (any 9:16 size) with the platform's crop, overlays and text-safe drawn on."""
    im = im.convert("RGB")
    k = im.width / float(W)
    S = lambda r: [r["x0"] * k, r["y0"] * k, r["x1"] * k - 1, r["y1"] * k - 1]
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    v = p["visible"]
    dense = v["evidence"] in ("measured", "documented", "derived")
    # outside visible: darken + hatch
    outside = [(0, 0, im.width, v["y0"] * k), (0, v["y1"] * k, im.width, im.height),
               (0, v["y0"] * k, v["x0"] * k, v["y1"] * k), (v["x1"] * k, v["y0"] * k, im.width, v["y1"] * k)]
    for box in outside:
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            continue
        d.rectangle(box, fill=(0, 0, 0, 165))
        step = max(4, int((10 if dense else 22) * k * 2))
        x0, y0, x1, y1 = (int(round(c)) for c in box)
        hw, hh = max(1, x1 - x0), max(1, y1 - y0)
        hatch = Image.new("RGBA", (hw, hh), (0, 0, 0, 0))     # drawn in its own tile so the diagonals stay inside the box
        hd = ImageDraw.Draw(hatch)
        for t in range(-hh, hw + 1, step):
            hd.line([(t, hh), (t + hh, 0)], fill=(230, 40, 40, 230), width=max(1, int(3 * k)))
        ov.alpha_composite(hatch, (x0, y0))
    # overlays
    for o in p["overlays"]:
        d.rectangle(S(o), fill=(255, 140, 0, 70), outline=(255, 140, 0, 255), width=max(1, int(4 * k)))
    # text safe + notches
    ts = p["text_safe"]
    dash = max(3, int(18 * k))
    def dashed(r, fill, width, dot=False):
        x0, y0, x1, y1 = S(r)
        seg = dash if not dot else max(2, dash // 3)
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            L = max(abs(b[0] - a[0]), abs(b[1] - a[1])) or 1
            n = int(L // (2 * seg)) + 1
            for i in range(n):
                t0, t1 = (2 * i * seg) / L, min(1, (2 * i + 1) * seg / L)
                d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0), (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)],
                       fill=fill, width=width)
    dashed(ts, (40, 220, 90, 255), max(1, int(5 * k)))
    for n in ts["notches"]:
        r = {"x0": n["x0"], "y0": n["y0"], "x1": min(n["x1"], ts["x1"]), "y1": min(n["y1"], ts["y1"])}
        if r["x1"] > r["x0"] and r["y1"] > r["y0"]:
            dashed(r, (40, 220, 90, 255), max(1, int(4 * k)), dot=True)
    if label and im.width >= 200:
        f = _font(max(10, int(34 * k)))
        txt = "%s  (%s)" % (p["key"], v["evidence"])
        d.rectangle([0, im.height - int(58 * k), im.width, im.height], fill=(0, 0, 0, 200))
        d.text((int(14 * k), im.height - int(50 * k)), txt, fill=(255, 255, 255, 255), font=f)
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


def mask_sheet(path, p, out, tile=(270, 480)):
    im = Image.open(path).convert("RGB")
    tw, th = tile
    res = im.copy()
    for y in range(0, im.height - th + 1, th):
        for x in range(0, im.width - tw + 1, tw):
            t = im.crop((x, y, x + tw, y + th))
            if sum(__import__("PIL.ImageStat", fromlist=["Stat"]).Stat(t.convert("L")).mean) < 6:   # black padding tile (ffmpeg tile=)
                continue
            res.paste(mask_image(t, p, label=False), (x, y))
    res.save(out, quality=90)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--id"); ap.add_argument("--platform"); ap.add_argument("-o", "--out")
    ap.add_argument("--tile", default="270x480")
    a = ap.parse_args()
    name = a.platform or (platforms.routed_platform(a.id) if a.id else None)
    if not name:
        sys.exit("frame_mask: pass --platform, or --id of a routed short")
    p = platforms.profile(name)
    out = a.out or os.path.splitext(a.image)[0] + "-masked-%s.jpg" % p["key"]
    im = Image.open(a.image)
    if abs(im.width / float(im.height) - W / float(H)) < 0.01:
        mask_image(im, p).save(out, quality=92)
    else:
        tw, th = (int(v) for v in a.tile.split("x"))
        mask_sheet(a.image, p, out, (tw, th))
    print(out)


if __name__ == "__main__":
    main()
