"""Offline checks for archive provenance and authentication-free validation."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from deploy import failure_kind, inspect_archive, verify_preparation


class DeploymentTests(unittest.TestCase):
    def test_enterprise_gate_is_not_classified_as_technical_incompatibility(self):
        self.assertEqual(failure_kind("The EON Compiler is only available for pretrained models for enterprise projects."),
                         "enterprise_required_for_imported_model")
        self.assertEqual(failure_kind("The API key has insufficient permissions"),
                         "api_key_role_insufficient")
        self.assertEqual(failure_kind("Unsupported operator"), "export_error")

    def test_archive_does_not_imply_hardware_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("tflite-model/trained_model_compiled.cpp", "// source")
                archive.writestr("model-parameters/model_metadata.h", "// metadata")
            result = inspect_archive(path)
            self.assertEqual(len(result["compiled_source_candidates"]), 1)
            self.assertFalse(result["hardware_validated"])
            self.assertFalse(result["raw_int8_access_verified"])
            self.assertFalse(result["esp_nn_calls_verified"])

    def test_changed_prepared_file_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "model.bin").write_bytes(b"changed")
            (path / "manifest.json").write_text(json.dumps({"files": {"model.bin": "wrong"}}))
            with self.assertRaisesRegex(ValueError, "changed"):
                verify_preparation(path)

    def test_unsafe_manifest_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "manifest.json").write_text(json.dumps({"files": {"../model.bin": "wrong"}}))
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                verify_preparation(path)


if __name__ == "__main__":
    unittest.main()
