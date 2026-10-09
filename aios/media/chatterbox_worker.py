"""Standalone speech worker. Runs in whatever Python has `chatterbox-tts` installed.

It imports nothing from aios on purpose: Chatterbox pins torch/transformers versions, so it can live in
its own virtualenv (AIOS_TTS_PYTHON) without touching the main install.

    python chatterbox_worker.py --text-file script.txt --ref voice.wav --out out.wav --model turbo --device auto

Prints one JSON line on success: {"ok": true, "out": ..., "seconds": ..., "sample_rate": ..., "device": ...}
"""

from __future__ import annotations

import argparse
import json
import re
import sys


def _device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _chunks(text: str, limit: int = 280) -> list[str]:
    """Split on sentence ends so each generation stays short (long inputs drift and slow down)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    out: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="turbo", choices=["turbo", "original"])
    ap.add_argument("--device", default="auto")
    ap.add_argument("--check", action="store_true", help="only verify imports and print the device")
    a = ap.parse_args()

    import torch
    import torchaudio as ta

    dev = _device(a.device)
    if a.check:
        print(json.dumps({"ok": True, "device": dev, "torch": torch.__version__}))
        return 0

    _load = torch.load  # weights were saved on CUDA; map them to this device (needed on Macs)
    torch.load = lambda *x, **k: _load(*x, **{**k, "map_location": torch.device(dev)})

    if a.model == "turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS as Model
    else:
        from chatterbox.tts import ChatterboxTTS as Model
    model = Model.from_pretrained(device=dev)

    text = open(a.text_file, encoding="utf-8").read()
    pieces = []
    gap = torch.zeros(1, int(model.sr * 0.25))
    model.prepare_conditionals(a.ref)  # embed the reference voice once, reuse it for every chunk
    for chunk in _chunks(text):
        wav = model.generate(chunk)
        pieces += [wav.cpu(), gap]
    if not pieces:
        print(json.dumps({"ok": False, "error": "empty script"}))
        return 1
    audio = torch.cat(pieces[:-1], dim=1)
    ta.save(a.out, audio, model.sr)
    print(json.dumps({"ok": True, "out": a.out, "seconds": audio.shape[1] / model.sr, "sample_rate": model.sr,
                      "device": dev}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
