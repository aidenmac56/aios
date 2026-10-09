"""Studio: the founder's cloned voice and talking-head avatar, made from his own recordings.

    voice setup  → a 10–30 s clip of the founder's own voice becomes the reference (VOICE_REFERENCE)
    avatar setup → 30–60 s of the founder on camera becomes the face source (AVATAR_SOURCE)
    voice say    → script → speech in his voice, generated locally with Chatterbox (free, MIT)
    video make   → script → speech → his face lip-synced to it on a rented GPU (LatentSync on Replicate)

Rules this module keeps:
- Founder only. Agents can't register a voice or face, and can't generate media (no agent holds these
  permissions, and every function checks the actor).
- Only the founder's own voice and face: setup requires him to confirm the recording is of himself.
- Nothing is published. Output is saved as a DRAFT file marked synthetic; uploading it is his call and
  YouTube requires the "altered or synthetic content" disclosure for it.
- Paid steps are budget-checked before they run, and their measured cost is recorded in model_usage, so
  `aios cost` and the daily budget include them.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aios.config import ROOT, get_settings
from aios.core import audit, sysconfig
from aios.core.actor import Actor
from aios.core.budget import spent_today
from aios.core.errors import AIOSError, BudgetExceeded, NotFound, PermissionDenied, ValidationFailed
from aios.core.util import micros_to_usd, usd_to_micros
from aios.db.enums import MediaKind, MediaStatus
from aios.db.models import MediaAsset, ModelUsage, WorkflowRun

WORKER = Path(__file__).resolve().parent.parent / "media" / "chatterbox_worker.py"
DISCLOSURE = ("AI-generated: this uses an AI clone of the founder's voice"
              " and face. On YouTube, answer 'Yes' to 'Altered or synthetic content' when uploading.")

# Indirection so tests can run without ffmpeg, torch or the network.
run_process = subprocess.run


def _require_founder(actor: Actor) -> None:
    if not actor.is_founder:
        raise PermissionDenied("Only the founder can create or use his voice and face clone.", actor=str(actor))


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ValidationFailed(f"{name} is not installed. On a Mac: brew install ffmpeg")
    return path


def media_dir(session: Session) -> Path:
    d = Path(sysconfig.get(session, "media.dir"))
    d = d if d.is_absolute() else ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_duration(path: Path) -> float:
    _require_tool("ffprobe")
    r = run_process(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                    capture_output=True, text=True)
    if r.returncode != 0:
        raise ValidationFailed(f"Could not read {path.name}: {(r.stderr or '').strip()[:200]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def _ffmpeg(args: list[str]) -> None:
    _require_tool("ffmpeg")
    r = run_process(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValidationFailed(f"ffmpeg failed: {(r.stderr or '').strip()[:300]}")


def active(session: Session, kind: MediaKind) -> MediaAsset | None:
    return session.execute(select(MediaAsset).where(MediaAsset.kind == kind, MediaAsset.status == MediaStatus.ACTIVE)
                           .order_by(MediaAsset.created_at.desc()).limit(1)).scalar()


def _new_asset(session: Session, path: Path, **kw) -> MediaAsset:
    a = MediaAsset(path=str(path), sha256=_sha256(path), bytes=path.stat().st_size, **kw)
    session.add(a)
    session.flush()
    return a


# ------------------------------------------------------------------------------------------- setup


def setup_voice(session: Session, actor: Actor, src: Path, *, confirm_own_voice: bool, start_s: float = 0,
                seconds: float = 20) -> MediaAsset:
    """Turn the founder's recording into a clean mono reference clip (Chatterbox wants ~10–30 s)."""
    _require_founder(actor)
    if not confirm_own_voice:
        raise ValidationFailed("Confirm this recording is your own voice (--mine). Cloning anyone else's voice is not supported.")
    src = Path(src).expanduser()
    if not src.exists():
        raise NotFound(f"No file at {src}")
    total = probe_duration(src)
    if total - start_s < 8:
        raise ValidationFailed(f"The recording is {total:.0f}s; need at least 8 seconds of you talking after --start.")
    seconds = min(seconds, total - start_s, 30)
    out = media_dir(session) / "voice" / f"reference-{hashlib.sha1(str(src).encode()).hexdigest()[:8]}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-ss", str(start_s), "-t", str(seconds), "-i", str(src), "-ac", "1", "-ar", "24000", str(out)])
    for old in session.execute(select(MediaAsset).where(MediaAsset.kind == MediaKind.VOICE_REFERENCE,
                                                        MediaAsset.status == MediaStatus.ACTIVE)).scalars():
        old.status = MediaStatus.RETIRED
    a = _new_asset(session, out, kind=MediaKind.VOICE_REFERENCE, status=MediaStatus.ACTIVE, duration_s=seconds,
                   synthetic=False, engine="ffmpeg", created_by=str(actor),
                   meta={"source_file": src.name, "start_s": start_s, "founder_confirmed_own_voice": True})
    audit.record(session, who=str(actor), what="studio.voice_setup", input={"source": src.name, "seconds": seconds},
                 why="founder registered his own voice reference", target_type="media_asset", target_id=a.id)
    return a


