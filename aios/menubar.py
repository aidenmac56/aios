"""Mac menu bar to-do list (top-right of the screen).

    aios menubar              run it now
    aios menubar --install    also start it when you log in (aios menubar --uninstall to stop)

Shows the founder's open to-dos with checkboxes, approvals waiting on him, and the system's own list
(tasks assigned to agents) with a "Run system tasks" button. Clicking one checks it off in AIOS (the same completion
`aios task … --status COMPLETED` does), clicking a checked one undoes it. The list re-reads the database
every 20 seconds, so new tasks from plans and `aios todo add` appear on their own.

It never starts work by itself: system tasks run only when the founder clicks "Run system tasks".
Needs: pip install rumps   (macOS only)
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
import webbrowser
from pathlib import Path

from aios.config import ROOT

LABEL = "com.aios.menubar"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
REFRESH_S = 20
MAX_SHOWN = 15


def _short(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def run() -> None:
    try:
        import rumps
    except ImportError:
        print("The menu bar app needs rumps:  pip install rumps", file=sys.stderr)
        raise SystemExit(2)

    from aios.bootstrap import init
    from aios.core.actor import FOUNDER
    from aios.core.errors import AIOSError
    from aios.modules import todos, workqueue

    sm = init()

    class TodoBar(rumps.App):
        def __init__(self):
            super().__init__("AIOS", title="☐", quit_button=None)
            self.signature = None
            self.queue, self.approvals = [], []
            self.refresh(None)
            self.timer = rumps.Timer(self.refresh, REFRESH_S)  # kept on self so it isn't garbage-collected
            self.timer.start()

        # ---- data
        def refresh(self, _):
            try:
                with sm() as s:
                    open_, done = todos.open_todos(s), todos.recently_done(s)
                    self.queue = workqueue.queue(s)
                    self.approvals = pending_approvals(s)
            except Exception as e:  # keep the icon alive; show the problem in the menu
                self.title = "☐ !"
                self._render([], [], error=str(e)[:80])
                return
            sig = ([(t["id"], t["status"]) for t in open_ + done + self.queue]
                   + [a["id"] for a in self.approvals])
            ready = [t for t in open_ if not t["waiting"]]
            mine = len(ready) + len(self.approvals)  # approvals are his to-dos too
            busy = " ⚙" if any(q["status"] == "RUNNING" for q in self.queue) else ""
            self.title = (f"☐ {mine}" if mine else "☑") + busy
            if sig != self.signature:  # rebuild only on change, so an open menu doesn't flicker
                self.signature = sig
                self._render(open_, done)

        # ---- view
        def _render(self, open_, done, error=None):
            self.menu.clear()
            items = []
            if error:
                items.append(rumps.MenuItem(f"Can't read AIOS: {error}"))
            ready = [t for t in open_ if not t["waiting"]]
            waiting = [t for t in open_ if t["waiting"]]
            if self.approvals:
                items.append(rumps.MenuItem("Needs your approval (click to copy the command)"))
                for a in self.approvals[:6]:
                    it = rumps.MenuItem(f"☐  {_short(a['action'])}", callback=self.copy_approval)
                    it.approval_id = a["id"]
                    items.append(it)
                items.append(rumps.separator)
            if not open_ and not self.approvals:
                items.append(rumps.MenuItem("Nothing to do. Nice."))
            for t in ready[:MAX_SHOWN]:
                items.append(self._item(t, checked=False))
            if len(ready) > MAX_SHOWN:
                items.append(rumps.MenuItem(f"+ {len(ready) - MAX_SHOWN} more (aios todo list)"))
            if waiting:
                items.append(rumps.separator)
                items.append(rumps.MenuItem("Waiting on something else first"))
                for t in waiting[:6]:
                    items.append(self._item(t, checked=False, dim=True))
            if done:
                items.append(rumps.separator)
                items.append(rumps.MenuItem("Done today (click to undo)"))
                for t in done[:8]:
                    items.append(self._item(t, checked=True))
            items.append(rumps.separator)
            items += self._system_section()
            items += [rumps.separator,
                      rumps.MenuItem("Add to-do…", callback=self.add),
                      rumps.MenuItem("Refresh", callback=self.refresh),
                      rumps.MenuItem("Open dashboard", callback=lambda _: webbrowser.open("http://127.0.0.1:8787")),
                      rumps.separator,
                      rumps.MenuItem("Quit", callback=rumps.quit_application)]
            seen: dict[str, int] = {}
            for it in items:  # rumps keys menu items by title; keep identical titles from replacing each other
                if isinstance(it, rumps.MenuItem):
                    n = seen.get(it.title, 0)
                    seen[it.title] = n + 1
                    if n:
                        it.title = it.title + "\u200b" * n
            self.menu = items

        def _system_section(self):
            q = getattr(self, "queue", [])
            ready = [x for x in q if x["status"] in ("READY", "FAILED")]
            running = [x for x in q if x["status"] == "RUNNING"]
            sub = [rumps.MenuItem(f"{x['status'].lower():<8} {x['agent']}: {_short(x['title'], 55)}") for x in q[:20]]
            if not sub:
                sub = [rumps.MenuItem("Nothing queued")]
            head = rumps.MenuItem(f"System's list ({len(q)})")
            if running:
                run_item = rumps.MenuItem(f"⚙ System is working on {len(running)}…")
            elif ready:
                run_item = rumps.MenuItem(f"▶ Run system tasks ({min(3, len(ready))} of {len(ready)} ready)",
                                          callback=self.run_system)
            else:
                run_item = rumps.MenuItem("Nothing ready for the system")
            return [(head, sub), run_item]

        def run_system(self, _):
            """The founder's click starts one `aios work run` (up to 3 tasks, budget-checked)."""
            log = (ROOT / "data" / "work.log").open("a")
            subprocess.Popen([sys.executable, "-m", "aios.cli", "work", "run", "--max", "3"], cwd=str(ROOT),
                             stdout=log, stderr=log, start_new_session=True)
            rumps.notification("AIOS", "Running system tasks", "Up to 3. The list updates as each one finishes.")
            self.signature = None
            self.soon = rumps.Timer(lambda t: (t.stop(), self.refresh(None)), 3)
            self.soon.start()

        def copy_approval(self, item):
            subprocess.run(["pbcopy"], input=f"aios approve {item.approval_id}".encode())
            rumps.notification("AIOS", "Copied", f"aios approve {item.approval_id}  (paste in Terminal; "
                               f"aios approvals shows details)")

        def _item(self, t, checked: bool, dim: bool = False):
            label = ("   " if dim else "") + f"P{t['priority']}  {_short(t['title'])}"
            if t.get("project"):
                label += f"  · {_short(t['project'], 24)}"
            item = rumps.MenuItem(label, callback=None if dim else self.toggle)
            item.state = 1 if checked else 0
            item.task_id = t["id"]
            return item

        # ---- actions (the founder's own clicks)
        def toggle(self, item):
            try:
                with sm() as s:
                    if item.state:
                        todos.reopen(s, FOUNDER, item.task_id)
                    else:
                        todos.complete(s, FOUNDER, item.task_id, note="checked off in the menu bar")
                    s.commit()
            except AIOSError as e:
                rumps.alert("Couldn't update", e.message)
            self.signature = None
            self.refresh(None)

        def add(self, _):
            w = rumps.Window(message="What do you need to do?", title="Add to-do", default_text="",
                             ok="Add", cancel="Cancel", dimensions=(320, 24))
            r = w.run()
            if r.clicked and r.text.strip():
                with sm() as s:
                    todos.add(s, FOUNDER, r.text.strip())
                    s.commit()
                self.signature = None
                self.refresh(None)

    try:  # menu bar only: no Dock icon
        from AppKit import NSApplication

        NSApplication.sharedApplication().setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
    except Exception:
        pass
    TodoBar().run()


def pending_approvals(session) -> list[dict]:
    from sqlalchemy import select

    from aios.db.enums import ApprovalStatus
    from aios.db.models import Approval

    rows = session.execute(select(Approval).where(Approval.status == ApprovalStatus.PENDING)
                           .order_by(Approval.created_at.desc())).scalars()
    return [{"id": a.id, "action": a.action} for a in rows]


def install() -> Path:
    """Start the menu bar app at login (a LaunchAgent). It only shows the list; it runs nothing else."""
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    logs = ROOT / "data"
    logs.mkdir(exist_ok=True)
    PLIST.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "aios.menubar"],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(logs / "menubar.log"),
        "StandardErrorPath": str(logs / "menubar.log"),
    }))
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST)], check=False)
    return PLIST


def uninstall() -> None:
    if PLIST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink()


if __name__ == "__main__":
    run()
