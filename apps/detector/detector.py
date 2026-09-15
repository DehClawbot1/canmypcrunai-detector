"""
Real Hardware Detector for CanMyPCRunAI (Windows / Cross-platform)
Collects only technical system specifications necessary for AI model compatibility.
Sends normalized hardware profile back to the web application session.
"""

import sys
import os
import base64
import re
import json
import platform
import subprocess
import shutil
import urllib.request
import urllib.error
import webbrowser


# Pairing details the website bakes into the download filename, so the user can
# just double-click the file instead of typing a code.
#
# Compact form (current):
#   CanMyPCRunAI_<32 base64url chars>[_dev].exe
# Those 32 characters are the same 24 bytes the legacy form spelled out in hex:
# 8 bytes of scan id followed by 16 bytes of upload secret. Encoding them
# densely rather than as hex keeps every bit of entropy while cutting the
# filename from 80 characters to 49 — long download names look alarming, and
# some tools truncate them.
#
# Legacy form, still accepted so binaries downloaded before the change keep
# pairing:
#   canmypcrunai-detector_<scanId>~<uploadSecret>[~dev].exe
#
# The trailing " (1)" in both allows for browsers renaming a repeated download.
FILENAME_PAIRING_COMPACT_RE = re.compile(
    r"_([A-Za-z0-9_-]{32})(_dev)?(?:\s*\(\d+\))?$"
)
FILENAME_PAIRING_LEGACY_RE = re.compile(
    r"_(scan-[0-9a-f]{16})~([0-9a-f]{32})(~dev)?(?:\s*\(\d+\))?$",
    re.IGNORECASE,
)


