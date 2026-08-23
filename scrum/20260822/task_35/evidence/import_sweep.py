"""HW-1 corroboration: import EVERY parcel_robot module and classify each failure.

Run it with the interpreter under test:

    ~/.cache/parcel-hw1/py310/bin/python scrum/20260822/task_35/evidence/import_sweep.py
    .parcel/bin/python                   scrum/20260822/task_35/evidence/import_sweep.py

A failure is only interesting if it is NOT a missing third-party package: those
are optional extras the interpreter under test cannot install (``websockets``
needs >=3.11) or repo-root packages no extra ships (``evals``). Everything else
would be a 3.10 defect, and the row this script backs is that there are none.

The except clause is a NAMED tuple rather than ``except Exception``: the point
of the sweep is to enumerate import-time failures, and an exception outside this
list is something the sweep does not understand and must not absorb.
"""

import importlib
import pkgutil
import sys

import parcel_robot

THIRD_PARTY_HINTS = (
    "cv2",
    "onnxruntime",
    "websockets",
    "sounddevice",
    "msgpack",
    "pyrealsense2",
    "serial",
    "unitree",
    "rclpy",
    "torch",
    "transformers",
    "PIL",
    "scipy",
    "sklearn",
    "requests",
    "aiohttp",
    "soundfile",
    "evals",
)

ok: list[str] = []
dep_missing: list[tuple[str, str]] = []
other: list[tuple[str, str]] = []

for module in pkgutil.walk_packages(parcel_robot.__path__, "parcel_robot."):
    name = module.name
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as error:
        missing = error.name or ""
        row = (name, f"ModuleNotFoundError: {missing}")
        if missing.split(".")[0] in THIRD_PARTY_HINTS or not missing.startswith("parcel_robot"):
            dep_missing.append(row)
        else:
            other.append(row)
    except (
        ArithmeticError,
        AttributeError,
        ImportError,
        LookupError,
        NameError,
        OSError,
        RuntimeError,
        SyntaxError,
        TypeError,
        ValueError,
    ) as error:
        other.append((name, f"{type(error).__name__}: {error}"))
    else:
        ok.append(name)

print(f"interpreter {sys.version.split()[0]}")
print(f"imported OK              : {len(ok)}")
print(f"missing optional 3rd-party: {len(dep_missing)}")
for name, reason in sorted(dep_missing):
    print(f"   {name}: {reason}")
print(f"OTHER failures (the ones that would be a 3.10 bug): {len(other)}")
for name, reason in sorted(other):
    print(f"   {name}: {reason}")
