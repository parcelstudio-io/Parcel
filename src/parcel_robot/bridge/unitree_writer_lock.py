"""Device-wide Unitree SDK writer authority shared by product and gateway.

This module is deliberately pure standard library.  The separately packaged
``gateway`` distribution already depends on ``parcel-robot-dog`` for its wire
protocol; keeping the lock beside that protocol preserves the dependency
direction while giving the supervised commissioning CLI and the autonomous
gateway one kernel-enforced authority inode.

The inode is persistent and must never be unlinked while locked.  A physical
SDK activation is also irreversible for the lifetime of the Python process:
Unitree's public lease client exposes no release/thread-shutdown operation.
Call :meth:`retain_until_process_exit` immediately before that irreversible
boundary.  After retention, :meth:`close` intentionally does nothing and the
OS releases the descriptor only when the process terminates.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import threading
from pathlib import Path

UNITREE_WRITER_LOCK_PATH = Path("/run/parcel-gateway/unitree-writer.lock")
UNITREE_WRITER_LOCK_MODE = 0o600

# Strong references are the process-lifetime retention mechanism.  The list is
# private so ordinary callers cannot release a physical SDK authority claim by
# dropping their local object.
_RETAINED_LOCKS: list[UnitreeWriterLockV1] = []
_RETAINED_LOCKS_GUARD = threading.Lock()


class UnitreeWriterLockV1:
    """Interprocess guard acquired before any Unitree writer construction."""

    def __init__(self, *, required: bool, path: str | Path | None = None) -> None:
        self._required = bool(required)
        self.path = Path(path) if path is not None else UNITREE_WRITER_LOCK_PATH
        self._fd: int | None = None
        self._retained = False

    @property
    def held(self) -> bool:
        return self._fd is not None

    @property
    def retained_until_process_exit(self) -> bool:
        return self._retained

    def acquire(self) -> None:
        if not self._required:
            return
        if self._fd is not None:
            raise RuntimeError("Unitree writer authority is already held")
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, UNITREE_WRITER_LOCK_MODE)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise FileExistsError(f"refusing non-regular Unitree writer lock {self.path}")
            if metadata.st_uid != os.geteuid():
                raise PermissionError(
                    f"Unitree writer lock is not owned by uid {os.geteuid()}: {self.path}"
                )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise FileExistsError(
                        errno.EEXIST,
                        f"another process holds Unitree writer authority at {self.path}",
                        str(self.path),
                    ) from exc
                raise
            os.fchmod(fd, UNITREE_WRITER_LOCK_MODE)
            current = self.path.lstat()
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_uid != os.geteuid()
                or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino)
            ):
                raise FileExistsError(
                    f"Unitree writer lock path changed while acquiring {self.path}"
                )
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd

    def retain_until_process_exit(self) -> None:
        """Make an acquired physical authority irreversible in this process."""

        if not self._required:
            return
        if self._fd is None:
            raise RuntimeError("cannot retain Unitree writer authority before acquiring it")
        with _RETAINED_LOCKS_GUARD:
            if self._retained:
                return
            self._retained = True
            _RETAINED_LOCKS.append(self)

    def close(self) -> None:
        if self._retained:
            return
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