def _decode_compact_pairing(token):
    """Turn 32 base64url characters back into (scan_id, upload_secret)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=")
    except Exception:
        return None, None
    if len(raw) != 24:
        return None, None
    return "scan-" + raw[:8].hex(), raw[8:].hex()


def console_available():
    """
    True when there is a console to read a typed answer from.

    A windowed build has no console, so sys.stdin is None and input() raises
    RuntimeError("lost sys.stdin") rather than the EOFError these prompts were
    written to catch. Redirected input still counts, which is how the console
    path stays testable.
    """
    try:
        return sys.stdin is not None and not sys.stdin.closed
    except Exception:
        return False


def pairing_from_filename():
    """Extract (scan_id, upload_secret, is_dev) from our own filename, if present."""
    try:
        # Frozen PyInstaller build reports the real .exe path in sys.executable;
        # a plain script run reports the interpreter, so fall back to argv[0].
        own_path = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
        stem = os.path.splitext(os.path.basename(own_path))[0]

        match = FILENAME_PAIRING_COMPACT_RE.search(stem)
        if match:
            scan_id, secret = _decode_compact_pairing(match.group(1))
            if scan_id and secret:
                return scan_id, secret, bool(match.group(2))

        match = FILENAME_PAIRING_LEGACY_RE.search(stem)
        if match:
            return match.group(1), match.group(2), bool(match.group(3))
    except Exception:
        pass
    return None, None, False

def run_hidden(args, timeout=6, stderr=None):
    """
    Run a helper command without flashing a console window.

    The executable is built windowed, so a child process would otherwise pop up
    its own console for a moment, and inherits no usable standard handles --
    which silently broke CPU name detection and left the fallback
    "AMD64 Family 25 ..." string in its place. CREATE_NO_WINDOW suppresses the
    window and explicit handles keep the child's output readable.
    """
    kwargs = {
        "text": True,
        "timeout": timeout,
        "stdin": subprocess.DEVNULL,
        "stderr": stderr if stderr is not None else subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
    return subprocess.check_output(args, **kwargs)


def detect_system_backends():
    """Detect substantiated runtime acceleration backends available on the host machine"""
    backends = set()

    # 1. CUDA
    if shutil.which("nvidia-smi"):
        backends.add("cuda")
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.LoadLibrary("nvcuda.dll")
            backends.add("cuda")
        except Exception:
            pass

    # 2. Vulkan
    if shutil.which("vulkaninfo"):
        backends.add("vulkan")
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.LoadLibrary("vulkan-1.dll")
            backends.add("vulkan")
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            import ctypes
            ctypes.CDLL("libvulkan.so.1")
            backends.add("vulkan")
        except Exception:
            pass

    # 3. ROCm / HIP
    if shutil.which("rocminfo"):
        backends.add("rocm")
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.LoadLibrary("amdhip64.dll")
            backends.add("rocm")
        except Exception:
            pass
        if os.environ.get("HIP_PATH") or os.environ.get("ROCM_PATH"):
            backends.add("rocm")
    elif sys.platform.startswith("linux"):
        if os.path.exists("/opt/rocm") or shutil.which("hipcc"):
            backends.add("rocm")

    # 4. Metal (macOS arm64)
    if sys.platform == "darwin" and platform.machine() in ["arm64", "aarch64"]:
        backends.add("metal")

    # CPU is always available as fallback
    backends.add("cpu")
    return backends

def get_os_info():
    uname = platform.uname()
    return {
        "name": uname.system,
        "version": platform.release() or uname.version,
        "arch": uname.machine
    }

def get_cpu_info():
    model = platform.processor() or "Unknown CPU"
    physical_cores = os.cpu_count() or 4
    logical_cores = os.cpu_count() or 4

    if sys.platform == "win32":
        # Registry and Win32 API first: the PowerShell/WMI query below returns
        # nothing in a windowed build, which silently left the unhelpful
        # "AMD64 Family 25 Model 33 ..." name and a wrong core count.
        try:
            import cpu_win

            name = cpu_win.cpu_name()
            if name:
                model = name
            physical = cpu_win.physical_core_count()
            if physical:
                physical_cores = physical
            logical = cpu_win.logical_core_count()
            if logical:
                logical_cores = logical
        except Exception:
            pass

        # Only ask PowerShell for whatever is still missing.
        if model == (platform.processor() or "Unknown CPU"):
            try:
                cmd = "Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors | ConvertTo-Json"
                out = run_hidden(["powershell", "-NoProfile", "-Command", cmd], timeout=5)
                data = json.loads(out)
                if data.get("Name"):
                    model = data["Name"].strip()
                if data.get("NumberOfCores"):
                    physical_cores = int(data["NumberOfCores"])
                if data.get("NumberOfLogicalProcessors"):
                    logical_cores = int(data["NumberOfLogicalProcessors"])
            except Exception:
                pass

    elif sys.platform == "darwin":
        # platform.processor() returns "arm" or "i386" here, which names nothing
        # a person would recognise.
        try:
            name = run_hidden(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5).strip()
            if name:
                model = name
        except Exception:
            pass
        for key, setter in (("hw.physicalcpu", "physical"), ("hw.logicalcpu", "logical")):
            try:
                value = int(run_hidden(["sysctl", "-n", key], timeout=5).strip())
                if value > 0:
                    if setter == "physical":
                        physical_cores = value
                    else:
                        logical_cores = value
            except Exception:
                pass

    elif sys.platform.startswith("linux"):
        try:
            cores = set()
            with open("/proc/cpuinfo", encoding="utf-8") as handle:
                physical_id = core_id = None
                for line in handle:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if key == "model name" and model in ("", "Unknown CPU", platform.processor()):
                        model = value
                    elif key == "physical id":
                        physical_id = value
                    elif key == "core id":
                        core_id = value
                        cores.add((physical_id, core_id))
            if cores:
                physical_cores = len(cores)
        except Exception:
            pass

    vendor = "Unknown"
    model_lower = model.lower()
    if "amd" in model_lower or "ryzen" in model_lower:
        vendor = "AMD"
    elif "intel" in model_lower or "core" in model_lower:
        vendor = "Intel"
    elif "apple" in model_lower:
        vendor = "Apple"

    return {
        "vendor": vendor,
        "model": model,
        "physicalCores": physical_cores,
        "logicalCores": logical_cores
    }

class UnsupportedPlatform(Exception):
    """Raised when this machine's real specifications cannot be read."""


def _unix_memory():
    """
    (total, available) in bytes on Linux and macOS, or (None, None).

    Kept separate from the Windows path because the profile schema demands
    positive numbers for both: there is no way to say "unknown" in an upload, so
    the only honest options are a measured value or no upload at all.
    """
    total = available = None

    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        pass

    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    key, _, rest = line.partition(":")
                    if key == "MemTotal":
                        total = int(rest.split()[0]) * 1024
                    elif key == "MemAvailable":
                        available = int(rest.split()[0]) * 1024
        except Exception:
            pass
    elif sys.platform == "darwin":
        # vm_stat reports pages; free plus inactive plus speculative is what the
        # kernel would hand to a new allocation.
        try:
            out = run_hidden(["vm_stat"], timeout=5)
            page_size = 4096
            first = out.splitlines()[0] if out else ""
            match = re.search(r"page size of (\d+) bytes", first)
            if match:
                page_size = int(match.group(1))
            pages = 0
            for name in ("Pages free", "Pages inactive", "Pages speculative"):
                m = re.search(rf"{name}:\s+(\d+)", out)
                if m:
                    pages += int(m.group(1))
            if pages:
                available = pages * page_size
        except Exception:
            pass

    return total, available


