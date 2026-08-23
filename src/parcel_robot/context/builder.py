from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from .models import ContextBuildConfig, ContextField, ContextSnapshot
from .providers import ContextProvider

# ---- CARD HW-1 py310-clean (scrum/20260822/task_35) ----
# ``datetime.UTC`` is 3.11+; the Orin's JetPack CPython is 3.10 (design §5.1,
# seam S22). ``datetime.UTC`` IS ``timezone.utc`` — the same singleton — so the
# alias keeps every call site, ``tzinfo`` identity and ``isoformat`` unchanged.
UTC = timezone.utc
# ---- END CARD HW-1 py310-clean ----


class ContextBuilder:
    """Build local, typed runtime context under feature gates and one deadline."""

    def __init__(
        self,
        config: ContextBuildConfig,
        providers: dict[str, ContextProvider] | None = None,
    ):
        self.config = config
        self.providers = dict(providers or {})
        self._cache: dict[str, ContextField] = {}
        self._lock = threading.RLock()

    def register(self, provider: ContextProvider) -> None:
        with self._lock:
            self.providers[provider.kind] = provider

    def build(self, now: datetime | None = None) -> ContextSnapshot:
        generated_at = now or datetime.now(UTC)
        kinds = self.config.enabled_kinds()
        if not kinds:
            return ContextSnapshot(generated_at=generated_at)

        with self._lock:
            providers = {kind: self.providers.get(kind) for kind in kinds}
            cache = dict(self._cache)
        fields: dict[str, ContextField] = {}
        errors: dict[str, str] = {}
        jobs = {}
        available = {kind: provider for kind, provider in providers.items() if provider is not None}
        if available:
            executor = ThreadPoolExecutor(max_workers=len(available), thread_name_prefix="context")
            try:
                jobs = {
                    executor.submit(provider.collect, generated_at): kind
                    for kind, provider in available.items()
                }
                done, pending = wait(jobs, timeout=self.config.timeout_ms / 1000.0)
                for future in done:
                    kind = jobs[future]
                    try:
                        item = future.result()
                        if item.age_s(generated_at) > self.config.max_age_s:
                            raise ValueError("stale context")
                        fields[kind] = item
                    except (OSError, RuntimeError, TypeError, ValueError) as error:
                        errors[kind] = str(error)[:200]
                for future in pending:
                    errors[jobs[future]] = "provider timeout"
                    future.cancel()
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        for kind, provider in providers.items():
            if provider is None:
                errors[kind] = "provider unavailable"
            if kind not in fields:
                cached = cache.get(kind)
                if cached is not None and cached.age_s(generated_at) <= self.config.max_age_s:
                    fields[kind] = cached
                    errors.pop(kind, None)
        with self._lock:
            self._cache.update(fields)
        return ContextSnapshot(generated_at=generated_at, fields=fields, errors=errors)