def setup_avatar(session: Session, actor: Actor, src: Path, *, confirm_own_face: bool, max_seconds: float = 60) -> MediaAsset:
    """Normalize the founder's on-camera footage: H.264, 25 fps, no audio, at most `max_seconds`."""
    _require_founder(actor)
    if not confirm_own_face:
        raise ValidationFailed("Confirm this footage is of you (--mine). Avatars of anyone else are not supported.")
    src = Path(src).expanduser()
    if not src.exists():
        raise NotFound(f"No file at {src}")
    total = probe_duration(src)
    if total < 5:
        raise ValidationFailed(f"The clip is {total:.1f}s; record at least 15–30 seconds of you looking at the camera.")
    seconds = min(total, max_seconds)
    out = media_dir(session) / "avatar" / f"source-{hashlib.sha1(str(src).encode()).hexdigest()[:8]}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-t", str(seconds), "-i", str(src), "-an", "-r", "25", "-vf", "scale=-2:'min(1080,ih)'",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)])
    for old in session.execute(select(MediaAsset).where(MediaAsset.kind == MediaKind.AVATAR_SOURCE,
                                                        MediaAsset.status == MediaStatus.ACTIVE)).scalars():
        old.status = MediaStatus.RETIRED
    a = _new_asset(session, out, kind=MediaKind.AVATAR_SOURCE, status=MediaStatus.ACTIVE, duration_s=seconds,
                   synthetic=False, engine="ffmpeg", created_by=str(actor),
                   meta={"source_file": src.name, "founder_confirmed_own_face": True})
    audit.record(session, who=str(actor), what="studio.avatar_setup", input={"source": src.name, "seconds": seconds},
                 why="founder registered his own face footage", target_type="media_asset", target_id=a.id)
    return a


# ------------------------------------------------------------------------------------------- scripts


_DIRECTION = re.compile(r"\[(?!laugh\]|chuckle\]|sigh\]|cough\])[^\]]*\]|\((?:b-roll|cut|on screen|pause|beat)[^)]*\)", re.I)


def spoken_text(script: str) -> str:
    """Drop what the camera does, keep what you say: [B-roll …], (cut to …), markdown, speaker labels."""
    lines = []
    for line in script.splitlines():
        s = line.strip()
        if not s or re.match(r"^(#+|---|\*\*?(b-roll|on screen|visual|shot)\b)", s, re.I):
            continue
        s = _DIRECTION.sub("", s)
        s = re.sub(r"^\s*(aiden|host|you|vo|narrator)\s*:\s*", "", s, flags=re.I)
        s = re.sub(r"[*_`#>]", "", s).strip()
        if s:
            lines.append(s)
    return " ".join(lines)