def get_memory_info():
    total_bytes = None
    available_bytes = None

    if sys.platform != "win32":
        total_bytes, available_bytes = _unix_memory()
        if not total_bytes:
            raise UnsupportedPlatform(
                "Could not read the amount of memory installed on this machine."
            )
        if available_bytes is None:
            raise UnsupportedPlatform("Could not measure currently available system memory.")
        return {
            "totalBytes": total_bytes,
            "availableBytes": available_bytes,
            # Apple Silicon shares one pool between CPU and GPU, which changes
            # what the compatibility engine may assume about VRAM.
            "unified": sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64"),
        }

    if sys.platform == "win32":
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
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_bytes = int(stat.ullTotalPhys)
                available_bytes = int(stat.ullAvailPhys)
        except Exception:
            pass

    # Refuse rather than report the 16 GB this used to assume when the call
    # failed. entrypoint.py already replaces this function in the packaged
    # build; this keeps the same promise for anyone running the script.
    if not total_bytes or not available_bytes:
        raise UnsupportedPlatform("Could not measure how much memory this machine has.")

    return {
        "totalBytes": total_bytes,
        "availableBytes": available_bytes,
        "unified": False
    }

def get_storage_info():
    # The same promise as get_memory_info: a measurement or nothing. This used
    # to claim 100 GB free whenever the call failed, which is a number that
    # decides whether a 40 GB model looks downloadable.
    try:
        root = (os.environ.get("SystemDrive") or "C:") + os.sep if sys.platform == "win32" else os.sep
        free_bytes = int(shutil.disk_usage(root).free)
    except Exception as error:
        raise UnsupportedPlatform("Could not measure free disk space.") from error

    if free_bytes < 0:
        raise UnsupportedPlatform("The operating system reported negative free disk space.")

    return {
        "freeBytes": free_bytes
    }

def get_windows_gpu_registry():
    gpus_map = {}
    if sys.platform != "win32":
        return gpus_map
    try:
        import winreg
        key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base:
            for i in range(25):
                try:
                    with winreg.OpenKey(base, f"{i:04d}") as sub:
                        desc, _ = winreg.QueryValueEx(sub, "DriverDesc")
                        vram = 0
                        try:
                            vram, _ = winreg.QueryValueEx(sub, "HardwareInformation.qwMemorySize")
                        except FileNotFoundError:
                            try:
                                vram, _ = winreg.QueryValueEx(sub, "HardwareInformation.MemorySize")
                            except FileNotFoundError:
                                pass
                        if vram and vram > 0:
                            gpus_map[desc.strip().lower()] = int(vram)
                except OSError:
                    pass
    except Exception:
        pass
    return gpus_map

