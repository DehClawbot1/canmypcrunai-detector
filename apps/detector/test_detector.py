import copy
import unittest
from unittest.mock import patch

import detector


class DetectorEvidenceTests(unittest.TestCase):
    def nvidia(self, name, free):
        return {"vendor": "NVIDIA", "model": name, "localMemoryAvailableBytes": free,
                "vramAvailableBytes": free, "driverVersion": "570.86", "detection": {}}

    def test_nvidia_driver_is_reported(self):
        with patch.object(detector, "detect_system_backends", return_value=["cuda", "cpu"]), \
             patch.object(detector, "run_hidden", return_value="NVIDIA GeForce RTX 4090, 24576, 20000, 570.86\n"):
            result = detector.get_nvidia_smi_gpus()
        self.assertEqual(result[0]["driverVersion"], "570.86")
        self.assertEqual(result[0]["vramAvailableBytes"], 20000 * 1024 ** 2)

    def test_different_cards_keep_their_own_available_memory(self):
        cards = [self.nvidia("NVIDIA GeForce RTX 3080", 100), self.nvidia("NVIDIA GeForce RTX 4090", 200)]
        nv = [self.nvidia("NVIDIA GeForce RTX 4090", 400), self.nvidia("NVIDIA GeForce RTX 3080", 300)]
        with patch.object(detector, "detect_system_backends", return_value=["cpu"]), \
             patch.object(detector, "get_dxgi_gpus", return_value=cards), \
             patch.object(detector, "get_nvidia_smi_gpus", return_value=nv):
            result = detector.get_gpus_info()
        self.assertEqual([card["vramAvailableBytes"] for card in result], [300, 400])

    def test_identical_cards_do_not_guess_enumeration_order(self):
        cards = [self.nvidia("RTX 3080", 100), self.nvidia("RTX 3080", 200)]
        before = copy.deepcopy(cards)
        with patch.object(detector, "detect_system_backends", return_value=["cpu"]), \
             patch.object(detector, "get_dxgi_gpus", return_value=cards), \
             patch.object(detector, "get_nvidia_smi_gpus", return_value=[self.nvidia("RTX 3080", 999)]):
            self.assertEqual(detector.get_gpus_info(), before)

    def test_missing_unix_available_memory_fails_instead_of_guessing(self):
        with patch.object(detector.sys, "platform", "linux"), \
             patch.object(detector, "_unix_memory", return_value=(16 * 1024 ** 3, None)):
            with self.assertRaises(detector.UnsupportedPlatform):
                detector.get_memory_info()

    def test_zero_available_memory_is_a_real_measurement(self):
        with patch.object(detector.sys, "platform", "linux"), \
             patch.object(detector, "_unix_memory", return_value=(16 * 1024 ** 3, 0)):
            self.assertEqual(detector.get_memory_info()["availableBytes"], 0)


if __name__ == "__main__":
    unittest.main()
