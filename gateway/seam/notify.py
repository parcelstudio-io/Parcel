"""``sd_notify`` for the gateway unit — readiness that is earned, not announced.

``deploy/orin/services/parcel-gateway.service`` declares ``Type=notify`` with
``NotifyAccess=main`` and ``WatchdogSec=2``.  That is a two-way contract:

* systemd holds the unit in ``activating`` until the process sends
  ``READY=1``, so anything ordered ``After=`` this unit does not start early;
  and
* once active the process must send ``WATCHDOG=1`` at least every
  ``WatchdogSec``, or systemd declares it hung and applies the unit's restart
  policy.

Both halves are only worth anything if the messages are **evidence**.  A
process that sends ``READY=1`` from the top of ``main()`` and pings from a bare
``while True: sleep()`` has implemented the protocol and defeated its purpose:
it will keep reporting healthy with a wedged control loop, which is exactly the
failure this card exists to make impossible.  So:

* :meth:`GatewayLivenessNotifierV1.announce_ready` sends ``READY=1`` only after
  a caller-supplied *readiness predicate* is true **and** one bounded liveness
  probe has come back; and
* every subsequent ``WATCHDOG=1`` is preceded by another bounded probe, on the
  ping thread, and is **not sent** if that probe did not return in its budget.

The probe runs through :class:`~gateway.seam.vendor_io.BoundedCallLaneV1` — the
same primitive that contains the vendor calls — so a probe that blocks forever
(because the core lock is held by something that is never coming back) costs
one lane thread and silences the pings, instead of blocking the ping thread and
silently keeping the unit "healthy".

**Lock ordering.** This module takes no lock of its own beyond the lane's own
leaf condition, and the probe it is given must not call back into it.

**Outside systemd it is inert.**  With no ``NOTIFY_SOCKET`` in the environment
:class:`SdNotifierV1` is a no-op that records what it *would* have sent, which
is what makes the desktop bench able to test the sequencing at all.
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .vendor_io import BoundedCallLaneV1

#: systemd's own environment variable names (``sd_notify(3)``, ``systemd.service(5)``).
NOTIFY_SOCKET_ENV = "NOTIFY_SOCKET"
WATCHDOG_USEC_ENV = "WATCHDOG_USEC"
WATCHDOG_PID_ENV = "WATCHDOG_PID"

#: Ping at a **quarter** of the watchdog interval, not the half
#: ``sd_watchdog_enabled(3)`` suggests, and the difference is derived rather
#: than cautious.  A ping is only sent after a bounded probe of the core lock
#: returns, and a *legitimate* stop legitimately holds that lock for up to
#: ``stop_timeout_s`` (1.0 s shipped).  The worst gap between successful pings
#: is therefore ``ping_period + stop_timeout_s``, and the unit's
#: ``WatchdogSec=2`` needs that to stay under 2.0 s: a half-interval ping
#: (1.0 + 1.0 = 2.0 s) sits exactly on the limit and would restart the gateway
#: during a healthy stop; a quarter-interval ping (0.5 + 1.0 = 1.5 s) leaves
#: 0.5 s of margin.  This is why the service file needs no ``WatchdogSec``
#: edit.
WATCHDOG_PING_FRACTION = 0.25


@dataclass(frozen=True)
class SupervisionV1:
    """What the supervisor asked of this process, read from the environment."""

    notify_address: str
    watchdog_period_s: float

    @property
    def supervised(self) -> bool:
        return bool(self.notify_address)

    @property
    def watchdog_enabled(self) -> bool:
        return self.supervised and self.watchdog_period_s > 0.0


def read_supervision(environ: dict[str, str] | None = None) -> SupervisionV1:
    """Read ``NOTIFY_SOCKET`` / ``WATCHDOG_USEC`` the way ``sd_notify(3)`` does."""

    source = dict(os.environ) if environ is None else dict(environ)
    address = source.get(NOTIFY_SOCKET_ENV, "")
    watchdog_pid = source.get(WATCHDOG_PID_ENV, "")
    period_s = 0.0
    if not watchdog_pid or watchdog_pid == str(os.getpid()):
        raw = source.get(WATCHDOG_USEC_ENV, "")
        if raw.isdigit():
            period_s = int(raw) / 1_000_000.0 * WATCHDOG_PING_FRACTION
    return SupervisionV1(notify_address=address, watchdog_period_s=period_s)


class SdNotifierV1:
    """A minimal ``sd_notify`` datagram client. Inert with no supervisor."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._sent: list[str] = []
        self._errors = 0

    @property
    def supervised(self) -> bool:
        return bool(self._address)

    @property
    def sent(self) -> tuple[str, ...]:
        """Everything this notifier has emitted, in order. Bench observability."""

        return tuple(self._sent)

    @property
    def errors(self) -> int:
        return self._errors

    def ready(self, status: str = "") -> bool:
        message = "READY=1"
        if status:
            message = f"{message}\nSTATUS={status}"
        return self.send(message)

    def watchdog(self) -> bool:
        return self.send("WATCHDOG=1")

    def stopping(self, status: str = "") -> bool:
        message = "STOPPING=1"
        if status:
            message = f"{message}\nSTATUS={status}"
        return self.send(message)

    def send(self, message: str) -> bool:
        """Emit one datagram. Never raises: a supervisor is not a control path."""

        self._sent.append(message)
        if not self._address:
            return False
        path = self._address
        if path.startswith("@"):
            # Abstract namespace, as ``sd_notify(3)`` specifies.
            path = "\0" + path[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as datagram:
                datagram.settimeout(0.5)
                datagram.sendto(message.encode("utf-8"), path)
        except OSError:
            self._errors += 1
            return False
        return True


class GatewayLivenessNotifierV1:
    """READY and WATCHDOG, each behind a bounded probe of the real gateway.

    ``probe`` must be a cheap, side-effect-free call that genuinely touches the
    thing whose liveness is being claimed — for the gateway that means reading
    a value guarded by the core lock, so a wedged core makes the probe block
    and the pings stop.
    """

    def __init__(
        self,
        notifier: SdNotifierV1,
        probe: Callable[[], object],
        *,
        watchdog_period_s: float,
        probe_timeout_s: float,
    ) -> None:
        self._notifier = notifier
        self._watchdog_period_s = max(0.0, watchdog_period_s)
        self._probe_timeout_s = max(0.0, probe_timeout_s)
        self._lane = BoundedCallLaneV1("liveness-probe", lambda _payload: probe())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = False
        self._pings = 0
        self._missed = 0

    @property
    def ready_announced(self) -> bool:
        return self._ready

    @property
    def pings(self) -> int:
        return self._pings

    @property
    def missed_probes(self) -> int:
        return self._missed

    def probe_once(self) -> bool:
        """One bounded liveness probe. False means it did not come back in time."""

        return self._lane.invoke(None, self._probe_timeout_s).ok

    def announce_ready(self, *, status: str = "") -> bool:
        """Send ``READY=1`` — but only if the process really is ready."""

        if self._ready:
            return True
        if not self.probe_once():
            self._missed += 1
            return False
        delivered = self._notifier.ready(status)
        # With no supervisor this return value represents local readiness for
        # desktop benches. Under Type=notify, a failed datagram is not an
        # announcement; leave readiness false so the caller can retry.
        if self._notifier.supervised and not delivered:
            self._missed += 1
            return False
        self._ready = True
        return True

    def start(self) -> None:
        """Begin the ping loop. Each ping is earned by its own probe."""

        if self._thread is not None or self._watchdog_period_s <= 0.0:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="parcel-gateway-sd-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, status: str = "") -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=max(1.0, self._watchdog_period_s * 2.0))
        if self._ready:
            self._notifier.stopping(status)
        self._lane.close()

    def _run(self) -> None:
        while not self._stop.wait(self._watchdog_period_s):
            if not self._ready:
                continue
            if self.probe_once():
                self._pings += 1
                self._notifier.watchdog()
            else:
                # Deliberately silent.  A missed ping is the signal; inventing
                # one here would be the exact lie this module exists to avoid.
                self._missed += 1