def get_dxgi_gpus():
    """Query physical GPUs using Windows native DXGI API (Priority 1)"""
    if sys.platform != "win32":
        return []
    system_backends = detect_system_backends()
    dxgi_gpus = []
    try:
        import ctypes
        from ctypes import wintypes, Structure, c_wchar, c_size_t, c_uint, POINTER, byref, c_void_p, WINFUNCTYPE, c_int32

        class GUID(Structure):
            _fields_ = [
                ('Data1', wintypes.DWORD),
                ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD),
                ('Data4', wintypes.BYTE * 8)
            ]

        class LUID(Structure):
            _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

        class DXGI_ADAPTER_DESC1(Structure):
            _fields_ = [
                ('Description', c_wchar * 128),
                ('VendorId', wintypes.UINT),
                ('DeviceId', wintypes.UINT),
                ('SubSysId', wintypes.UINT),
                ('Revision', wintypes.UINT),
                ('DedicatedVideoMemory', c_size_t),
                ('DedicatedSystemMemory', c_size_t),
                ('SharedSystemMemory', c_size_t),
                ('AdapterLuid', LUID),
                ('Flags', wintypes.UINT),
            ]

        IID_IDXGIFactory4 = GUID(0x1bc6ea02, 0xef36, 0x464f, (wintypes.BYTE * 8)(0xbf, 0x0c, 0x21, 0xca, 0x39, 0xe5, 0x16, 0x8a))
        IID_IDXGIFactory1 = GUID(0x770aae78, 0xf26f, 0x4d1f, (wintypes.BYTE * 8)(0x88, 0x97, 0x32, 0xfa, 0x50, 0xac, 0x56, 0x5f))

        dxgi = ctypes.windll.dxgi
        pFactory = c_void_p()
        hr = dxgi.CreateDXGIFactory1(byref(IID_IDXGIFactory4), byref(pFactory))
        if hr != 0:
            hr = dxgi.CreateDXGIFactory1(byref(IID_IDXGIFactory1), byref(pFactory))
        if hr != 0 or not pFactory.value:
            return []

        factory_vtable = ctypes.cast(pFactory, POINTER(POINTER(c_void_p))).contents
        EnumAdapters1 = WINFUNCTYPE(c_int32, c_void_p, c_uint, POINTER(c_void_p))(factory_vtable[12])

        idx = 0
        while True:
            pAdapter1 = c_void_p()
            if EnumAdapters1(pFactory, idx, byref(pAdapter1)) != 0 or not pAdapter1.value:
                break

            adapter1_vtable = ctypes.cast(pAdapter1, POINTER(POINTER(c_void_p))).contents
            GetDesc1 = WINFUNCTYPE(c_int32, c_void_p, POINTER(DXGI_ADAPTER_DESC1))(adapter1_vtable[10])
            desc1 = DXGI_ADAPTER_DESC1()
            GetDesc1(pAdapter1, byref(desc1))

            name = desc1.Description.strip()
            name_lower = name.lower()

            # Ignore software adapters (DXGI_ADAPTER_FLAG_SOFTWARE = 2) or Microsoft Basic Render Driver
            if (desc1.Flags & 2 == 0) and not any(x in name_lower for x in ["remote", "virtual", "rdp", "vnc", "basic render"]):
                vendor = "Unknown"
                hw_caps = ["vulkan", "cpu"]
                if desc1.VendorId == 0x10DE or any(x in name_lower for x in ["nvidia", "geforce", "rtx", "gtx", "quadro"]):
                    vendor = "NVIDIA"
                    hw_caps = ["cuda", "vulkan", "cpu"]
                elif desc1.VendorId == 0x1002 or any(x in name_lower for x in ["amd", "radeon", "rx"]):
                    vendor = "AMD"
                    hw_caps = ["rocm", "vulkan", "cpu"]
                elif desc1.VendorId == 0x8086 or any(x in name_lower for x in ["intel", "arc", "iris", "uhd", "hd graphics"]):
                    vendor = "Intel"
                    hw_caps = ["vulkan", "cpu"]

                det_backends = [b for b in hw_caps if b in system_backends]
                effective_backends = [b for b in det_backends if b != "cpu"] or ["cpu"]

                vram_bytes = int(desc1.DedicatedVideoMemory)
                dxgi_gpus.append({
                    "vendor": vendor,
                    "model": name,
                    "dedicatedVramTotalBytes": vram_bytes,
                    "vramTotalBytes": vram_bytes,
                    "localMemoryBudgetBytes": None,
                    "localMemoryCurrentUsageBytes": None,
                    "localMemoryAvailableBytes": None,
                    "vramAvailableBytes": None,
                    "backends": effective_backends,
                    "hardwareCapabilities": hw_caps,
                    "detectedBackends": det_backends,
                    "detection": {
                        "totalVramSource": "DXGI",
                        "availabilitySource": None,
                        "confidence": "HIGH" if vram_bytes > 0 else "LOW"
                    }
                })

            WINFUNCTYPE(ctypes.c_ulong, c_void_p)(adapter1_vtable[2])(pAdapter1)
            idx += 1

        WINFUNCTYPE(ctypes.c_ulong, c_void_p)(factory_vtable[2])(pFactory)
    except Exception:
        pass
    return dxgi_gpus

def get_nvidia_smi_gpus():
    """Query NVIDIA GPUs via nvidia-smi for total and free memory"""
    system_backends = detect_system_backends()
    nv_gpus = []
    try:
        cmd = ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"]
        out = run_hidden(cmd, timeout=4)
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                name = parts[0]
                total_mb = float(parts[1]) if parts[1].replace('.', '', 1).isdigit() else 0
                free_mb = float(parts[2]) if len(parts) > 2 and parts[2].replace('.', '', 1).isdigit() else None
                total_bytes = int(total_mb * 1024 * 1024)
                free_bytes = int(free_mb * 1024 * 1024) if free_mb is not None else None
                hw_caps = ["cuda", "vulkan", "cpu"]
                det_backends = [b for b in hw_caps if b in system_backends]
                effective_backends = [b for b in det_backends if b != "cpu"] or ["cpu"]
                nv_gpus.append({
                    "vendor": "NVIDIA",
                    "model": name,
                    "driverVersion": parts[3] if len(parts) > 3 and re.fullmatch(r"\d+(?:\.\d+)+", parts[3]) else None,
                    "dedicatedVramTotalBytes": total_bytes,
                    "vramTotalBytes": total_bytes,
                    "localMemoryBudgetBytes": total_bytes,
                    "localMemoryCurrentUsageBytes": (total_bytes - free_bytes) if free_bytes is not None else None,
                    "localMemoryAvailableBytes": free_bytes,
                    "vramAvailableBytes": free_bytes,
                    "backends": effective_backends,
                    "hardwareCapabilities": hw_caps,
                    "detectedBackends": det_backends,
                    "detection": {
                        "totalVramSource": "nvidia-smi",
                        "availabilitySource": "nvidia-smi" if free_bytes is not None else None,
                        "confidence": "HIGH"
                    }
                })
    except Exception:
        pass
    return nv_gpus

