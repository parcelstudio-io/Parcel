"""No-dataset CUDA, EGL, and Habitat-Sim import smoke for Python 3.6.

This file is mounted read-only into the archived Habitat 2020 root filesystem.
It intentionally does not construct a simulator, load a scene, import an
evaluation episode, or execute an agent action.
"""

import ctypes
import json
import sys
import traceback

SENTINEL = "PARCEL_HABITAT_GPU_SMOKE="


def _cuda_probe():
    cuda = ctypes.CDLL("libcuda.so.1")
    cuda.cuInit.argtypes = [ctypes.c_uint]
    cuda.cuInit.restype = ctypes.c_int
    cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
    cuda.cuDeviceGetCount.restype = ctypes.c_int
    init_result = int(cuda.cuInit(0))
    count = ctypes.c_int(0)
    count_result = int(cuda.cuDeviceGetCount(ctypes.byref(count)))
    return {
        "library_loaded": True,
        "cu_init_result": init_result,
        "cu_device_get_count_result": count_result,
        "device_count": int(count.value),
        "passed": init_result == 0 and count_result == 0 and count.value > 0,
    }


def _egl_probe():
    egl = ctypes.CDLL("libEGL.so.1")
    egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
    egl.eglGetProcAddress.restype = ctypes.c_void_p
    query_pointer = egl.eglGetProcAddress(b"eglQueryDevicesEXT")
    display_pointer = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
    if not query_pointer or not display_pointer:
        return {
            "library_loaded": True,
            "extension_functions_resolved": False,
            "device_count": 0,
            "egl_initialize_result": False,
            "passed": False,
        }

    query_devices = ctypes.CFUNCTYPE(
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_int),
    )(query_pointer)
    get_platform_display = ctypes.CFUNCTYPE(
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    )(display_pointer)
    devices = (ctypes.c_void_p * 16)()
    count = ctypes.c_int(0)
    query_result = bool(query_devices(16, devices, ctypes.byref(count)))
    initialized = False
    major = ctypes.c_int(0)
    minor = ctypes.c_int(0)
    if query_result and count.value > 0:
        # EGL_PLATFORM_DEVICE_EXT from EGL_EXT_platform_device.
        display = get_platform_display(0x313F, devices[0], None)
        if display:
            egl.eglInitialize.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            egl.eglInitialize.restype = ctypes.c_uint
            initialized = bool(egl.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)))
            if initialized:
                egl.eglTerminate.argtypes = [ctypes.c_void_p]
                egl.eglTerminate.restype = ctypes.c_uint
                egl.eglTerminate(display)
    return {
        "library_loaded": True,
        "extension_functions_resolved": True,
        "query_devices_result": query_result,
        "device_count": int(count.value),
        "egl_initialize_result": initialized,
        "egl_version": f"{major.value}.{minor.value}",
        "passed": query_result and count.value > 0 and initialized,
    }


def _habitat_import_probe():
    import habitat_sim

    return {
        "imported": True,
        "module_file": getattr(habitat_sim, "__file__", None),
        "module_version": getattr(habitat_sim, "__version__", None),
        "simulator_constructed": False,
        "scene_loaded": False,
        "passed": True,
    }


def main():
    report = {
        "schema_version": 1,
        "python_version": sys.version,
        "cuda": None,
        "egl": None,
        "habitat_sim": None,
        "claims": {
            "dataset_used": False,
            "scene_loaded": False,
            "simulator_constructed": False,
            "gpu_render_executed": False,
            "navigation_episode_executed": False,
            "navigation_metrics_emitted": False,
        },
        "passed": False,
    }
    try:
        report["cuda"] = _cuda_probe()
        report["egl"] = _egl_probe()
        report["habitat_sim"] = _habitat_import_probe()
        report["passed"] = bool(
            report["cuda"]["passed"] and report["egl"]["passed"] and report["habitat_sim"]["passed"]
        )
    except Exception as error:  # noqa: BLE001 - emit a fail-closed in-image report
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
    print(SENTINEL + json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
