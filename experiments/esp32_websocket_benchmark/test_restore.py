import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('ws_restore',HERE/'restore_components.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class RestoreTests(unittest.TestCase):
    def test_restore_and_recheck_clean_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);module.restore(root);module.restore(root,check=True)
            self.assertTrue((root/'experiments/esp32_nopad_benchmark/idf/components/esp-nn/CMakeLists.txt').is_file())

    def test_conflict_preserved_before_any_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'experiments/esp32_nopad_benchmark/idf/components/esp-nn/CMakeLists.txt'
            path.parent.mkdir(parents=True);path.write_text('local edit')
            with self.assertRaises(ValueError):module.restore(root)
            self.assertEqual(path.read_text(),'local edit')
            self.assertFalse((root/'src').exists())
