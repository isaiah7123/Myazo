import collections
import ctypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path

import cv2
import imageio_ffmpeg
import mss
import numpy as np
from PySide6.QtCore import QObject, Signal

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
NOWIN = 0x08000000  # CREATE_NO_WINDOW
RATE = 48000


def run_ff(args):
    return subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                          creationflags=NOWIN, capture_output=True)


def parse_res(s):
    if "x" in str(s):
        w, h = str(s).split("x")
        return int(w), int(h)
    return 0, 0


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(pcm.tobytes())


def mux(video, wavs, out, normalize):
    """Combine the silent video with 0-2 audio tracks (mixed, optionally volume-normalized)."""
    if not wavs:
        os.replace(video, out)
        return
    args = ["-i", video]
    for w in wavs:
        args += ["-i", w]
    if len(wavs) > 1:
        f = "".join(f"[{i + 1}:a]" for i in range(len(wavs))) + f"amix=inputs={len(wavs)}:normalize=0"
    else:
        f = "[1:a]anull"
    f += (",dynaudnorm" if normalize else "") + "[a]"
    r = run_ff([*args, "-filter_complex", f, "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out])
    if r.returncode:
        os.replace(video, out)  # fall back to silent video


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE), ("pt", wintypes.POINT)]


_ARROW = np.array([(0, 0), (0, 16), (4, 12), (7, 19), (10, 18), (7, 11), (12, 11)], np.int32)


def draw_cursor(f, m):
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(ci)
    if ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci)) and ci.flags & 1:
        x, y = ci.pt.x - m["left"], ci.pt.y - m["top"]
        if 0 <= x < f.shape[1] and 0 <= y < f.shape[0]:
            pts = _ARROW + (x, y)
            cv2.fillPoly(f, [pts], (255, 255, 255))
            cv2.polylines(f, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)


def grab_frame(sct, m, ow, oh):
    f = np.ascontiguousarray(np.asarray(sct.grab(m))[:, :, :3])
    draw_cursor(f, m)
    if f.shape[1] != ow or f.shape[0] != oh:
        f = cv2.resize(f, (ow, oh), interpolation=cv2.INTER_AREA)
    return f


def out_size(st, m):
    w, h = m["width"] & ~1, m["height"] & ~1
    mw, mh = parse_res(st["max_res"])
    sc = min(1, mw / w, mh / h) if mw else 1
    return w, h, int(w * sc) & ~1, int(h * sc) & ~1