def get_gpus_info():
    system_backends = detect_system_backends()
    # 1. DXGI native Windows query (Priority 1)
    gpus = get_dxgi_gpus()

    # If DXGI found dedicated GPUs, check if any is NVIDIA to enrich with nvidia-smi dynamic free memory
    if gpus:
        has_nvidia = any(g["vendor"] == "NVIDIA" for g in gpus)
        if has_nvidia:
            nv_gpus = get_nvidia_smi_gpus()
            for g in gpus:
                if g["vendor"] == "NVIDIA":
                    # Only merge an unambiguous matching model. Two identical cards
                    # may have different free memory; enumeration order is not an ID.
                    matches = [nv for nv in nv_gpus if nv["model"].strip().lower() == g["model"].strip().lower()]
                    dxgi_matches = [other for other in gpus if other["model"] == g["model"]]
                    for nv in matches if len(matches) == 1 and len(dxgi_matches) == 1 else []:
                        g["driverVersion"] = nv.get("driverVersion")
                        if nv["localMemoryAvailableBytes"] is not None:
                            g["localMemoryAvailableBytes"] = nv["localMemoryAvailableBytes"]
                            g["vramAvailableBytes"] = nv["vramAvailableBytes"]
                            g["detection"]["availabilitySource"] = "nvidia-smi"
                            break
        return gpus

    # 2. NVIDIA via nvidia-smi if DXGI wasn't available
    nv_gpus = get_nvidia_smi_gpus()
    if nv_gpus:
        return nv_gpus

    # 3. 64-bit Registry + Win32_VideoController fallback
    if sys.platform == "win32":
        reg_vram_map = get_windows_gpu_registry()
        try:
            cmd = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json"
            out = run_hidden(["powershell", "-NoProfile", "-Command", cmd], timeout=6)
            controllers = json.loads(out)
            if isinstance(controllers, dict):
                controllers = [controllers]
            for c in controllers:
                name = c.get("Name", "Unknown GPU")
                if any(x in name.lower() for x in ["remote", "virtual", "rdp", "vnc", "basic render"]):
                    continue

                name_clean = name.strip()
                name_lower = name_clean.lower()

                # Check 64-bit registry VRAM first
                ram_bytes = 0
                source = "UNKNOWN"
                confidence = "LOW"
                for k, v in reg_vram_map.items():
                    if k in name_lower or name_lower in k:
                        ram_bytes = v
                        source = "REGISTRY_64"
                        confidence = "HIGH"
                        break

                if ram_bytes <= 0:
                    raw_ram = c.get("AdapterRAM") or 0
                    if raw_ram > 0:
                        ram_bytes = raw_ram
                        source = "WMI_ADAPTER_RAM"
                        confidence = "MEDIUM" if raw_ram <= 4 * 1024 * 1024 * 1024 else "LOW"

                vendor = "Unknown"
                hw_caps = ["vulkan", "cpu"]
                if any(x in name_lower for x in ["nvidia", "geforce", "rtx", "gtx", "quadro"]):
                    vendor = "NVIDIA"
                    hw_caps = ["cuda", "vulkan", "cpu"]
                elif any(x in name_lower for x in ["amd", "radeon", "rx"]):
                    vendor = "AMD"
                    hw_caps = ["rocm", "vulkan", "cpu"]
                elif any(x in name_lower for x in ["intel", "arc", "iris", "uhd", "hd graphics"]):
                    vendor = "Intel"
                    hw_caps = ["vulkan", "cpu"]

                det_backends = [b for b in hw_caps if b in system_backends]
                effective_backends = [b for b in det_backends if b != "cpu"] or ["cpu"]

                gpus.append({
                    "vendor": vendor,
                    "model": name_clean,
                    "dedicatedVramTotalBytes": int(ram_bytes),
                    "vramTotalBytes": int(ram_bytes),
                    "localMemoryBudgetBytes": None,
                    "localMemoryCurrentUsageBytes": None,
                    "localMemoryAvailableBytes": None,
                    "vramAvailableBytes": None,
                    "backends": effective_backends,
                    "hardwareCapabilities": hw_caps,
                    "detectedBackends": det_backends,
                    "detection": {
                        "totalVramSource": source,
                        "availabilitySource": None,
                        "confidence": confidence
                    }
                })
        except Exception:
            pass

    return gpus

def get_runtimes_info():
    runtimes = {}
    # Check Ollama
    ollama_path = shutil.which("ollama")
    if not ollama_path and sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidate = os.path.join(local_app, "Programs", "Ollama", "ollama.exe")
        if os.path.exists(candidate):
            ollama_path = candidate

    if ollama_path:
        runtimes["ollama"] = {
            "installed": True,
            "version": get_ollama_version(ollama_path),
            "models": list_ollama_models(ollama_path),
        }
    else:
        runtimes["ollama"] = {
            "installed": False
        }

    return runtimes


