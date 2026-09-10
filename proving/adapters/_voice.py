"""Transcript channels for a voice agent: clean, word noise at a set rate, and split turns.

These isolate the dialogue model from speech recognition, as MTVA-Bench does (arXiv 2609.20152).
"""

from __future__ import annotations

import hashlib
import random

# Letters speech recognizers confuse, per script. Arabic pairs are close in sound, Latin ones in shape.
_AR = {"ح": "خ", "خ": "ح", "ع": "غ", "غ": "ع", "س": "ص", "ص": "س", "ت": "ط", "ط": "ت", "د": "ض", "ض": "د",
       "ذ": "ز", "ز": "ذ", "ق": "ك", "ك": "ق", "ب": "ت", "ن": "ت", "ر": "ز", "ي": "ب", "ة": "ه", "ا": "ى"}
_EN = {"a": "e", "e": "i", "i": "e", "o": "u", "u": "o", "b": "p", "p": "b", "d": "t", "t": "d", "s": "z",
       "z": "s", "v": "f", "f": "v", "m": "n", "n": "m", "r": "l", "l": "r", "g": "k", "k": "g"}


def _confuse(word: str, rng: random.Random) -> str:
    spots = [i for i, c in enumerate(word) if c.lower() in _EN or c in _AR]
    if not spots:
        return word
    i = rng.choice(spots)
    c = word[i]
    repl = _AR.get(c) or _EN.get(c.lower(), c)
    return word[:i] + repl + word[i + 1:]


def noisy(text: str, rate: float, rng: random.Random) -> str:
    """Corrupt about `rate` of the words: mostly a confused letter, sometimes a dropped or merged word."""
    words = text.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if rng.random() < rate:
            roll = rng.random()
            if roll < 0.6:
                out.append(_confuse(w, rng))
            elif roll < 0.8:
                pass
            elif i + 1 < len(words):
                out.append(w + words[i + 1])
                i += 1
            else:
                out.append(_confuse(w, rng))
        else:
            out.append(w)
        i += 1
    return " ".join(out)


def split(text: str) -> list[str]:
    """The same words as two messages cut near the middle, the way a caller pauses mid-sentence."""
    words = text.split()
    if len(words) < 4:
        return [text]
    mid = len(words) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    """Edit distance over words and the reference length, for the WER a channel actually produced."""
    r, h = ref.split(), hyp.split()
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1], len(r)


class SpeechChannel:
    """Caller text spoken by Parley's Piper voices, optionally degraded, heard by Parley's Whisper stack.

    TRACE (arXiv 2609.29452) runs each call on a clean and a stressed copy. Only this channel needs the
    speech models, and its transcripts are recorded, so a replay needs neither.
    """

    def __init__(self, config: str = "local-v1") -> None:
        from speech.backends import CONFIGS
        from speech.backends.local import build_asr
        from speech.tts import PiperTTS

        self.asr = build_asr(CONFIGS[config])
        self.tts = PiperTTS()

    def _audio(self, text: str):
        import re

        import numpy as np
        from speech.audio import silence

        # Parley's own callers voice a code-switched line one language at a time, so split by script.
        runs = re.findall(r"[؀-ۿ][؀-ۿ\s،؟]*|[^؀-ۿ]+", text)
        parts = [silence(0.25)]
        for chunk in (r.strip() for r in runs):
            if not chunk or not re.search(r"\w", chunk):
                continue
            lang = "ar" if re.search(r"[؀-ۿ]", chunk) else "en"
            parts += [self.tts.synthesize(chunk, lang).pcm, silence(0.12)]
        parts.append(silence(0.25))
        return np.concatenate(parts)

    @staticmethod
    def stress(pcm, arm: str, seed: str):
        import numpy as np

        if arm == "clean":
            return pcm
        kind, _, level = arm.partition("@")
        rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
        x = pcm.astype(np.float64)
        if kind == "white":
            snr = float(level)
            noise = rng.standard_normal(len(x))
            scale = np.sqrt(np.mean(x ** 2) / (np.mean(noise ** 2) * 10 ** (snr / 10)))
            x = x + scale * noise
        return np.clip(x, -32768, 32767).astype(np.int16)

    def hear(self, text: str, arm: str, hint: str | None, seed: str) -> dict:
        import numpy as np
        from speech.asr import StreamingRecognizer
        from speech.audio import SAMPLE_RATE, silence
        from speech.vad import FRAME, EnergyVAD

        pcm = self.stress(self._audio(text), arm, seed)
        rec = StreamingRecognizer(self.asr, early_final=True)
        rec.lang_hint = hint
        hangover = EnergyVAD().hangover_frames * FRAME / SAMPLE_RATE
        stream = np.concatenate([silence(0.3), pcm, silence(hangover + 0.3)])
        texts, secs = [], 0.0
        for k in range(len(stream) // FRAME):
            for ev in rec.push(stream[k * FRAME:(k + 1) * FRAME]):
                if ev.kind == "final":
                    texts.append(ev.text)
                    secs += ev.decode_seconds
        for ev in rec.flush():
            texts.append(ev.text)
            secs += ev.decode_seconds
        return {"text": " ".join(t for t in texts if t).strip(), "decode_s": round(secs, 3)}