class AudioCapture(threading.Thread):
    """Captures system loopback or microphone. Writes a wav file, or keeps a rolling in-memory buffer."""

    def __init__(self, kind, wav=None, keep=None):
        super().__init__(daemon=True)
        self.kind, self.wav, self.keep = kind, wav, keep
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self.chunks = collections.deque()
        self.t0 = self.prev = None
        self.closed = False
        self.wf = None
        if wav:
            self.wf = wave.open(str(wav), "wb")
            self.wf.setnchannels(2)
            self.wf.setsampwidth(2)
            self.wf.setframerate(RATE)

    def run(self):
        try:
            import warnings
            import soundcard as sc
            warnings.simplefilter("ignore")
            if self.kind == "system":
                dev = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
            else:
                dev = sc.default_microphone()
            with dev.recorder(samplerate=RATE, channels=dev.channels) as rec:
                self.t0 = self.prev = time.monotonic()
                while not self.stop_ev.is_set():
                    self._push(rec.record(numframes=RATE // 10), time.monotonic())
        except Exception:
            pass

    def _push(self, data, now):
        if data.ndim == 1:
            data = data[:, None]
        if data.shape[1] == 1:
            data = np.repeat(data, 2, 1)
        pcm = (np.clip(data[:, :2], -1, 1) * 32767).astype(np.int16)
        start = now - len(pcm) / RATE
        with self.lock:
            if self.closed:
                return
            gap = start - self.prev
            if gap > 0.05:  # loopback sends nothing during silence: fill the gap
                self._emit(np.zeros((int(gap * RATE), 2), np.int16), start)
            self._emit(pcm, now)
            self.prev = now

    def _emit(self, pcm, end):
        if self.wf:
            self.wf.writeframes(pcm.tobytes())
        else:
            self.chunks.append((end, pcm))
            while self.chunks and self.chunks[0][0] < end - self.keep - 1:
                self.chunks.popleft()

    def finish(self, end_time):
        self.stop_ev.set()
        with self.lock:
            self.closed = True
            if self.wf:
                if self.t0 and end_time - self.prev > 0.05:
                    self.wf.writeframes(np.zeros((int((end_time - self.prev) * RATE), 2), np.int16).tobytes())
                self.wf.close()

    def snapshot(self, seconds):
        with self.lock:
            now = time.monotonic()
            arr = [c for e, c in self.chunks if e > now - seconds]
            if self.chunks and now - self.chunks[-1][0] > 0.05:
                arr.append(np.zeros((int((now - self.chunks[-1][0]) * RATE), 2), np.int16))
        return np.concatenate(arr)[-int(seconds * RATE):] if arr else None


class Recorder(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, st, mon, out):
        super().__init__()
        self.st, self.mon, self.out = st, mon, str(out)
        self.stop_ev = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stop_ev.set()

    def _run(self):
        st = self.st
        tmpd = tempfile.mkdtemp(prefix="myazo_")
        vid = os.path.join(tmpd, "v.mp4")
        audio = []
        try:
            m = dict(self.mon)
            m["width"] &= ~1
            m["height"] &= ~1
            _, _, ow, oh = out_size(st, m)
            fps = int(st["fps"])
            for kind, key in (("system", "rec_system"), ("mic", "rec_mic")):
                if st[key]:
                    a = AudioCapture(kind, wav=os.path.join(tmpd, kind + ".wav"))
                    a.start()
                    audio.append(a)
            ff = subprocess.Popen(
                [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                 "-s", f"{ow}x{oh}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
                 "-preset", "ultrafast", "-crf", "21", "-pix_fmt", "yuv420p", vid],
                stdin=subprocess.PIPE, creationflags=NOWIN)
            written, start, maxs = 0, time.monotonic(), int(st["max_seconds"])
            with mss.mss() as sct:
                while not self.stop_ev.is_set():
                    if maxs and time.monotonic() - start >= maxs:
                        break
                    data = grab_frame(sct, m, ow, oh).tobytes()
                    due = int((time.monotonic() - start) * fps) + 1
                    while written < due:  # keep real-time pace even if grabbing is slow
                        ff.stdin.write(data)
                        written += 1
                    delay = start + written / fps - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
            end = time.monotonic()
            ff.stdin.close()
            ff.wait()
            for a in audio:
                a.finish(end)
            mux(vid, [a.wav for a in audio if a.t0], self.out, st["rec_normalize"])
            self.finished.emit(self.out)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)


class ReplayBuffer(QObject):
    """Continuously records the primary screen into memory; saving writes out the last N seconds."""
    saved = Signal(str)
    failed = Signal(str)

    def __init__(self, st):
        super().__init__()
        self.st = st
        self.running = False
        self.frames = collections.deque()
        self.lock = threading.Lock()
        self.audio = []
        self.stop_ev = threading.Event()

    def start(self):
        if self.running:
            return
        self.stop_ev = threading.Event()
        self.frames.clear()
        secs = int(self.st["replay_seconds"])
        for kind, key in (("system", "replay_system"), ("mic", "replay_mic")):
            if self.st[key]:
                a = AudioCapture(kind, keep=secs)
                a.start()
                self.audio.append(a)
        self.running = True
        threading.Thread(target=self._loop, args=(self.stop_ev, secs), daemon=True).start()

    def stop(self):
        self.stop_ev.set()
        for a in self.audio:
            a.stop_ev.set()
        self.audio, self.running = [], False

    def _loop(self, stop_ev, secs):
        fps = min(int(self.st["fps"]), 30)
        cap = fps * secs
        try:
            with mss.mss() as sct:
                m = dict(sct.monitors[1])
                m["width"] &= ~1
                m["height"] &= ~1
                _, _, ow, oh = out_size(self.st, m)
                nxt = time.monotonic()
                while not stop_ev.is_set():
                    f = grab_frame(sct, m, ow, oh)
                    ok, b = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    with self.lock:
                        self.frames.append((time.monotonic(), b.tobytes()))
                        while len(self.frames) > cap:
                            self.frames.popleft()
                    nxt += 1 / fps
                    d = nxt - time.monotonic()
                    if d > 0:
                        time.sleep(d)
                    else:
                        nxt = time.monotonic()
        except Exception as e:
            self.running = False
            self.failed.emit(f"Replay stopped: {e}")

    def save(self, out):
        with self.lock:
            items = list(self.frames)
        audio = list(self.audio)
        threading.Thread(target=self._save, args=(items, audio, str(out)), daemon=True).start()

    def _save(self, items, audio, out):
        tmpd = tempfile.mkdtemp(prefix="myazo_")
        try:
            if len(items) < 2:
                raise RuntimeError("Replay buffer is still empty")
            span = max(0.1, items[-1][0] - items[0][0])
            fps = (len(items) - 1) / span
            vid = os.path.join(tmpd, "v.mp4")
            ff = subprocess.Popen(
                [FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", f"{fps:.3f}",
                 "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", vid],
                stdin=subprocess.PIPE, creationflags=NOWIN)
            for _, b in items:
                ff.stdin.write(b)
            ff.stdin.close()
            ff.wait()
            wavs = []
            for a in audio:
                pcm = a.snapshot(span)
                if pcm is not None and a.t0:
                    p = os.path.join(tmpd, a.kind + ".wav")
                    write_wav(p, pcm)
                    wavs.append(p)
            mux(vid, wavs, out, self.st["replay_normalize"])
            self.saved.emit(out)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)


__all__ = ["Recorder", "ReplayBuffer", "Path"]
