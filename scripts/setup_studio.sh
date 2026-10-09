#!/usr/bin/env bash
# One-time setup for the studio (voice clone + avatar). Free; downloads ~2–3 GB.
# Puts Chatterbox in its own environment (.venv-tts) so its pinned torch versions never touch AIOS.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null; then
  echo "Installing ffmpeg…"
  # conda first: prebuilt binaries. A Homebrew outside /opt/homebrew compiles from source and often fails.
  if command -v conda >/dev/null; then conda install -y -c conda-forge ffmpeg
  elif command -v brew >/dev/null; then brew install ffmpeg
  else echo "Install Homebrew (https://brew.sh) then run: brew install ffmpeg"; exit 1; fi
fi

if [ ! -x .venv-tts/bin/python ]; then
  if command -v conda >/dev/null; then
    conda create -y -p .venv-tts python=3.11
  elif command -v python3.11 >/dev/null; then
    python3.11 -m venv .venv-tts
  else
    echo "Need Python 3.11: brew install python@3.11  (then run this again)"; exit 1
  fi
fi
.venv-tts/bin/python -m pip install --upgrade pip
.venv-tts/bin/python -m pip install chatterbox-tts

grep -q '^AIOS_TTS_PYTHON=' .env 2>/dev/null || echo "AIOS_TTS_PYTHON=$PWD/.venv-tts/bin/python" >> .env
.venv-tts/bin/python aios/media/chatterbox_worker.py --check --text-file x --ref x --out x
echo "Studio ready. Next: aios voice setup <your recording> --mine"