def script_from_run(session: Session, run_id: str, item: int | None) -> str:
    run = session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFound(f"No run {run_id}")
    items = ((run.result or {}).get("draft") or {}).get("items") or []
    if not items:
        raise ValidationFailed("That run has no draft items. Use a run from `aios draft`.")
    if item is None:
        if len(items) > 1:
            labels = "; ".join(f"{i + 1}: {it['label']}" for i, it in enumerate(items))
            raise ValidationFailed(f"That draft has {len(items)} items; pick one with --item. {labels}")
        item = 1
    if not 1 <= item <= len(items):
        raise ValidationFailed(f"--item must be 1–{len(items)}")
    return items[item - 1]["text"]


# ------------------------------------------------------------------------------------------- generation


def speak(sm: sessionmaker, actor: Actor, script: str) -> dict:
    """Script → WAV in the founder's voice, generated on this machine. Free; takes a minute or two."""
    _require_founder(actor)
    text = spoken_text(script)
    if len(text) < 2:
        raise ValidationFailed("The script is empty after removing stage directions.")
    with sm() as s:
        ref = active(s, MediaKind.VOICE_REFERENCE)
        if ref is None:
            raise ValidationFailed("No voice reference yet. Run: aios voice setup <recording> --mine")
        model, device, out_dir = sysconfig.get(s, "media.tts_model"), sysconfig.get(s, "media.tts_device"), media_dir(s) / "audio"
        ref_id, ref_path = ref.id, ref.path
    out_dir.mkdir(parents=True, exist_ok=True)
    py = get_settings().tts_python or sys.executable
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        text_file = f.name
    out = out_dir / f"speech-{hashlib.sha1(text.encode()).hexdigest()[:10]}.wav"
    r = run_process([py, str(WORKER), "--text-file", text_file, "--ref", ref_path, "--out", str(out),
                     "--model", model, "--device", device], capture_output=True, text=True)
    Path(text_file).unlink(missing_ok=True)
    last = (r.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        info = json.loads(last[0])
    except json.JSONDecodeError:
        info = {"ok": False}
    if r.returncode != 0 or not info.get("ok") or not out.exists():
        err = (r.stderr or "").strip()
        hint = ("Chatterbox is not installed in that Python. See README → Studio."
                if "No module named" in err else "")
        raise AIOSError(f"Voice generation failed. {hint} {err[-400:]}".strip())
    with sm() as s:
        a = _new_asset(s, out, kind=MediaKind.VOICE_AUDIO, status=MediaStatus.DRAFT, duration_s=info.get("seconds"),
                       synthetic=True, engine=f"chatterbox-{model} (local, {info.get('device')})", parent_ids=[ref_id],
                       text=text, created_by=str(actor), meta={"disclosure": DISCLOSURE})
        audit.record(s, who=str(actor), what="studio.speak", input={"chars": len(text)}, output={"seconds": info.get("seconds")},
                     tools_used=["chatterbox"], target_type="media_asset", target_id=a.id)
        s.commit()
        return to_dict(a)


def _check_budget(session: Session, projected: int) -> None:
    limit = usd_to_micros(sysconfig.get(session, "budget.daily_limit_usd"))
    day = spent_today(session)
    if day + projected > limit:
        raise BudgetExceeded(f"daily budget would be exceeded: spent ${micros_to_usd(day):.2f} + projected "
                             f"${micros_to_usd(projected):.2f} > ${micros_to_usd(limit):.2f}",
                             scope="daily", limit_usd=micros_to_usd(limit), spent_usd=micros_to_usd(day),
                             projected_usd=micros_to_usd(projected))


def make_video(sm: sessionmaker, actor: Actor, script: str, *, client=None, audio_asset_id: str | None = None) -> dict:
    """Script → voice (local) → the founder's face lip-synced to it (Replicate). Saved as a DRAFT."""
    _require_founder(actor)
    from aios.integrations.replicate import ReplicateClient

    with sm() as s:
        src = active(s, MediaKind.AVATAR_SOURCE)
        if src is None:
            raise ValidationFailed("No face footage yet. Run: aios avatar setup <video> --mine")
        model = sysconfig.get(s, "media.lipsync_model")
        rate = float(sysconfig.get(s, "media.lipsync_usd_per_second"))
        projected = usd_to_micros(sysconfig.get(s, "media.lipsync_projected_usd"))
        max_s = float(sysconfig.get(s, "media.lipsync_max_seconds"))
        _check_budget(s, projected)
        src_id, src_path, out_dir = src.id, Path(src.path), media_dir(s) / "video"
    client = client or ReplicateClient(get_settings().replicate_api_token)

    if audio_asset_id:
        with sm() as s:
            aud = s.get(MediaAsset, audio_asset_id)
            if aud is None or aud.kind != MediaKind.VOICE_AUDIO:
                raise NotFound(f"No generated audio {audio_asset_id}")
            audio = to_dict(aud)
    else:
        audio = speak(sm, actor, script)
    seconds = audio.get("duration_s") or probe_duration(Path(audio["path"]))
    if seconds > max_s:
        raise ValidationFailed(f"The audio is {seconds:.0f}s; the limit per video is {max_s:.0f}s "
                               "(media.lipsync_max_seconds). Split the script or raise the limit.")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"video-{audio['id'][:10]}"
    face = out_dir / f"{stem}-face.mp4"  # loop the footage so it is at least as long as the speech
    _ffmpeg(["-stream_loop", "-1", "-i", str(src_path), "-t", f"{seconds + 0.5:.2f}", "-an", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-r", "25", str(face)])

    version, props = client.latest_version(model)
    if props and not {"video", "audio"} <= set(props):
        raise AIOSError(f"{model} changed its inputs ({sorted(props)}); update aios/modules/studio.py.")
    pred = client.run(version, {"video": client.upload(face, "video/mp4"),
                                "audio": client.upload(Path(audio["path"]), "audio/wav")})
    cost = usd_to_micros(pred.predict_time_s * rate)
    with sm() as s:
        s.add(ModelUsage(workflow="studio", purpose="lipsync", provider="replicate", model=model,
                         estimated_cost_micros=cost, latency_ms=int(pred.predict_time_s * 1000),
                         success=pred.status == "succeeded", error=pred.error,
                         pricing_version=f"replicate-l40s@{rate}/s"))
        if pred.status != "succeeded" or not pred.output_url:
            audit.record(s, who=str(actor), what="studio.video", result="FAILED", error=pred.error or pred.status,
                         cost_micros=cost, tools_used=["replicate"])
            s.commit()
            raise AIOSError(f"Lip-sync failed on Replicate ({pred.status}): {pred.error or 'no output'}", prediction=pred.id)
        s.commit()
    final = out_dir / f"{stem}.mp4"
    client.download(pred.output_url, final)
    face.unlink(missing_ok=True)
    with sm() as s:
        a = _new_asset(s, final, kind=MediaKind.AVATAR_VIDEO, status=MediaStatus.DRAFT, duration_s=seconds,
                       synthetic=True, engine=f"replicate:{model}", parent_ids=[src_id, audio["id"]], text=audio.get("text"),
                       cost_micros=cost, created_by=str(actor),
                       meta={"disclosure": DISCLOSURE, "prediction_id": pred.id, "version": version,
                             "gpu_seconds": pred.predict_time_s})
        audit.record(s, who=str(actor), what="studio.video", cost_micros=cost, tools_used=["chatterbox", "replicate"],
                     output={"seconds": seconds, "cost_usd": micros_to_usd(cost)}, target_type="media_asset", target_id=a.id)
        s.commit()
        return to_dict(a)


def to_dict(a: MediaAsset) -> dict:
    return {"id": a.id, "kind": a.kind.value, "status": a.status.value, "path": a.path, "duration_s": a.duration_s,
            "synthetic": a.synthetic, "engine": a.engine, "cost_usd": micros_to_usd(a.cost_micros), "text": a.text,
            "parent_ids": a.parent_ids, "created_at": a.created_at.isoformat() if a.created_at else None,
            "disclosure": (a.meta or {}).get("disclosure")}


def list_assets(session: Session, limit: int = 40) -> list[dict]:
    rows = session.execute(select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(limit)).scalars()
    return [to_dict(a) for a in rows]
