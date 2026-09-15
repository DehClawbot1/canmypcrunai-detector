import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import unix_detector as unix


class UnixHardwareTests(unittest.TestCase):
    def test_apple_memory_is_not_invented_available_memory_or_dedicated_vram(self):
        with patch.object(unix.sys, 'platform', 'darwin'), patch.object(unix.platform, 'machine', return_value='arm64'), patch.object(unix, 'command', return_value=str(16 * 1024 ** 3)):
            memory = unix.memory_info()
        self.assertEqual(memory, {'totalBytes': 16 * 1024 ** 3, 'availableBytes': None, 'unified': True})
        with patch.object(unix, 'metal_available', return_value=True):
            gpu = unix.mac_gpus({'model': 'Apple M2'}, memory)[0]
        self.assertEqual(gpu['vramTotalBytes'], 0)
        self.assertEqual(gpu['backends'], ['metal'])

    def test_apple_virtual_machine_without_metal_keeps_cpu_backend(self):
        with patch.object(unix, 'metal_available', return_value=False):
            gpu = unix.mac_gpus({'model': 'Apple M1 (Virtual)'}, {'unified': True})[0]
        self.assertEqual(gpu['backends'], ['cpu'])

    def test_linux_memory_zero_and_missing_are_distinct(self):
        with patch.object(unix.sys, 'platform', 'linux'), patch.object(unix, 'read', return_value='MemTotal: 16000 kB\nMemAvailable: 0 kB'):
            self.assertEqual(unix.memory_info()['availableBytes'], 0)
        with patch.object(unix.sys, 'platform', 'linux'), patch.object(unix, 'read', return_value='MemTotal: 16000 kB'):
            self.assertIsNone(unix.memory_info()['availableBytes'])

    def test_missing_total_ram_fails(self):
        with patch.object(unix.sys, 'platform', 'linux'), patch.object(unix, 'read', return_value=''):
            with self.assertRaises(RuntimeError):
                unix.memory_info()

    def test_nvidia_matches_by_bus_and_never_guesses_missing_vram(self):
        with patch.object(unix, 'command', return_value='00000000:01:00.0, RTX 4090, 24576, 20000, 570.86\n00000000:02:00.0, RTX 4090, N/A, N/A, 570.86'):
            cards = unix.nvidia_by_bus()
        self.assertEqual(cards[unix.pci_key('0000:01:00.0')]['vramTotalBytes'], 24576 * 1024 ** 2)
        self.assertIsNone(cards[unix.pci_key('0000:02:00.0')]['vramTotalBytes'])

    def test_amd_sysfs_capacity_is_not_used_as_free_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            device = root / 'card0' / 'device'
            device.mkdir(parents=True)
            (device / 'vendor').write_text('0x1002')
            (device / 'product_name').write_text('AMD Radeon RX 9060 XT')
            (device / 'mem_info_vram_total').write_text(str(16 * 1024 ** 3))
            with patch.object(unix, 'nvidia_by_bus', return_value={}), patch.object(unix.detector, 'detect_system_backends', return_value={'vulkan', 'cpu'}):
                gpu = unix.linux_gpus(root)[0]
            self.assertEqual(gpu['vramTotalBytes'], 16 * 1024 ** 3)
            self.assertIsNone(gpu['vramAvailableBytes'])
            self.assertEqual(gpu['backends'], ['vulkan'])

    def test_upload_rejects_insecure_remote_hosts_before_network_access(self):
        with self.assertRaises(ValueError):
            unix.upload({}, 'scan-' + 'a' * 16, 'b' * 32, 'http://example.com')


if __name__ == '__main__':
    unittest.main()
