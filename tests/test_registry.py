import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from scenic_devices.registry import validate_registry


class RegistryTest(unittest.TestCase):
    def test_sample_registry_is_safe(self) -> None:
        items = json.loads((Path(__file__).parents[1] / "data" / "devices.json").read_text(encoding="utf-8"))
        validate_registry(items)


if __name__ == "__main__":
    unittest.main()
