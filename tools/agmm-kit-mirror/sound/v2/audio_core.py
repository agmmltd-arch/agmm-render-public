#!/usr/bin/env python3
"""Shared measurement core for mix2.py and audio_report.py (AUDIO DESIGN SYSTEM v2).

Dependencies: system python3 + numpy (+ PIL for the PNG plot, optional). ffmpeg does decoding, K-weighting and
true peak. Laptop-safe: every ffmpeg call is `nice -n 15` with `-threads 2`, one process at a time, and decodes
are streamed in 10 s blocks so a 20-minute film never sits in memory as float PCM.

Loudness is ITU-R BS.1770-4 / EBU R128:
  K-weighting = ffmpeg highshelf(1681.97 Hz, +4.0 dB, Q 0.7072) + highpass(38.14 Hz, Q 0.5003) on each channel,
  block power = mean square per channel summed over channels, L = -0.691 + 10 log10(power).
  Blocks are 50 ms. Momentary = 400 ms (8 blocks), short-term = 3 s (60 blocks), "fast" = 200 ms (4 blocks).
  Integrated = 400 ms windows at a 100 ms step, absolute gate -70 LUFS, relative gate -10 LU.
  LRA = short-term at a 100 ms step, gates -70 / -20, p95 - p10.
selftest() checks integrated and LRA against ffmpeg's own ebur128 filter on real files.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 24000            # analysis rate (Nyquist 12 kHz covers the 2-10 kHz noise band)
HOP_S = 0.05          # 50 ms blocks
HOP = int(SR * HOP_S)  # 1200 samples
NFFT = 2048
KW = "highshelf=f=1681.974:g=3.99984:t=q:w=0.7071752,highpass=f=38.13547:t=q:w=0.5003270"
EPS = 1e-12


def ff_cmd(args):
    return ["nice", "-n", "15", "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-threads", "2"] + args


def run(cmd, check=True):
    p = subprocess.run(cmd, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s" % (p.returncode, " ".join(cmd[:12]),
                                                           p.stderr.decode("utf-8", "replace")[-1500:]))
    return p


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,channels:format=duration",
             "-of", "json", path])
    d = json.loads(p.stdout)
    a = [s for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    return {"duration": float(d.get("format", {}).get("duration") or 0.0), "has_audio": bool(a),
            "sample_rate": int(a[0]["sample_rate"]) if a else None, "channels": int(a[0]["channels"]) if a else None}


def stream_pcm(path, sr=SR, channels=2, af=None, block_s=10.0, offset_s=0.0):
    """Yield float32 blocks (n, channels) from ffmpeg. Mono sources are upmixed with -ac 2 (same signal both sides)."""
    args = []
    if offset_s > 0:
        args += ["-ss", "%.4f" % offset_s]
    args += ["-i", path, "-vn", "-map", "0:a:0"]
    if af:
        args += ["-af", af]
    args += ["-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    p = subprocess.Popen(ff_cmd(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    nbytes = int(sr * block_s) * channels * 4
    try:
        while True:
            buf = p.stdout.read(nbytes)
            if not buf:
                break
            buf = buf[: len(buf) - (len(buf) % (4 * channels))]
            yield np.frombuffer(buf, dtype=np.float32).reshape(-1, channels)
    finally:
        p.stdout.close()
        err = p.stderr.read().decode("utf-8", "replace")
        p.wait()
        if p.returncode not in (0, None):
            raise RuntimeError("ffmpeg decode failed for %s: %s" % (path, err[-800:]))


def read_pcm(path, sr=SR, channels=2, af=None):
    blocks = list(stream_pcm(path, sr, channels, af))
    return np.concatenate(blocks) if blocks else np.zeros((0, channels), np.float32)


def db(x):
    return 10.0 * np.log10(np.maximum(x, EPS))


def lufs_from_power(p):
    return -0.691 + db(p)


def _blocks(stream, hop):
    carry = None
    for blk in stream:
        if carry is not None and len(carry):
            blk = np.concatenate([carry, blk])
        n = (len(blk) // hop) * hop
        if n:
            yield blk[:n].reshape(-1, hop, blk.shape[1])
        carry = blk[n:]
    if carry is not None and len(carry):
        pad = np.zeros((hop - len(carry), carry.shape[1]), np.float32)
        yield np.concatenate([carry, pad]).reshape(1, hop, carry.shape[1])


class Features:
    """Per-50 ms-block features of one signal.

    kz[:, c]   K-weighted mean square per channel        -> loudness
    km, ks     K-weighted mid / side power               -> master-only voice/music estimates
    band_lvl   unweighted 2-10 kHz level (dBFS)          -> noise floor
    band_spec  2-10 kHz power spectrum, 4-bin groups     -> Welch flatness per pause
    sp_lvl     unweighted 300-3400 Hz level (dBFS)
    peak       sample peak per block (24 kHz decode; true peak comes from ffmpeg)
    """

    def __init__(self, path, label=None):
        self.path = path
        self.label = label or os.path.basename(path)
        kz, km, ks = [], [], []
        for b in _blocks(stream_pcm(path, af=KW), HOP):
            ms = np.mean(b.astype(np.float64) ** 2, axis=1)
            kz.append(ms)
            mid = (b[:, :, 0] + b[:, :, 1]) * 0.5
            side = (b[:, :, 0] - b[:, :, 1]) * 0.5
            km.append(np.mean(mid.astype(np.float64) ** 2, axis=1))
            ks.append(np.mean(side.astype(np.float64) ** 2, axis=1))
        self.kz = np.concatenate(kz) if kz else np.zeros((0, 2))
        self.km = np.concatenate(km) if km else np.zeros(0)
        self.ks = np.concatenate(ks) if ks else np.zeros(0)
        f = np.fft.rfftfreq(NFFT, 1.0 / SR)
        band = np.where((f >= 2000) & (f <= 10000))[0]
        band = band[: (len(band) // 4) * 4]
        self.band_f = f[band].reshape(-1, 4).mean(axis=1)   # centre frequency of each 4-bin group
        spb = (f >= 300) & (f <= 3400)
        win = np.hanning(HOP).astype(np.float32)
        wnorm = float(np.sum(win ** 2))
        bl, bs, sl, pk, full = [], [], [], [], []
        for b in _blocks(stream_pcm(path), HOP):
            mono = b.mean(axis=2)
            pk.append(np.max(np.abs(b), axis=(1, 2)))
            spec = np.abs(np.fft.rfft(mono * win, n=NFFT, axis=1)) ** 2 / (wnorm * SR / 2.0)
            bp = spec[:, band]
            bs.append(bp.reshape(len(bp), -1, 4).mean(axis=2).astype(np.float32))
            df = SR / NFFT
            bl.append(db(bp.sum(axis=1) * df))
            sl.append(db(spec[:, spb].sum(axis=1) * df))
            full.append(db(np.mean(mono.astype(np.float64) ** 2, axis=1)))
        self.band_lvl = np.concatenate(bl) if bl else np.zeros(0)
        self.band_spec = np.concatenate(bs) if bs else np.zeros((0, 1), np.float32)
        self.sp_lvl = np.concatenate(sl) if sl else np.zeros(0)
        self.peak = np.concatenate(pk) if pk else np.zeros(0)
        self.full_lvl = np.concatenate(full) if full else np.zeros(0)
        n = min(len(self.kz), len(self.band_lvl))
        for k in ("kz", "km", "ks", "band_lvl", "band_spec", "sp_lvl", "peak", "full_lvl"):
            setattr(self, k, getattr(self, k)[:n])
        self.n = n
        self.t = np.arange(n) * HOP_S

    # ---- loudness series (centred windows, value at block i describes t[i]) ----
    def power(self):
        return self.kz.sum(axis=1)

    def windowed(self, nblocks, power=None):
        p = self.power() if power is None else power
        if len(p) == 0:
            return p
        c = np.concatenate([[0.0], np.cumsum(p)])
        h0, h1 = nblocks // 2, nblocks - nblocks // 2
        i = np.arange(len(p))
        a, b = np.clip(i - h0, 0, len(p)), np.clip(i + h1, 0, len(p))
        return (c[b] - c[a]) / np.maximum(b - a, 1)

    def momentary(self):
        return lufs_from_power(self.windowed(8))

    def short_term(self):
        return lufs_from_power(self.windowed(60))

    def fast(self):
        return lufs_from_power(self.windowed(4))

    def integrated(self, mask=None):
        return integrated_lufs(self.power(), mask)

    def lra(self):
        return loudness_range(self.power())


def integrated_lufs(power, mask=None):
    """BS.1770-4 gated integrated loudness from 50 ms block powers. mask (bool per block) restricts the windows."""
    p = np.asarray(power, dtype=np.float64)
    if len(p) < 8:
        return None
    c = np.concatenate([[0.0], np.cumsum(p)])
    starts = np.arange(0, len(p) - 7, 2)
    z = (c[starts + 8] - c[starts]) / 8.0
    if mask is not None:
        m = np.asarray(mask, bool)
        keep = np.array([m[s:s + 8].mean() >= 0.5 for s in starts])
        z = z[keep]
    if len(z) == 0:
        return None
    l = lufs_from_power(z)
    z1 = z[l > -70.0]
    if len(z1) == 0:
        return None
    rel = lufs_from_power(np.mean(z1)) - 10.0
    z2 = z1[lufs_from_power(z1) > rel]
    return float(lufs_from_power(np.mean(z2))) if len(z2) else None


def loudness_range(power):
    p = np.asarray(power, dtype=np.float64)
    if len(p) < 60:
        return None
    c = np.concatenate([[0.0], np.cumsum(p)])
    starts = np.arange(0, len(p) - 59, 2)
    z = (c[starts + 60] - c[starts]) / 60.0
    l = lufs_from_power(z)
    l = l[l > -70.0]
    if len(l) == 0:
        return None
    rel = lufs_from_power(np.mean(10 ** ((l + 0.691) / 10))) - 20.0
    l = l[l > rel]
    return float(np.percentile(l, 95) - np.percentile(l, 10)) if len(l) else None


def ffmpeg_ebur128(path):
    """Authoritative I / LRA / true peak from ffmpeg's ebur128 filter (native rate, 4x oversampled true peak)."""
    # not ff_cmd(): the ebur128 summary is printed at info level, which "-v error" would suppress
    p = run(["nice", "-n", "15", "ffmpeg", "-hide_banner", "-nostdin", "-threads", "2", "-i", path, "-vn",
             "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
    txt = p.stderr.decode("utf-8", "replace")
    s = txt[txt.rfind("Summary:"):] if "Summary:" in txt else txt
    def grab(pat):
        m = re.search(pat, s)
        return float(m.group(1)) if m else None
    return {"integrated_lufs": grab(r"I:\s+(-?[\d.]+|-inf)\s+LUFS"), "lra_lu": grab(r"LRA:\s+(-?[\d.]+)\s+LU"),
            "true_peak_dbtp": grab(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS")}


def clipping_runs(path, thresh=0.9999, min_run=3):
    """Count runs of >= min_run consecutive samples at |x| >= thresh at the file's native rate."""
    pr = probe(path)
    sr = pr["sample_rate"] or 48000
    runs, carry = 0, None
    max_abs = 0.0
    for blk in stream_pcm(path, sr=sr, channels=2, block_s=10.0):
        a = np.abs(blk)
        max_abs = max(max_abs, float(a.max()) if len(a) else 0.0)
        hot = (a >= thresh).any(axis=1).astype(np.int8)
        if carry is not None:
            hot = np.concatenate([carry, hot])
        d = np.diff(np.concatenate([[0], hot, [0]]))
        st, en = np.where(d == 1)[0], np.where(d == -1)[0]
        lens = en - st
        if len(lens) and en[-1] == len(hot):   # run touches block end: carry it
            carry = hot[st[-1]:]
            lens = lens[:-1]
        else:
            carry = None
        runs += int(np.sum(lens >= min_run))
    return {"clipped_runs": runs, "sample_peak_dbfs": round(20 * math.log10(max(max_abs, 1e-9)), 2), "native_sr": sr}


# ---- speech segmentation --------------------------------------------------------------------------------------
def runs_of(mask):
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(np.int8))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def voice_activity(level_db, rel_db=30.0, min_pause_s=0.25, min_speech_s=0.12, floor_db=-60.0):
    """Speech mask from a voice-only level track (dB per 50 ms block). Speech = within rel_db of the speech level
    (median of the loud half); pauses shorter than min_pause_s are bridged; blips shorter than min_speech_s dropped."""
    lv = np.asarray(level_db)
    if len(lv) == 0:
        return np.zeros(0, bool), None
    loud = lv[lv > np.percentile(lv, 50)]
    ref = float(np.median(loud)) if len(loud) else float(lv.max())
    # Otsu split of the block-level histogram (speech vs the take's own floor), clamped to [ref-rel_db, ref-12].
    # A fixed ref-30 counted P2's -44 dB take floor as speech and hid its pauses (24 Sep).
    v = lv[lv > -100]
    thr = ref - rel_db
    if len(v) > 20:
        h, e = np.histogram(v, bins=80)
        c = (e[:-1] + e[1:]) / 2
        w0 = np.cumsum(h); w1 = w0[-1] - w0
        m0 = np.cumsum(h * c) / np.maximum(w0, 1); m1 = (np.sum(h * c) - np.cumsum(h * c)) / np.maximum(w1, 1)
        otsu = float(c[np.argmax(w0 * w1 * (m0 - m1) ** 2)])
        thr = min(max(otsu, ref - rel_db), ref - 12.0)
    thr = max(thr, floor_db)
    sp = lv > thr
    for a, b in runs_of(~sp):
        if a > 0 and b < len(sp) and (b - a) * HOP_S < min_pause_s:
            sp[a:b] = True
    for a, b in runs_of(sp):
        if (b - a) * HOP_S < min_speech_s:
            sp[a:b] = False
    return sp, thr


def pauses_from_mask(sp, min_pause_s=0.25):
    out = []
    first = np.argmax(sp) if sp.any() else None
    last = len(sp) - np.argmax(sp[::-1]) if sp.any() else None
    for a, b in runs_of(~sp):
        if first is None or a < first or b > last:
            continue  # leading / trailing non-speech is not a pause
        if (b - a) * HOP_S >= min_pause_s:
            out.append((a * HOP_S, b * HOP_S))
    return out


def welch_flatness(spec_rows):
    """Spectral flatness (geometric / arithmetic mean) of the Welch-averaged 2-10 kHz spectrum.
    Averaging the rows first matters: a single periodogram of white noise has flatness ~0.56 (chi-square bins),
    the averaged one approaches 1.0, while tonal music and voice stay far lower."""
    if len(spec_rows) == 0:
        return None
    s = np.mean(np.asarray(spec_rows, dtype=np.float64), axis=0) + 1e-20
    return float(np.exp(np.mean(np.log(s))) / np.mean(s))


# ---- plotting -------------------------------------------------------------------------------------------------
def plot_png(path, title, t, series, bands=None, hlines=None, panel2=None, dur=None):
    """series: list of (label, y array, rgb). bands: list of (t0, t1, rgb) shaded spans. panel2: same dict for a
    second panel {"title", "series", "hlines", "ylim"}. Returns path or None when PIL is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    W, H1, H2 = 1800, 520, 360 if panel2 else 0
    H = 40 + H1 + (H2 + 40 if panel2 else 0) + 30
    im = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(im)
    font = None
    for fp in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
               "/Library/Fonts/Arial.ttf"):
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 18); small = ImageFont.truetype(fp, 14); break
            except Exception:
                pass
    if font is None:
        font = small = ImageFont.load_default()
    dur = dur or (float(t[-1]) if len(t) else 1.0)
    L, R = 90, W - 30

    def panel(y0, h, ptitle, ser, hl, ylim, bnd):
        lo, hi = ylim
        X = lambda tt: L + (R - L) * (tt / max(dur, 1e-6))
        Y = lambda v: y0 + h - (h * (np.clip(v, lo, hi) - lo) / (hi - lo))
        d.rectangle([L, y0, R, y0 + h], outline=(180, 180, 180), fill=(255, 255, 255))
        for (a, b, col) in (bnd or []):
            d.rectangle([X(a), y0 + 1, X(b), y0 + h - 1], fill=col)
        step = 10 if hi - lo > 30 else 5
        for v in range(int(math.ceil(lo / step) * step), int(hi) + 1, step):
            d.line([L, Y(v), R, Y(v)], fill=(232, 232, 232))
            d.text((10, Y(v) - 8), "%d" % v, fill=(90, 90, 90), font=small)
        tick = 5 if dur <= 90 else 30 if dur <= 600 else 120
        for s in range(0, int(dur) + 1, tick):
            d.line([X(s), y0 + h, X(s), y0 + h + 5], fill=(120, 120, 120))
            d.text((X(s) - 8, y0 + h + 6), "%d" % s, fill=(90, 90, 90), font=small)
        for (v, col, lab) in (hl or []):
            d.line([L, Y(v), R, Y(v)], fill=col, width=2)
            d.text((L + 8, Y(v) - 18), lab, fill=col, font=small)
        for (lab, y, col) in ser:
            y = np.asarray(y, dtype=float)
            if len(y) == 0:
                continue
            k = max(1, len(y) // (R - L))
            seg = []
            for i in range(0, min(len(t), len(y)), k):      # break the line wherever the value is undefined
                if np.isfinite(y[i]):
                    seg.append((X(t[i]), Y(y[i])))
                else:
                    if len(seg) > 1:
                        d.line(seg, fill=col, width=2)
                    seg = []
            if len(seg) > 1:
                d.line(seg, fill=col, width=2)
        d.text((L, y0 - 26), ptitle, fill=(20, 20, 20), font=font)
        x = L + 12
        for (lab, _, col) in ser:
            d.rectangle([x, y0 + 8, x + 18, y0 + 20], fill=col)
            d.text((x + 24, y0 + 5), lab, fill=(40, 40, 40), font=small)
            x += 30 + int(d.textlength(lab, font=small)) + 20

    panel(40, H1, title, series, hlines, (-60, -5), bands)
    if panel2:
        panel(40 + H1 + 70, H2, panel2["title"], panel2["series"], panel2.get("hlines"), panel2.get("ylim", (-10, 50)),
              panel2.get("bands"))
    d.text((L, H - 24), "seconds", fill=(90, 90, 90), font=small)
    im.save(path)
    return path


def selftest(paths):
    """Our integrated / LRA vs ffmpeg ebur128 on real files. Fails (exit 1) beyond 0.5 LU integrated, 1.5 LU LRA."""
    ok = True
    for p in paths:
        f = Features(p)
        ours_i, ours_lra = f.integrated(), f.lra()
        ref = ffmpeg_ebur128(p)
        di = abs(ours_i - ref["integrated_lufs"]) if ours_i is not None and ref["integrated_lufs"] is not None else 99
        dl = abs(ours_lra - ref["lra_lu"]) if ours_lra is not None and ref["lra_lu"] is not None else 99
        good = di <= 0.5 and dl <= 1.5
        ok &= good
        print("%s  ours I %.2f LRA %.2f | ffmpeg I %s LRA %s TP %s | dI %.2f dLRA %.2f  %s" % (
            os.path.basename(p), ours_i if ours_i is not None else float("nan"),
            ours_lra if ours_lra is not None else float("nan"), ref["integrated_lufs"], ref["lra_lu"],
            ref["true_peak_dbtp"], di, dl, "OK" if good else "MISMATCH"))
    return ok


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        sys.exit(0 if selftest(sys.argv[2:]) else 1)
    print(__doc__)
