"""Make clean PDF pages look like scans or phone photos."""
import io
import random

import pymupdf as fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance


def pdf_to_images(pdf_path: str, dpi: int = 150) -> list[Image.Image]:
    doc = fitz.open(pdf_path)
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    doc.close()
    return out


def _coeffs(src, dst):
    """Perspective coefficients mapping dst quad -> src quad (PIL convention)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, dtype=float), np.array(rhs, dtype=float)).tolist()


def _noise(img: Image.Image, sigma: float, rng: random.Random) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    gen = np.random.default_rng(rng.randrange(2**32))
    arr += gen.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _shadow(img: Image.Image, strength: float, rng: random.Random) -> Image.Image:
    w, h = img.size
    ang = rng.uniform(0, 2 * np.pi)
    xs = np.linspace(-1, 1, w)[None, :]
    ys = np.linspace(-1, 1, h)[:, None]
    grad = (xs * np.cos(ang) + ys * np.sin(ang) + 1) / 2          # 0..1
    mult = 1 - strength * grad
    arr = np.asarray(img).astype(np.float32) * mult[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def scan(img: Image.Image, rng: random.Random) -> tuple[Image.Image, dict]:
    p = dict(rotate=round(rng.uniform(-1.5, 1.5), 2), blur=round(rng.uniform(0.3, 0.7), 2),
             noise=round(rng.uniform(3, 6), 1), gray=rng.random() < 0.5,
             jpeg=rng.randint(70, 85))
    img = img.rotate(p["rotate"], resample=Image.BICUBIC, expand=True, fillcolor=(247, 247, 245))
    img = img.filter(ImageFilter.GaussianBlur(p["blur"]))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.9, 1.05))
    img = _noise(img, p["noise"], rng)
    if p["gray"]:
        img = img.convert("L").convert("RGB")
    return img, p


def photo(img: Image.Image, rng: random.Random) -> tuple[Image.Image, dict]:
    p = dict(rotate=round(rng.uniform(-3, 3), 2), blur=round(rng.uniform(0.6, 1.4), 2),
             noise=round(rng.uniform(6, 12), 1), shadow=round(rng.uniform(0.15, 0.4), 2),
             brightness=round(rng.uniform(0.85, 1.1), 2), jpeg=rng.randint(45, 70))
    w, h = img.size
    pad = int(0.06 * w)
    desk = (rng.randint(110, 170), rng.randint(90, 140), rng.randint(70, 120))
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), desk)
    canvas.paste(img.rotate(p["rotate"], resample=Image.BICUBIC, expand=False, fillcolor=(247, 247, 245)),
                 (pad, pad))
    W, H = canvas.size
    j = 0.025
    jit = lambda: rng.uniform(-j, j)
    dst = [(0, 0), (W, 0), (W, H), (0, H)]
    src = [(W * max(0, jit()), H * max(0, jit())), (W * (1 + min(0, jit())), H * max(0, jit())),
           (W * (1 + min(0, jit())), H * (1 + min(0, jit()))), (W * max(0, jit()), H * (1 + min(0, jit())))]
    canvas = canvas.transform((W, H), Image.PERSPECTIVE, _coeffs(src, dst), Image.BICUBIC)
    canvas = _shadow(canvas, p["shadow"], rng)
    canvas = ImageEnhance.Brightness(canvas).enhance(p["brightness"])
    canvas = canvas.filter(ImageFilter.GaussianBlur(p["blur"]))
    canvas = _noise(canvas, p["noise"], rng)
    scale = 1400 / canvas.size[0]
    canvas = canvas.resize((1400, int(canvas.size[1] * scale)), Image.LANCZOS)
    return canvas, p


def save_jpeg(img: Image.Image, path: str, quality: int) -> None:
    img.save(path, "JPEG", quality=quality)
