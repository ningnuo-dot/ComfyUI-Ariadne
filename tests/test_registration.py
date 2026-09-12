"""节点注册冒烟（不启动 ComfyUI：验证节点模块可导入、MAPPINGS 完整；路由注册静默跳过）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXPECTED_NODES = {"AriadneSeedance25Video", "AriadneVeo31Video", "AriadneKlingVideo", "AriadneKieImage"}


def _load_package():
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("comfyui_ariadne", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["comfyui_ariadne"] = module
    spec.loader.exec_module(module)
    return module


class RegistrationTests(unittest.TestCase):
    def test_all_nodes_registered(self):
        package = _load_package()
        self.assertTrue(EXPECTED_NODES.issubset(package.NODE_CLASS_MAPPINGS))
        for name in EXPECTED_NODES:
            self.assertIn(name, package.NODE_DISPLAY_NAME_MAPPINGS)
            self.assertIn("Ariadne", package.NODE_DISPLAY_NAME_MAPPINGS[name])
        self.assertEqual(package.WEB_DIRECTORY, "./web/js")
        self.assertEqual(package.__version__, "0.1.0")

    def test_input_types_contract(self):
        package = _load_package()
        schema = package.NODE_CLASS_MAPPINGS["AriadneSeedance25Video"].INPUT_TYPES()
        self.assertIn("prompt", schema["required"])
        self.assertIn("first_frame", schema["optional"])
        self.assertIn("motion_video", schema["optional"])
        self.assertEqual(schema["optional"]["motion_video"][0], "VIDEO")
        self.assertEqual(schema["optional"]["reference_audio"][0], "AUDIO")


if __name__ == "__main__":
    unittest.main()
