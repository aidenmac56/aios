"""Studio: voice and face clone. Real ffmpeg, fake TTS worker, fake Replicate; no network, no GPU."""

import shutil
import subprocess
import sys
import textwrap

import pytest
from sqlalchemy import select

from aios.core import sysconfig
from aios.core.actor import FOUNDER, agent
from aios.core.errors import BudgetExceeded, PermissionDenied, ValidationFailed
from aios.db.enums import MediaKind, MediaStatus
from aios.db.models import AuditLog, MediaAsset, ModelUsage, WorkflowRun
from aios.integrations.replicate import Prediction
from aios.modules import studio

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture
def media(tmp_path, sm, monkeypatch):
    with sm() as s:
        sysconfig.set_value(s, "media.dir", str(tmp_path / "media"), FOUNDER, "test")
        s.commit()
    voice = tmp_path / "me.m4a"
    face = tmp_path / "me.mov"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=12",
                    str(voice)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=6",
                    str(face)], check=True)
    worker = tmp_path / "fake_worker.py"  # stands in for Chatterbox: copies the reference as the "speech"
    worker.write_text(textwrap.dedent("""
        import argparse, json, shutil
        ap = argparse.ArgumentParser()
        for a in ("--text-file", "--ref", "--out", "--model", "--device"):
            ap.add_argument(a)
        a = ap.parse_args()
        shutil.copy(a.ref, a.out)
        print(json.dumps({"ok": True, "out": a.out, "seconds": 12.0, "device": "cpu"}))
    """))
    monkeypatch.setattr(studio, "WORKER", worker)
    return {"voice": voice, "face": face, "dir": tmp_path / "media"}


class FakeReplicate:
    def __init__(self, predict_time=100.0, status="succeeded"):
        self.calls = []
        self.predict_time, self.status = predict_time, status

    def latest_version(self, model):
        return "ver123", {"video": {}, "audio": {}, "guidance_scale": {}}

    def upload(self, path, content_type):
        assert path.exists()
        return f"https://files.example/{path.name}"

    def run(self, version, inputs):
        self.calls.append(inputs)
        return Prediction(id="pred1", status=self.status, output_url="https://out.example/v.mp4" if self.status == "succeeded" else None,
                          predict_time_s=self.predict_time, error=None if self.status == "succeeded" else "boom", version=version)

    def download(self, url, dest):
        dest.write_bytes(b"fake mp4")


def test_setup_requires_founder_and_own_recording(sm, media):
    with sm() as s:
        with pytest.raises(PermissionDenied):
            studio.setup_voice(s, agent("cmo"), media["voice"], confirm_own_voice=True)
        with pytest.raises(ValidationFailed):
            studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=False)
        first = studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=True)
        second = studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=True, start_s=1, seconds=10)
        s.commit()
        assert s.get(MediaAsset, first.id).status == MediaStatus.RETIRED
        assert studio.active(s, MediaKind.VOICE_REFERENCE).id == second.id
        assert second.meta["founder_confirmed_own_voice"] is True
        assert s.execute(select(AuditLog).where(AuditLog.what == "studio.voice_setup")).scalars().all()


def test_speak_strips_stage_directions_and_saves_a_synthetic_draft(sm, media):
    with sm() as s:
        studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=True)
        s.commit()
    with pytest.raises(PermissionDenied):
        studio.speak(sm, agent("twin"), "hello")
    a = studio.speak(sm, FOUNDER, "## Intro\n[B-roll: phone ringing]\nAIDEN: Missed calls cost you jobs. [laugh]\n(cut to screen)")
    assert a["kind"] == "VOICE_AUDIO" and a["status"] == "DRAFT" and a["synthetic"]
    assert a["text"] == "Missed calls cost you jobs. [laugh]"
    assert "Altered or synthetic content" in a["disclosure"]


def test_video_records_measured_cost_and_stays_a_draft(sm, media):
    with sm() as s:
        studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=True)
        studio.setup_avatar(s, FOUNDER, media["face"], confirm_own_face=True)
        s.commit()
    rep = FakeReplicate(predict_time=100.0)
    v = studio.make_video(sm, FOUNDER, "Missed calls cost you jobs.", client=rep)
    assert v["kind"] == "AVATAR_VIDEO" and v["status"] == "DRAFT" and v["synthetic"]
    assert v["cost_usd"] == pytest.approx(0.0975)
    assert set(rep.calls[0]) == {"video", "audio"}
    with sm() as s:
        use = s.execute(select(ModelUsage).where(ModelUsage.provider == "replicate")).scalar_one()
        assert use.estimated_cost_micros == 97500 and use.workflow == "studio"
        log = s.execute(select(AuditLog).where(AuditLog.what == "studio.video")).scalar_one()
        assert log.cost_micros == 97500


def test_video_blocked_by_daily_budget_before_any_spend(sm, media):
    with sm() as s:
        studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=True)
        studio.setup_avatar(s, FOUNDER, media["face"], confirm_own_face=True)
        sysconfig.set_value(s, "budget.daily_limit_usd", 0.10, FOUNDER, "test")
        s.commit()
    rep = FakeReplicate()
    with pytest.raises(BudgetExceeded):
        studio.make_video(sm, FOUNDER, "hi there", client=rep)
    assert rep.calls == []


def test_failed_lipsync_is_recorded_not_hidden(sm, media):
    with sm() as s:
        studio.setup_voice(s, FOUNDER, media["voice"], confirm_own_voice=True)
        studio.setup_avatar(s, FOUNDER, media["face"], confirm_own_face=True)
        s.commit()
    with pytest.raises(Exception, match="Lip-sync failed"):
        studio.make_video(sm, FOUNDER, "hello", client=FakeReplicate(predict_time=10, status="failed"))
    with sm() as s:
        use = s.execute(select(ModelUsage).where(ModelUsage.provider == "replicate")).scalar_one()
        assert use.success is False and use.estimated_cost_micros == 9750
        assert not s.execute(select(MediaAsset).where(MediaAsset.kind == MediaKind.AVATAR_VIDEO)).scalars().all()


def test_script_from_draft_run_needs_item_when_ambiguous(sm):
    with sm() as s:
        r = WorkflowRun(command="draft", request="x", result={"draft": {"items": [{"label": "A", "text": "one"},
                                                                                   {"label": "B", "text": "two"}]}})
        s.add(r)
        s.commit()
        with pytest.raises(ValidationFailed, match="--item"):
            studio.script_from_run(s, r.id, None)
        assert studio.script_from_run(s, r.id, 2) == "two"


def test_cli_registers_studio_commands():
    out = subprocess.run([sys.executable, "-m", "aios.cli", "voice", "--help"], capture_output=True, text=True)
    assert "--mine" in out.stdout
