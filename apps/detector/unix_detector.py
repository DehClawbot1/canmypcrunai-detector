"""Read-only macOS/Linux detector. No dependencies beyond Python 3.9+.

Linux GPU memory: docs.kernel.org/gpu/amdgpu/driver-misc.html
macOS: sysctl reports physical memory; Apple Silicon has no dedicated VRAM.
Unknown measurements remain None. Device IDs are used locally, never uploaded.
"""
import argparse
import csv
import ctypes
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

import detector

VERSION = '1.4.0'


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ''


def integer(value):
    try:
        result = int(value)
        return result if result >= 0 else None
    except (ValueError, TypeError):
        return None


def command(args):
    return detector.run_hidden(args, timeout=15).strip()


def cpu_info():
    if sys.platform == 'darwin':
        model = command(['sysctl', '-n', 'machdep.cpu.brand_string'])
        physical = integer(command(['sysctl', '-n', 'hw.physicalcpu']))
        logical = integer(command(['sysctl', '-n', 'hw.logicalcpu']))
    else:
        raw = read('/proc/cpuinfo')
        model = next((line.split(':', 1)[1].strip() for line in raw.splitlines()
                      if line.startswith('model name')), '')
        if not model:
            model = read('/sys/firmware/devicetree/base/model').replace('\x00', '') or 'Unknown CPU'
        logical = os.cpu_count()
        topology = set()
        for core in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/topology'):
            package_id, core_id = read(core / 'physical_package_id'), read(core / 'core_id')
            if package_id and core_id:
                topology.add((package_id, core_id))
        physical = len(topology)
    if not physical or not logical:
        raise RuntimeError('CPU core counts could not be measured. Use manual entry.')
    vendor = 'Apple' if 'Apple' in model else 'AMD' if any(s in model for s in ('AMD', 'Ryzen')) else 'Intel' if 'Intel' in model else 'Unknown'
    return {'model': model, 'vendor': vendor, 'physicalCores': physical, 'logicalCores': logical}


def memory_info():
    if sys.platform == 'darwin':
        total = integer(command(['sysctl', '-n', 'hw.memsize']))
        # vm_stat's free/inactive pages are not a reliable available-memory budget.
        available = None
    else:
        values = {}
        for line in read('/proc/meminfo').splitlines():
            key, _, value = line.partition(':')
            parts = value.split()
            if parts and parts[-1] == 'kB':
                count = integer(parts[0])
                if count is not None:
                    values[key] = count * 1024
        total, available = values.get('MemTotal'), values.get('MemAvailable')
    if not total:
        raise RuntimeError('System memory could not be measured. Use manual entry.')
    if available is not None and available > total:
        available = None
    return {'totalBytes': total, 'availableBytes': available,
            'unified': sys.platform == 'darwin' and platform.machine().lower() in ('arm64', 'aarch64')}


def gpu_record(vendor, model, total, backends, source, free=None, driver=None):
    return {'vendor': vendor, 'model': model, 'dedicatedVramTotalBytes': total,
            'vramTotalBytes': total, 'vramAvailableBytes': free, 'localMemoryAvailableBytes': free,
            'backends': backends or ['cpu'], 'detectedBackends': backends or ['cpu'],
            'driverVersion': driver,
            'detection': {'totalVramSource': source, 'availabilitySource': 'nvidia-smi' if free is not None else None,
                          'confidence': 'HIGH' if total is not None else 'LOW'}}


def pci_key(bus):
    return bus.lower().lstrip('0')


def nvidia_by_bus():
    cards = {}
    try:
        raw = command(['nvidia-smi', '--query-gpu=pci.bus_id,name,memory.total,memory.free,driver_version', '--format=csv,noheader,nounits'])
        for row in csv.reader(io.StringIO(raw)):
            if len(row) != 5:
                continue
            bus, name, total, free, driver = (s.strip() for s in row)
            total, free = integer(total), integer(free)
            if total is None:
                free = None
            elif free is not None and free > total:
                free = None
            cards[pci_key(bus)] = gpu_record('NVIDIA', name, total * 1024 ** 2 if total is not None else None,
                                           ['cuda'], 'nvidia-smi', free * 1024 ** 2 if free is not None else None, driver)
    except Exception:
        # A missing utility or inaccessible GPU is not evidence of VRAM capacity.
        pass
    return cards


def linux_gpus(root=Path('/sys/class/drm')):
    nvidia = nvidia_by_bus()
    cards, seen = [], set()
    installed = detector.detect_system_backends()
    for card in sorted(root.glob('card[0-9]*')):
        if not re.fullmatch(r'card\d+', card.name):
            continue
        device = (card / 'device').resolve()
        if device in seen or not device.exists():
            continue
        seen.add(device)
        key = pci_key(device.name)
        if key in nvidia:
            cards.append(nvidia.pop(key))
            continue
        vendor = {'0x1002': 'AMD', '0x10de': 'NVIDIA', '0x8086': 'Intel'}.get(read(device / 'vendor'), 'Unknown')
        name = read(device / 'product_name')
        if not name:
            try:
                raw = command(['lspci', '-s', device.name])
                name = raw.split(': ', 1)[1].strip() if ': ' in raw else ''
            except Exception:
                pass
        name = name or vendor + ' GPU (model unknown)'
        total = integer(read(device / 'mem_info_vram_total')) if vendor == 'AMD' else None
        # Driver residency counters are not a measurement of currently allocatable memory.
        capable = ['rocm', 'vulkan'] if vendor == 'AMD' else ['vulkan'] if vendor in ('Intel', 'NVIDIA') else []
        backends = [backend for backend in capable if backend in installed]
        cards.append(gpu_record(vendor, name, total, backends, 'AMDGPU_SYSFS' if total is not None else 'UNKNOWN'))
    return cards + list(nvidia.values())


