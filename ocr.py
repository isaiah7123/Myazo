import json
import os
import shutil
import threading
from pathlib import Path

_lock = threading.Lock()


def _file(st):
    return st.meta_dir() / "ocr.json"


def load_index(st):
    try:
        return json.loads(_file(st).read_text("utf-8"))
    except Exception:
        return {}


def store(st, path, text):
    with _lock:
        idx = load_index(st)
        idx[Path(path).name] = text
        _file(st).write_text(json.dumps(idx), "utf-8")


def find_tesseract(st):
    """Settings path first, then PATH, then the usual install locations."""
    cands = [st["tesseract_path"], shutil.which("tesseract"),
             r"C:\Program Files\Tesseract-OCR\tesseract.exe",
             r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe")]
    for c in cands:
        if c and os.path.isdir(c):
            c = os.path.join(c, "tesseract.exe")
        if c and os.path.isfile(c):
            return c
    return None


def _prep(path):
    """Grayscale, flip dark-mode screenshots to dark-on-light, and upscale small images (helps Tesseract)."""
    from PIL import Image, ImageOps, ImageStat
    img = Image.open(path).convert("L")
    if ImageStat.Stat(img).mean[0] < 110:
        img = ImageOps.invert(img)
    s = 2 if max(img.size) < 2000 else 1
    if s > 1:
        img = img.resize((img.width * s, img.height * s), Image.Resampling.LANCZOS)
    return img, s


def ocr_words(st, path):
    """Returns [(text, x, y, w, h, (block, paragraph, line)), ...] in reading order, in image pixels."""
    exe = find_tesseract(st)
    if not exe:
        raise RuntimeError("Tesseract not found. Install it (Windows build from UB-Mannheim), "
                           "or set its path in Settings > More options.")
    import pytesseract
    from pytesseract import Output
    pytesseract.pytesseract.tesseract_cmd = exe
    img, s = _prep(path)
    d = pytesseract.image_to_data(img, lang=st["ocr_lang"] or "eng", output_type=Output.DICT)
    words = []
    for i, t in enumerate(d["text"]):
        try:
            conf = float(d["conf"][i])
        except ValueError:
            conf = -1
        if t.strip() and conf >= 30:
            words.append((t.strip(), d["left"][i] / s, d["top"][i] / s, d["width"][i] / s, d["height"][i] / s,
                          (d["block_num"][i], d["par_num"][i], d["line_num"][i])))
    return words


def join_words(words):
    out, prev = [], None
    for w in words:
        if prev is not None:
            out.append(" " if w[5] == prev else "\n")
        out.append(w[0])
        prev = w[5]
    return "".join(out)


def ocr_async(st, path):
    """Background OCR after a capture so the library's search can find text in screenshots."""
    def work():
        try:
            store(st, path, join_words(ocr_words(st, path)))
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()