def get_ollama_version(ollama_path):
    """
    Version number only.

    `ollama --version` also prints warnings when no server is running, e.g.
    "Warning: could not connect to a running Ollama instance". Returning the
    raw output put that warning text into the version field, so extract just
    the version number.
    """
    try:
        out = run_hidden([ollama_path, "--version"], timeout=5, stderr=subprocess.STDOUT)
    except Exception:
        return None

    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", out)
    return match.group(1) if match else None


def list_ollama_models(ollama_path):
    """
    Tags of the models already pulled locally, so the site can say which models
    the user does not need to download again.

    Only model tags are read — never prompts, chat history or any other file.
    Requires a running Ollama server; returns None when it cannot be reached,
    which is different from "the user has no models" (an empty list).
    """
    try:
        out = run_hidden([ollama_path, "list"], timeout=8)
    except Exception:
        return None

    tags = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("NAME"):
            continue
        tag = line.split()[0]
        # A tag always looks like "model:variant"; anything else is not a row.
        if ":" in tag:
            tags.append(tag)

    return tags

SCHEMA_VERSION = "1.0.0"
DETECTOR_VERSION = "1.3.2"

DEFAULT_PROD_URL = "https://canmypcrunai.online"
DEFAULT_DEV_URL = "http://localhost:3000"

