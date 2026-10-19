"""Synthetic logs test validation only; these are not hardware measurements."""

import json
import unittest

import numpy as np

from verify_serial import DEFAULT, verify


def synthetic_records():
    manifest = json.loads((DEFAULT / "manifest.json").read_text())
    model = manifest["models"]["prefix"]
    records = [{"event": "boot", "stage": "prefix", "model_sha256": model["sha256"],
                "vectors_sha256": manifest["vectors_sha256"], "arena_capacity_bytes": 524288,
                "model_bytes": model["file_bytes"], "runtime": "TensorFlowLite_ESP32@1.0.0",
                "esp_nn_enabled": False, "cpu_mhz": 240, "psram_bytes": 8388608,
                "arena_in_psram": True, "sdk": "synthetic-test-not-hardware"},
               {"event": "memory", "phase": "before_arena"},
               {"event": "allocated", "arena_used_bytes": 1024, "input_bytes": 9216, "output_bytes": 4608},
               {"event": "memory", "phase": "after_allocate_tensors"}]
    with np.load(DEFAULT / "vectors.npz", allow_pickle=False) as vectors:
        for index, values in zip(vectors["frame_indices"], vectors["boundaries"]):
            records.append({"event": "case", "stage": "prefix", "frame_index": int(index),
                            "runs": 10, "warmups": 2, "invoke_min_us": 1,
                            "invoke_p50_us": 2, "invoke_max_us": 3,
                            "max_mismatched_values_per_run": 0, "max_abs_error_integer_steps": 0,
                            "exact_match_all_runs": True, "output_hex": values.tobytes().hex()})
            records.append({"event": "memory", "phase": "after_case"})
    records.append({"event": "done", "stage": "prefix", "cases": 3})
    for row in records:
        if row["event"] == "memory":
            for kind in ("internal", "psram"):
                row.update({f"{kind}_free": 1024, f"{kind}_min_free": 512, f"{kind}_largest_free": 512})
    return records


def check(records):
    return verify("boot noise\n" + "\n".join(json.dumps(row, separators=(",", ":")) for row in records),
                  DEFAULT, "prefix")


class SerialTests(unittest.TestCase):
    def test_complete_synthetic_session_is_checked(self):
        self.assertTrue(check(synthetic_records())["passed"])

    def test_changed_byte_fails_even_if_firmware_claims_match(self):
        records = synthetic_records()
        row = next(row for row in records if row["event"] == "case")
        data = bytearray.fromhex(row["output_hex"])
        data[0] ^= 1
        row["output_hex"] = data.hex()
        self.assertFalse(check(records)["passed"])

    def test_incomplete_duplicate_or_wrong_model_logs_are_rejected(self):
        for mutation in ("incomplete", "duplicate", "wrong_model", "earlier_invoke_failed",
                         "missing_memory", "missing_config"):
            records = synthetic_records()
            if mutation == "incomplete":
                records.pop()
            elif mutation == "duplicate":
                records.insert(-1, next(row for row in records if row["event"] == "case"))
            elif mutation == "wrong_model":
                records[0]["model_sha256"] = "0" * 64
            elif mutation == "missing_memory":
                next(row for row in records if row["event"] == "memory").pop("internal_free")
            elif mutation == "missing_config":
                records[0].pop("cpu_mhz")
            else:
                records.insert(-1, {"event": "error", "reason": "invoke_failed"})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check(records)

    def test_new_incomplete_boot_does_not_reuse_an_old_success(self):
        records = synthetic_records()
        records.append(records[0].copy())
        with self.assertRaises(ValueError):
            check(records)


if __name__ == "__main__":
    unittest.main()
