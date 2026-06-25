"""Make installed.json writes safe across processes.

The plugin, the download subprocess, and the save-sync subprocess each hold
their own LegendaryCore with a cached ``_installed`` dict, and legendary's
``set_installed_game`` / ``remove_installed_game`` do a blind, unlocked
``json.dump`` of that cache. Two processes writing around the same time
last-writer-wins on the whole file, so one can silently drop another's game.

We monkey-patch those two methods to, under a dedicated cross-process file lock:
reload the on-disk state, apply just this one change on top of it, then write.
A stale in-memory cache can no longer clobber another process's entries.

We use our OWN lock file rather than legendary's ``_installed_lock`` (which
``lock_installed`` acquires and never releases for an instance's lifetime —
sharing it would deadlock our long-lived plugin against the subprocesses).
"""
from __future__ import annotations

import json
import os
import threading

from filelock import FileLock, Timeout

_LOCK_TIMEOUT = 20.0
_locks: dict[str, FileLock] = {}
_guard = threading.Lock()


def _lock_for(installed_path: str) -> FileLock:
    # One reentrant FileLock instance per path per process (reused so nested
    # same-process calls don't self-deadlock).
    with _guard:
        lock = _locks.get(installed_path)
        if lock is None:
            lock = FileLock(installed_path + ".decky.lock", timeout=_LOCK_TIMEOUT)
            _locks[installed_path] = lock
        return lock


def apply_installed_json_locking() -> None:
    """Idempotently patch LGDLFS write methods. Call after importing legendary
    in every process that may write installed.json."""
    from legendary.lfs.lgndry import LGDLFS

    if getattr(LGDLFS, "_decky_locked", False):
        return

    def _ipath(self) -> str:
        return os.path.join(self.path, "installed.json")

    def _reload(self) -> None:
        try:
            with open(_ipath(self), "r", encoding="utf-8") as f:
                self._installed = json.load(f)
        except FileNotFoundError:
            self._installed = {}
        except Exception:
            pass  # keep whatever we had rather than lose data

    def _write(self) -> None:
        path = _ipath(self)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._installed, f, indent=2, sort_keys=True)
        os.replace(tmp, path)

    def set_installed_game(self, app_name, install_info) -> None:
        try:
            with _lock_for(_ipath(self)):
                _reload(self)
                if self._installed is None:
                    self._installed = {}
                if app_name in self._installed:
                    self._installed[app_name].update(install_info.__dict__)
                else:
                    self._installed[app_name] = install_info.__dict__
                _write(self)
        except Timeout:
            # Never hang a download/launch on the lock; fall back to a plain
            # reload+write (best effort).
            _reload(self)
            if self._installed is None:
                self._installed = {}
            self._installed[app_name] = install_info.__dict__
            _write(self)

    def remove_installed_game(self, app_name) -> None:
        try:
            with _lock_for(_ipath(self)):
                _reload(self)
                if self._installed and app_name in self._installed:
                    del self._installed[app_name]
                    _write(self)
        except Timeout:
            _reload(self)
            if self._installed and app_name in self._installed:
                del self._installed[app_name]
                _write(self)

    LGDLFS.set_installed_game = set_installed_game
    LGDLFS.remove_installed_game = remove_installed_game
    LGDLFS._decky_locked = True