def scan_system():
    return {
        "schemaVersion": SCHEMA_VERSION,
        "detectorVersion": DETECTOR_VERSION,
        "os": get_os_info(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "gpus": get_gpus_info(),
        "storage": get_storage_info(),
        "runtimes": get_runtimes_info()
    }

def is_local_dev_reachable():
    try:
        req = urllib.request.Request("http://localhost:3000/api/scan", method="HEAD")
        with urllib.request.urlopen(req, timeout=0.8):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False

def main():
    print("==================================================")
    print("   CanMyPCRunAI Hardware Compatibility Detector        ")
    print(f"   Detector v{DETECTOR_VERSION} (Schema v{SCHEMA_VERSION})")
    print("==================================================")
    print("Scanning your PC specifications for AI compatibility...")
    print("(Only hardware specs are scanned. No personal data collected.)\n")

    try:
        profile = scan_system()
    except UnsupportedPlatform as error:
        # Better to stop than to upload a profile with invented numbers in it.
        print("")
        print(f"[UNSUPPORTED] {error}")
        print("  The detector is built for Windows. On macOS and Linux, enter your")
        print("  specifications by hand instead: https://canmypcrunai.online/my-pc")
        return

    print(f"OS:     {profile['os']['name']} {profile['os']['version']} ({profile['os']['arch']})")
    print(f"CPU:    {profile['cpu']['model']} ({profile['cpu']['physicalCores']} cores, {profile['cpu']['logicalCores']} threads)")
    print(f"RAM:    {profile['memory']['totalBytes'] / (1024**3):.1f} GB installed ({profile['memory']['availableBytes'] / (1024**3):.1f} GB available)")
    if profile['gpus']:
        for i, g in enumerate(profile['gpus']):
            vram_gb = (g.get('dedicatedVramTotalBytes') or g['vramTotalBytes']) / (1024**3)
            det = g.get('detection', {})
            source_str = f" [Source: {det.get('totalVramSource')}, Confidence: {det.get('confidence')}]" if det else ""
            avail_str = f" - Available: {g['vramAvailableBytes'] / (1024**3):.1f} GB" if g.get('vramAvailableBytes') is not None else ""
            backends_str = ', '.join(g['backends'])
            print(f"GPU {i+1}:  {g['vendor']} {g['model']} ({vram_gb:.1f} GB Dedicated VRAM{avail_str}){source_str} - Acceleration: {backends_str}")
    else:
        print("GPU:    None detected (CPU-only inference)")
    print(f"Disk:   {profile['storage']['freeBytes'] / (1024**3):.1f} GB free")
    ollama_info = profile['runtimes']['ollama']
    if ollama_info['installed']:
        version = ollama_info.get('version') or 'version unknown'
        models = ollama_info.get('models')
        if models is None:
            model_str = ' - server not running, installed models unknown'
        elif models:
            model_str = f" - {len(models)} model(s) already installed"
        else:
            model_str = ' - no models installed yet'
        print(f"Ollama: v{version}{model_str}")
    print("--------------------------------------------------")

    # Command line and pairing configuration
    scan_id = None
    upload_secret = None
    server_url = os.environ.get("CANMYPCRUNAI_SERVER_URL") or os.environ.get("CANMYPCRUNAI_URL")

    # Zero-typing pairing: the website names the download after the session.
    scan_id, upload_secret, filename_is_dev = pairing_from_filename()
    if scan_id:
        print("\n[PAIRED] Pairing code read from the downloaded filename - no code entry needed.")
        if filename_is_dev and not server_url:
            server_url = DEFAULT_DEV_URL

    # Parse CLI flags and positional arguments
    raw_args = [a.strip() for a in sys.argv[1:] if a.strip()]
    cleaned_args = []
    for a in raw_args:
        if a in ["--dev", "--local"]:
            server_url = DEFAULT_DEV_URL
        elif a.startswith("--server="):
            server_url = a.split("=", 1)[1].rstrip("/")
        elif a.startswith("--"):
            # Flags handled elsewhere, such as --no-gui. Falling through to the
            # positional arguments below made "--no-gui" the scan id, and the
            # upload went to /api/scan/--no-gui.
            continue
        else:
            cleaned_args.append(a)

    if cleaned_args:
        first = cleaned_args[0]
        if ":" in first:
            scan_id, upload_secret = first.split(":", 1)
            if len(cleaned_args) > 1 and not server_url:
                server_url = cleaned_args[1].rstrip("/")
        else:
            scan_id = first
            if len(cleaned_args) > 1:
                second = cleaned_args[1]
                if second.startswith("http://") or second.startswith("https://"):
                    server_url = second.rstrip("/")
                else:
                    upload_secret = second
                    if len(cleaned_args) > 2 and not server_url:
                        server_url = cleaned_args[2].rstrip("/")

    # If no server URL was specified or flagged, check reachability
    is_auto_server = False
    if not server_url:
        is_auto_server = True
        try:
            import socket
            from urllib.parse import urlparse
            # Derive the host from DEFAULT_PROD_URL rather than repeating it,
            # so the reachability probe cannot drift from the upload target.
            socket.getaddrinfo(urlparse(DEFAULT_PROD_URL).hostname, 443)
            server_url = DEFAULT_PROD_URL
        except Exception:
            if is_local_dev_reachable():
                server_url = DEFAULT_DEV_URL
                print(f"[INFO] Production host unresolvable. Auto-selected local server: {server_url}")
            else:
                server_url = DEFAULT_PROD_URL

    # Interactive prompt if pairing code not provided
    if not scan_id:
        if not console_available():
            # Nothing can be typed, so write a local profile instead of raising
            # at a prompt nobody can see.
            code_input = ""
        else:
            print("\nTo link your scan with the website, enter your Pairing Code.")
            print("(Format: scan-xxxx:secret shown on the Detect PC webpage)")
            try:
                code_input = input("Pairing Code (or press Enter to save local JSON profile): ").strip()
            except Exception:
                code_input = ""

        if ":" in code_input:
            scan_id, upload_secret = code_input.split(":", 1)
        elif code_input:
            scan_id = code_input
            try:
                upload_secret = input("Upload Secret: ").strip()
            except Exception:
                upload_secret = ""

    if scan_id:
        target_url = f"{server_url}/api/scan/{scan_id}"
        print(f"\nSending hardware specifications to {target_url}...")
        try:
            payload_data = {
                "schemaVersion": SCHEMA_VERSION,
                "detectorVersion": DETECTOR_VERSION,
                "uploadSecret": upload_secret or "",
                "hardware": profile
            }
            req_data = json.dumps(payload_data).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": f"CanMyPCRunAI-Detector/{DETECTOR_VERSION}"
            }
            if upload_secret:
                headers["x-upload-secret"] = upload_secret
                headers["Authorization"] = f"Bearer {upload_secret}"

            req = urllib.request.Request(
                target_url,
                data=req_data,
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                if res_json.get("success"):
                    print("\n[SUCCESS] Hardware specifications verified and linked with your session!")
                    print("Your browser should automatically display your PC compatibility report.")
                    result_url = f"{server_url}/results/{scan_id}"
                    print(f"Direct link: {result_url}")
                    try:
                        webbrowser.open(result_url)
                    except Exception:
                        pass
                else:
                    print(f"\n[ERROR] Server response: {res_body}")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                pass
            print(f"\n[HTTP {e.code} ERROR] Server pairing rejected:")
            if e.code == 401:
                print("  -> Unauthorized: Invalid or missing pairing upload secret.")
                print("     Make sure you entered the complete pairing code (scan-xxxx:secret).")
            elif e.code == 404:
                print("  -> Not Found: Scan session does not exist.")
                print("     Please visit the website and start a scan session first.")
            elif e.code == 409:
                print("  -> Conflict: This scan session has already been completed.")
                print("     Completed sessions cannot be overwritten. Start a new scan on the website.")
            elif e.code == 410:
                print("  -> Expired: This scan session has expired (valid for 15 minutes).")
                print("     Please refresh the website to generate a new scan session.")
            elif e.code == 413:
                print("  -> Payload Too Large: Scan payload exceeds the 64 KB limit.")
            elif e.code == 429:
                print("  -> Rate Limited: Too many scan requests. Please wait a moment.")
            else:
                print(f"  -> {e.reason}: {err_body}")
        except urllib.error.URLError as e:
            if (server_url == DEFAULT_PROD_URL or is_auto_server) and is_local_dev_reachable():
                print(f"\n[INFO] Could not reach {server_url} ({e.reason}).")
                print(f"[INFO] Detected local CanMyPCRunAI server at {DEFAULT_DEV_URL}! Falling back automatically...")
                server_url = DEFAULT_DEV_URL
                target_url = f"{server_url}/api/scan/{scan_id}"
                print(f"Retrying hardware upload to {target_url}...")
                try:
                    req_retry = urllib.request.Request(target_url, data=req_data, headers=headers)
                    with urllib.request.urlopen(req_retry, timeout=12) as response:
                        res_body = response.read().decode("utf-8")
                        res_json = json.loads(res_body)
                        if res_json.get("success"):
                            print("\n[SUCCESS] Hardware specifications verified and linked with your session!")
                            print("Your browser should automatically display your PC compatibility report.")
                            result_url = f"{server_url}/results/{scan_id}"
                            print(f"Direct link: {result_url}")
                            try:
                                webbrowser.open(result_url)
                            except Exception:
                                pass
                            if console_available() and sys.stdin.isatty():
                                print("\nPress Enter to exit...")
                                try: input()
                                except Exception: pass
                            return
                        else:
                            print(f"\n[ERROR] Server response: {res_body}")
                            if console_available() and sys.stdin.isatty():
                                print("\nPress Enter to exit...")
                                try: input()
                                except Exception: pass
                            return
                except Exception as fallback_err:
                    print(f"Fallback attempt failed: {fallback_err}")

            print(f"\n[CONNECTION ERROR] Could not reach {server_url}: {e.reason}")
            print("Tip: If testing against a local development server, pass --dev or http://localhost:3000")
            print("     Example: canmypcrunai-detector.exe <pairing_code> --dev")
        except Exception as e:
            print(f"\n[ERROR] Unexpected upload error: {e}")
    else:
        out_file = "hardware_profile.json"
        with open(out_file, "w") as f:
            json.dump(profile, f, indent=2)
        print(f"\nHardware profile saved to {out_file}")

    if console_available() and sys.stdin.isatty():
        print("\nPress Enter to exit...")
        try:
            input()
        except Exception:
            pass

def launch():
    """
    Entry point. Prefers the window; falls back to the console.

    The window is the default because most people reach this by double-clicking
    a download, and a terminal is an alarming thing to greet them with. Anything
    the window cannot handle -- no pairing code in the filename, an explicit
    --no-gui, or a system without tkinter -- goes to the console path instead.
    """
    args = [a.strip() for a in sys.argv[1:] if a.strip()]

    # --no-gui only makes sense where there is a console to print to. Honouring
    # it in a windowed build sent the user to a path that prints into nothing
    # and then crashed at a prompt it could not read: "lost sys.stdin".
    if ("--no-gui" in args or "--console" in args) and console_available():
        return main()

    # A pairing code typed on the command line belongs to the console path,
    # which is where the prompts and the error reporting for it live.
    if console_available() and any(":" in a and not a.startswith("--") for a in args):
        return main()

    scan_id, upload_secret, filename_is_dev = pairing_from_filename()

    # A missing pairing code is no longer a reason to fall back to the console:
    # the window starts its own scan instead, so a copy that was renamed, shared
    # or simply kept works the same as a fresh download.
    server_url = (
        os.environ.get("CANMYPCRUNAI_SERVER_URL")
        or os.environ.get("CANMYPCRUNAI_URL")
        or (DEFAULT_DEV_URL if filename_is_dev else DEFAULT_PROD_URL)
    )

    try:
        import gui
    except Exception:
        return main()

    result = gui.run(
        scan_system, scan_id, upload_secret, server_url,
        SCHEMA_VERSION, DETECTOR_VERSION,
    )
    if result is None:
        # tkinter unavailable on this system.
        return main()
    return result


def report_crash(error):
    """
    Show a failure in a window rather than PyInstaller's raw traceback dialog.

    Someone who has just clicked past a SmartScreen warning should not then be
    shown a Python stack trace. The detail still goes to a log file beside the
    executable so a problem can be diagnosed.
    """
    import traceback

    detail = traceback.format_exc()
    try:
        log = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "canmypcrunai-error.log")
        with open(log, "w", encoding="utf-8") as handle:
            handle.write(detail)
    except Exception:
        log = None

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "CanMyPCRunAI Detector",
            "The detector could not finish.\n\n"
            f"{type(error).__name__}: {error}\n\n"
            + (f"Details were written to:\n{log}" if log else "")
            + "\n\nPlease start a new scan at canmypcrunai.online.",
        )
        root.destroy()
    except Exception:
        # No display either; the log file is all that is left.
        pass


if __name__ == "__main__":
    try:
        launch()
    except Exception as error:  # noqa: BLE001 - last resort before the OS shows a traceback
        report_crash(error)
        sys.exit(1)
