"""Hardened packaged entry point for the CanMyPCRunAI detector.

The legacy detector module remains directly runnable for development and the
plain-text fallback scripts. The production executable starts here so hardware
measurements fail closed instead of falling back to plausible invented values.
"""

import os
import shutil
import sys

import detector


def get_memory_info_strict():
    """Return measured physical RAM or fail the scan; never invent a capacity."""
    if sys.platform != "win32":
        raise RuntimeError("The packaged detector currently supports Windows only.")

    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            raise OSError("GlobalMemoryStatusEx returned failure")

        total_bytes = int(stat.ullTotalPhys)
        available_bytes = int(stat.ullAvailPhys)
        if total_bytes <= 0 or available_bytes <= 0 or available_bytes > total_bytes:
            raise ValueError("Windows returned invalid physical-memory counters")

        return {
            "totalBytes": total_bytes,
            "availableBytes": available_bytes,
            "unified": False,
        }
    except Exception as error:
        raise RuntimeError(
            "Could not measure system RAM. The detector refuses to substitute a guessed value."
        ) from error


def get_storage_info_strict():
    """Return measured free storage or fail the scan; never invent free space."""
    try:
        # Use Windows' SystemDrive explicitly; os.sep alone can resolve relative
        # to whichever drive happens to be current when the executable starts.
        root = (os.environ.get("SystemDrive") or 'C:') + os.sep if sys.platform == "win32" else os.sep
        free_bytes = int(shutil.disk_usage(root).free)
        if free_bytes < 0:
            raise ValueError("Operating system returned a negative free-space value")
        return {"freeBytes": free_bytes}
    except Exception as error:
        raise RuntimeError(
            "Could not measure free disk space. The detector refuses to substitute a guessed value."
        ) from error


# scan_system/main resolve these names from the detector module at call time, so
# replacing them here hardens both GUI and console paths without duplicating the
# rest of the hardware detector.
detector.get_memory_info = get_memory_info_strict
detector.get_storage_info = get_storage_info_strict


if __name__ == "__main__":
    try:
        detector.launch()
    except Exception as error:  # last-resort UI/log handling remains centralized
        detector.report_crash(error)
        raise SystemExit(1)