def metal_available():
    """Probe an actual Metal device, including inside a macOS virtual machine."""
    try:
        metal = ctypes.CDLL('/System/Library/Frameworks/Metal.framework/Metal')
        metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        metal.MTLCreateSystemDefaultDevice.argtypes = []
        device = metal.MTLCreateSystemDefaultDevice()
        if not device:
            return False
        objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_msgSend.restype = None
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc.objc_msgSend(device, objc.sel_registerName(b'release'))
        return True
    except (OSError, AttributeError):
        return False


def mac_gpus(cpu, memory):
    if memory['unified']:
        # The M-series GPU is on this measured chip and shares system memory.
        return [gpu_record('Apple', cpu['model'], 0, ['metal'] if metal_available() else ['cpu'], 'APPLE_UNIFIED_MEMORY')]
    try:
        displays = json.loads(command(['system_profiler', 'SPDisplaysDataType', '-json'])).get('SPDisplaysDataType', [])
        cards = []
        for gpu in displays:
            name = gpu.get('sppci_model') or gpu.get('_name') or 'Unknown GPU'
            vendor = 'AMD' if re.search(r'AMD|Radeon', name, re.I) else 'NVIDIA' if re.search(r'NVIDIA|GeForce', name, re.I) else 'Intel' if 'Intel' in name else 'Unknown'
            cards.append(gpu_record(vendor, name, None, ['cpu'], 'UNKNOWN'))
        return cards
    except Exception:
        return []


def model_directory(override=None):
    configured = override or os.environ.get('OLLAMA_MODELS')
    if configured:
        return Path(configured).expanduser()
    return Path.home() / '.ollama' / 'models' if sys.platform == 'darwin' else Path('/usr/share/ollama/.ollama/models')


def scan_system(models_dir=None):
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        raise RuntimeError('This download is for macOS and Linux. Use the Windows detector on Windows.')
    cpu, memory = cpu_info(), memory_info()
    model_path = model_directory(models_dir)
    while not model_path.exists() and model_path != model_path.parent:
        model_path = model_path.parent
    free = shutil.disk_usage(model_path).free
    if free < 0:
        raise RuntimeError('Free disk space could not be measured.')
    return {'source': 'detector', 'schemaVersion': '1.0.0', 'detectorVersion': VERSION,
            'os': {'name': 'macOS' if sys.platform == 'darwin' else 'Linux',
                   'version': platform.mac_ver()[0] if sys.platform == 'darwin' else platform.release(),
                   'arch': platform.machine()}, 'cpu': cpu, 'memory': memory,
            'gpus': mac_gpus(cpu, memory) if sys.platform == 'darwin' else linux_gpus(),
            'storage': {'freeBytes': free}, 'runtimes': detector.get_runtimes_info()}


def upload(profile, scan_id, secret, server):
    parsed = urllib.parse.urlsplit(server)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('Uploads require HTTPS, except explicit local development.')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError('Invalid server URL.')
    if not re.fullmatch(r'scan-[0-9a-f]{16}', scan_id) or not re.fullmatch(r'[0-9a-f]{32}', secret):
        raise ValueError('Invalid pairing code. Start a new scan on the website.')
    request = urllib.request.Request(server.rstrip('/') + '/api/scan/' + scan_id,
                                    data=json.dumps({'hardware': profile}).encode(),
                                    headers={'Content-Type': 'application/json', 'x-upload-secret': secret})
    # Do not forward a scan capability to a redirect target.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        if not json.load(response).get('success'):
            raise RuntimeError('Upload was not accepted. Start a new scan on the website.')


def main():
    parser = argparse.ArgumentParser(description='Read-only hardware check for macOS and Linux. Python 3.9+ required.')
    parser.add_argument('--profile-only', action='store_true', help='Print measured hardware JSON without uploading')
    parser.add_argument('--pairing-code', help='Optional fallback: the pairing code from the scan page')
    parser.add_argument('--server', default=None, help='Explicit development server override')
    parser.add_argument('--models-dir', help='Measure free space on a custom model directory or drive')
    args = parser.parse_args()
    try:
        profile = scan_system(args.models_dir)
        if args.profile_only:
            print(json.dumps(profile, indent=2))
            return 0
        scan_id, secret, dev = detector.pairing_from_filename()
        if args.pairing_code:
            scan_id, secret = args.pairing_code.split(':', 1)
        if not scan_id or not secret:
            raise ValueError('Keep the original download filename, or provide --pairing-code from the website.')
        upload(profile, scan_id, secret, args.server or (detector.DEFAULT_DEV_URL if dev else detector.DEFAULT_PROD_URL))
        print('Hardware uploaded. Return to the same browser tab to see your model requirements.')
        return 0
    except Exception as error:
        print('Scan failed: ' + str(error) + '\nUse https://canmypcrunai.online/my-pc for manual entry.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
