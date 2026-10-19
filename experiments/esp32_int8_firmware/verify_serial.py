"""Check a captured hardware-probe log against archived desktop INT8 vectors.

Requires a complete boot-to-done session. Non-JSON boot/runtime noise is ignored;
incomplete logs, duplicate cases and any numerical difference fail validation.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent / "activation_compression" / "esp32_prep_2026-10-19"


def verify(log, artifacts, stage):
    manifest = json.loads((artifacts / "manifest.json").read_text())
    path = artifacts / "vectors.npz"
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["vectors_sha256"]:
        raise ValueError("Vector hash mismatch")
    records = []
    for line in log.splitlines():
        line = line.strip()
        if line.startswith('{"event":'):
            records.append(json.loads(line))
    boots = [i for i, row in enumerate(records) if row.get("event") == "boot"]
    if not boots:
        raise ValueError("Missing boot record; press r and capture the complete session")
    # A reset in a monitor capture begins a new session. Verify the most recent one.
    records = records[boots[-1]:]
    boot = records[0]
    if (boot.get("stage") != stage or boot.get("model_sha256") != manifest["models"][stage]["sha256"]
            or boot.get("vectors_sha256") != manifest["vectors_sha256"]):
        raise ValueError("Wrong firmware stage, model or vectors")
    if (boot.get("runtime") != "TensorFlowLite_ESP32@1.0.0" or boot.get("esp_nn_enabled") is not False
            or boot.get("model_bytes") != manifest["models"][stage]["file_bytes"]
            or not isinstance(boot.get("cpu_mhz"), int) or boot["cpu_mhz"] <= 0
            or not isinstance(boot.get("psram_bytes"), int) or boot["psram_bytes"] < 0
            or not isinstance(boot.get("arena_capacity_bytes"), int) or boot["arena_capacity_bytes"] <= 0
            or not isinstance(boot.get("arena_in_psram"), bool) or not boot.get("sdk")):
        raise ValueError("Missing or unsupported firmware configuration")
    if any(row.get("event") == "error" for row in records):
        raise ValueError("Firmware reported an error")
    allocations = [row for row in records if row.get("event") == "allocated"]
    done = [row for row in records if row.get("event") == "done"]
    if len(allocations) != 1 or len(done) != 1 or done[0].get("stage") != stage:
        raise ValueError("Missing or duplicate allocation/completion records")
    if not 0 < allocations[0]["arena_used_bytes"] <= boot["arena_capacity_bytes"]:
        raise ValueError("Invalid reported arena usage")
    for role in ("input", "output"):
        if allocations[0][f"{role}_bytes"] != manifest["models"][stage][role]["logical_value_bytes"]:
            raise ValueError("Wrong tensor byte count")
    memory = [row for row in records if row.get("event") == "memory"]
    if not {"before_arena", "after_allocate_tensors", "after_case"} <= {row.get("phase") for row in memory}:
        raise ValueError("Missing memory observations")
    for row in memory:
        for kind in ("internal", "psram"):
            for field in ("free", "min_free", "largest_free"):
                value = row.get(f"{kind}_{field}")
                if type(value) is not int or value < 0:
                    raise ValueError("Missing or invalid memory byte count")
            if not (row[f"{kind}_min_free"] <= row[f"{kind}_free"]
                    and row[f"{kind}_largest_free"] <= row[f"{kind}_free"]):
                raise ValueError("Inconsistent memory observations")
    if sum(row.get("phase") == "after_case" for row in memory) != len(manifest["selected_frame_indices"]):
        raise ValueError("Missing per-case memory observations")
    cases = [row for row in records if row.get("event") == "case"]
    indices = manifest["selected_frame_indices"]
    if [row.get("frame_index") for row in cases] != indices or done[0].get("cases") != len(indices):
        raise ValueError("Missing, duplicate or reordered test cases")
    if records.index(done[0]) < max(records.index(row) for row in cases):
        raise ValueError("Completion precedes test cases")
    checked = []
    with np.load(path, allow_pickle=False) as vectors:
        expected = vectors["boundaries" if stage == "prefix" else "outputs"]
        for i, row in enumerate(cases):
            if row.get("stage") != stage or row.get("runs") != 10 or row.get("warmups") != 2:
                raise ValueError("Unexpected case protocol")
            if not 0 < row["invoke_min_us"] <= row["invoke_p50_us"] <= row["invoke_max_us"]:
                raise ValueError("Invalid timing observations")
            values = np.frombuffer(bytes.fromhex(row["output_hex"]), dtype=np.int8)
            reference = expected[i].reshape(-1)
            if values.size != reference.size:
                raise ValueError("Truncated/wrong-length output")
            errors = np.abs(values.astype(np.int16) - reference.astype(np.int16))
            mismatches = int(np.count_nonzero(errors))
            checked.append({"frame_index": indices[i], "final_output_mismatched_values": mismatches,
                            "final_output_max_abs_error_integer_steps": int(errors.max()),
                            "all_runs_exact_match": row.get("exact_match_all_runs") is True
                            and row.get("max_mismatched_values_per_run") == 0
                            and row.get("max_abs_error_integer_steps") == 0,
                            "invoke_min_us": row["invoke_min_us"], "invoke_p50_us": row["invoke_p50_us"],
                            "invoke_max_us": row["invoke_max_us"]})
    passed = all(row["final_output_mismatched_values"] == 0 and row["all_runs_exact_match"] for row in checked)
    return {"scope": "Captured ESP32 probe log vs desktop expected bytes; excludes camera and network",
            "stage": stage, "boot": boot, "allocation": allocations[0], "memory": memory,
            "cases": checked, "passed": passed,
            "note": "A difference is a failed exact-parity check; no accuracy tolerance is implicitly accepted"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--stage", choices=("full", "prefix", "suffix"), required=True)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.log.read_text(errors="replace"), args.artifacts, args.stage)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{args.stage}: {'PASS' if result['passed'] else 'FAIL'}, {len(result['cases'])} cases; {args.output}")
    raise SystemExit(0 if result["passed"] else 1)
