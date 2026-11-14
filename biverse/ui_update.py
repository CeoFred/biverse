"""The operator window's side of in-app updates (``biverse/updates.py`` does the work).

Checks by itself (unless turned off in Settings -> Updates) at most twice a
day and never while listening; offers the update with Download / Later / Skip
this version; downloads in the background with progress in the status bar
(cancel and resume from Help -> Check for updates); then installs with
"Restart now" or "When I close Biverse". Offers wait while Biverse is
listening, so nothing pops up during a service.
"""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Optional, Sequence

from . import APP_NAME, __version__, updates
from .downloads import Job, mb

log = logging.getLogger(__name__)

FIRST_CHECK_MS = 30 * 1000       # after start-up settles
RECHECK_MS = 10 * 60 * 1000      # how often to see whether a check is due
CHECK_INTERVAL = 12 * 3600       # seconds between automatic checks


class _UpdateItem(object):
    """What ``downloads.Job`` needs to describe an update download."""

    kind = "update"

    def __init__(self, update: updates.Update) -> None:
        self.id = "update"
        self.label = "%s %s" % (APP_NAME, update.version)
        self._size = update.size

    def size(self) -> int:
        return self._size


def choose(parent, pal: dict, title: str, message: str, buttons: Sequence[str], link: str = "",
           link_text: str = "") -> Optional[str]:
    """A small modal dialog with custom buttons; returns the pressed button's text (None if closed)."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(background=pal.get("bg", ""))
    win.transient(parent)
    win.resizable(False, False)
    result = {"value": None}  # type: dict
    body = ttk.Frame(win, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=message, wraplength=420, justify="left").pack(anchor="w")
    if link:
        lnk = ttk.Label(body, text=link_text or link, cursor="hand2")
        lnk.configure(foreground=pal.get("accent", "blue"))
        lnk.pack(anchor="w", pady=(8, 0))
        lnk.bind("<Button-1>", lambda e: webbrowser.open(link))
    row = ttk.Frame(body)
    row.pack(fill="x", pady=(14, 0))

    def press(text):
        result["value"] = text
        win.destroy()

    for i, text in enumerate(reversed(list(buttons))):
        b = ttk.Button(row, text=text, command=lambda t=text: press(t))
        b.pack(side="right", padx=(6, 0))
        if i == len(buttons) - 1:
            b.focus_set()
            win.bind("<Return>", lambda e, t=text: press(t))
    win.bind("<Escape>", lambda e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.update_idletasks()
    try:
        x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))
    except tk.TclError:
        pass
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


class UpdateController(object):
    def __init__(self, op) -> None:
        self.op = op
        self.update = None  # type: Optional[updates.Update]
        self.job = None  # type: Optional[Job]
        self.zip_path = ""
        self.new_root = ""          # unpacked, ready-to-install copy
        self.problem = ""           # why this copy cannot replace itself
        self.install_on_close = False
        self._checking = False
        self._pending = ""          # "offer" | "install" | "manual": waits while listening

    # -- start-up -------------------------------------------------------------------------
    def start(self) -> None:
        self._report_last_install()
        self.op.root.after(FIRST_CHECK_MS, self._auto_check)

    def _report_last_install(self) -> None:
        try:
            result = updates.take_result()
        except Exception:
            log.exception("reading the update result")
            return
        if not result:
            return
        if result.get("ok"):
            self.op._status("Updated to %s %s" % (APP_NAME, result.get("version", __version__)))
            log.info("updated to %s", result.get("version"))
        else:
            log.warning("update to %s failed: %s", result.get("version"), result.get("detail"))
            messagebox.showerror(APP_NAME, "The update to %s %s could not be installed:\n\n%s\n\n%s %s is "
                                 "still installed." % (APP_NAME, result.get("version", "?"), result.get("detail", ""),
                                                       APP_NAME, __version__), parent=self.op.root)

    # -- checking -------------------------------------------------------------------------
    def busy(self) -> bool:
        return self._checking or (self.job is not None and self.job.state == "running")

    def _auto_check(self) -> None:
        op = self.op
        if op._closing:
            return
        s = op.settings
        due = time.time() - float(s["update_last_check"] or 0) >= CHECK_INTERVAL
        if s["update_check"] and due and not op.listening and not self.busy() and not self.new_root:
            self.check(manual=False)
        op.root.after(RECHECK_MS, self._auto_check)

    def check(self, manual: bool = True) -> None:
        """Help -> Check for updates (manual) or the automatic check."""
        if self.job is not None and self.job.state == "running":
            if manual and messagebox.askyesno(
                    APP_NAME, "%s is downloading (%s).\n\nCancel the download? Checking again later continues "
                    "where it stopped." % (self.job.item.label, self.job.describe()), parent=self.op.root):
                self.job.cancel_event.set()
            return
        if self.new_root and manual:
            self._offer_install()
            return
        if self._checking:
            return
        self._checking = True
        if manual:
            self.op._status("Checking for updates…")

        def work():
            try:
                found, error = updates.check(), ""
            except updates.UpdateError as exc:
                found, error = None, str(exc)
            except Exception as exc:
                log.exception("update check")
                found, error = None, str(exc) or exc.__class__.__name__
            self.op.events.put(("update", "checked", (manual, found, error)))

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def on_event(self, kind: str, payload) -> None:
        if kind == "checked":
            self._on_checked(*payload)
        elif kind == "downloaded":
            self._on_downloaded()

    def _on_checked(self, manual: bool, found: Optional[updates.Update], error: str) -> None:
        self._checking = False
        s = self.op.settings
        if not manual:
            s["update_last_check"] = time.time()
            s.save()
        if error:
            log.info("update check: %s", error)
            if manual:
                self.op._status("")
                messagebox.showinfo(APP_NAME, "Could not check for updates: %s." % error, parent=self.op.root)
            return
        if found is None:
            log.info("no update (have %s)", __version__)
            if manual:
                self.op._status("")
                messagebox.showinfo(APP_NAME, "You have the latest version (%s %s)." % (APP_NAME, __version__),
                                    parent=self.op.root)
            return
        log.info("update available: %s", found.version)
        if not manual and found.version == s["update_skipped"]:
            return
        self.update = found
        self._show("manual" if manual else "offer")

    # -- dialogs wait while listening -------------------------------------------------------
    def _show(self, what: str) -> None:
        if self.op.listening and what != "manual":
            self._pending = what
            return
        self._pending = ""
        if what in ("offer", "manual"):
            self._offer()
        elif what == "install":
            self._offer_install()

    def poll(self) -> None:
        """Called about once a second by the operator window."""
        if self._pending and not self.op.listening:
            self._show(self._pending)

    def status_text(self) -> str:
        if self.job is not None and self.job.state == "running":
            return "Update %s: %s" % (self.job.item.label, self.job.describe())
        return ""

    def _offer(self) -> None:
        u = self.update
        if u is None:
            return
        choice = choose(self.op.root, self.op.pal, "Update available",
                        "%s %s is available. You have %s.\n\nThe download is %s. It continues in the background "
                        "while you work, and is installed when you restart %s." % (
                            APP_NAME, u.version, __version__, mb(u.size), APP_NAME),
                        ["Download", "Later", "Skip this version"], link=u.notes_url, link_text="What's new")
        if choice == "Download":
            self.download()
        elif choice == "Skip this version":
            self.op.settings["update_skipped"] = u.version
            self.op.settings.save()
            self.op._status("%s %s will not be offered again" % (APP_NAME, u.version))

    # -- downloading ----------------------------------------------------------------------
    def download(self) -> None:
        u = self.update
        if u is None or (self.job is not None and self.job.state == "running"):
            return
        job = Job(_UpdateItem(u))  # type: ignore[arg-type]
        self.job = job

        def work():
            try:
                job.path = self.zip_path = updates.download(u, job.update, job.cancel_event)
                job.update(u.size, u.size, "unpack")
                self.problem = updates.install_problem()
                if not self.problem:
                    self.new_root = updates.stage(job.path, u.version)
                job.state = "done"
            except updates.catalog.Cancelled:
                job.state = "cancelled"
            except updates.UpdateError as exc:
                job.state, job.error = "failed", str(exc)
            except Exception as exc:
                log.exception("update download")
                job.state, job.error = "failed", str(exc) or exc.__class__.__name__
            self.op.events.put(("update", "downloaded", None))

        threading.Thread(target=work, name="update-download", daemon=True).start()
        self.op._status("Update %s: %s" % (job.item.label, job.describe()))

    def _on_downloaded(self) -> None:
        job, op = self.job, self.op
        if job is None or op._closing:
            return
        label = job.item.label
        if job.state == "cancelled":
            op._status("%s download cancelled. Help → Check for updates continues it." % label)
            return
        if job.state == "failed":
            op._status("%s was not downloaded" % label, error=True)
            if not op.listening:
                messagebox.showerror(APP_NAME, "%s could not be downloaded: %s" % (label, job.error),
                                     parent=op.root)
            return
        if self.problem:
            op._status("%s is downloaded" % label)
            if messagebox.askyesno(
                    APP_NAME, "%s is downloaded, but %s cannot install it by itself: %s.\n\nShow the downloaded "
                    "zip? Unzip it and replace %s with the new copy." % (label, APP_NAME, self.problem, APP_NAME),
                    parent=op.root):
                updates.open_file(self.zip_path)
            return
        op._status("%s is ready to install" % label)
        self._show("install")

    # -- installing -----------------------------------------------------------------------
    def _offer_install(self) -> None:
        if not self.new_root or self.update is None:
            return
        choice = choose(self.op.root, self.op.pal, "Install update",
                        "%s %s is ready. Install it now (%s closes and opens again, which takes a moment) or "
                        "when you close %s?" % (APP_NAME, self.update.version, APP_NAME, APP_NAME),
                        ["Restart now", "When I close %s" % APP_NAME])
        if choice == "Restart now":
            self.restart_now()
        elif choice is not None:
            self.install_on_close = True
            self.op._status("%s %s will be installed when you close %s" % (APP_NAME, self.update.version, APP_NAME))

    def restart_now(self) -> None:
        op = self.op
        if op.listening and not messagebox.askyesno(
                APP_NAME, "%s is listening. Stop listening and restart now?" % APP_NAME, parent=op.root):
            return
        try:
            updates.launch_installer(self.new_root, updates.app_root(), relaunch=True)
        except Exception as exc:
            log.exception("starting the installer")
            messagebox.showerror(APP_NAME, "The update could not be started: %s" % exc, parent=op.root)
            return
        self.install_on_close = False
        op.close()

    def on_close(self) -> None:
        """Called by the operator window as it closes."""
        if self.job is not None and self.job.state == "running":
            self.job.cancel_event.set()  # the .part file is kept and resumed next time
        if self.install_on_close and self.new_root:
            try:
                updates.launch_installer(self.new_root, updates.app_root(), relaunch=False)
            except Exception:
                log.exception("starting the installer on close")
