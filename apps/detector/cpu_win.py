"""
Windows CPU details without spawning a process.

The PowerShell/WMI query this replaces worked in a console build but returned
nothing once the executable was built windowed, leaving the useless fallback
name "AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD" and a physical core
count equal to the logical one.

Reading the registry and calling the Win32 API directly is also faster and
cannot flash a console window, so it is the better approach regardless.
"""

import ctypes
import sys

RELATION_PROCESSOR_CORE = 0


def cpu_name():
    """Marketing name, e.g. "AMD Ryzen 7 5700X 8-Core Processor"."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "ProcessorNameString")
        value = (value or "").strip()
        return value or None
    except Exception:
        return None


def physical_core_count():
    """
    Physical cores, which is not the same as the logical count when SMT is on.

    GetLogicalProcessorInformationEx returns a packed list of variable-length
    records; each RelationProcessorCore entry is one physical core.
    """
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.windll.kernel32

        size = ctypes.c_ulong(0)
        kernel32.GetLogicalProcessorInformationEx(
            RELATION_PROCESSOR_CORE, None, ctypes.byref(size)
        )
        if size.value == 0:
            return None

        buffer = ctypes.create_string_buffer(size.value)
        if not kernel32.GetLogicalProcessorInformationEx(
            RELATION_PROCESSOR_CORE, buffer, ctypes.byref(size)
        ):
            return None

        raw = buffer.raw
        cores = 0
        offset = 0
        while offset + 8 <= size.value:
            relationship = int.from_bytes(raw[offset : offset + 4], "little")
            record_size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
            if record_size == 0:
                break
            if relationship == RELATION_PROCESSOR_CORE:
                cores += 1
            offset += record_size

        return cores or None
    except Exception:
        return None


def logical_core_count():
    """Logical processors as the OS sees them."""
    if sys.platform != "win32":
        return None
    try:
        return int(ctypes.windll.kernel32.GetActiveProcessorCount(0xFFFF)) or None
    except Exception:
        return None
