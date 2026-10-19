"""Reproducible host Micro INT8 verification and float execution experiments.

Writes only to a new output directory. No server, camera, network or hardware.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS = ROOT / "experiments/activation_compression"
DEFAULT_RUNTIME = ROOT / "src/client/esp32-s3-eye-http/.pio/libdeps/esp32dev/TensorFlowLite_ESP32/src"
MODEL_DIR = ROOT / "src/server/models/test/test_model"
SPLITS = (0, 11, 25, 58)
RESIDUALS = {25: 16, 43: 34, 52: 43}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def execute(command, log, env=None):
    with log.open("w") as output:
        process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, env=env)
    require(process.returncode == 0, f"Command failed; see {log}")


def build(runtime, out, sanitized):
    directory = out / ("build-sanitized" if sanitized else "build-release")
    execute(["cmake", "-S", str(Path(__file__).parent), "-B", str(directory),
             f"-DTFLM_ROOT={runtime}", f"-DSCIOT_SANITIZERS={'ON' if sanitized else 'OFF'}",
             f"-DCMAKE_BUILD_TYPE={'Debug' if sanitized else 'Release'}",
             "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], out / f"{directory.name}-configure.log")
    execute(["cmake", "--build", str(directory), "--target", "experiment_host", "-j", "2"],
            out / f"{directory.name}.log")
    commands = json.loads((directory / "compile_commands.json").read_text())
    for entry in commands:
        command = entry["command"]
        require("-UNDEBUG" in command and "-ffp-contract=off" in command and "-fno-fast-math" in command,
                "Missing correctness compile flags")
        require(("-fsanitize=address,undefined" in command) == sanitized, "Wrong sanitizer configuration")
        if not sanitized:
            require("-O3" in command, "Release must use O3")
    return directory / "experiment_host"


def native(executable, mode, fixtures, out):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    process = subprocess.run([str(executable), mode, str(fixtures)], capture_output=True, text=True, env=env)
    (out / f"{mode}-stdout.txt").write_text(process.stdout)
    (out / f"{mode}-stderr.txt").write_text(process.stderr)
    require(process.returncode == 0 or (mode == "int8" and process.returncode == 2),
            f"Native {mode} failed; see {out / (mode + '-stderr.txt')}")
    return json.loads(process.stdout.strip().splitlines()[-1])


def prepare_int8(fixtures):
    source = EXPERIMENTS / "esp32_prep_2026-10-19"
    manifest = json.loads((source / "manifest.json").read_text())
    require(digest(source / "vectors.npz") == manifest["vectors_sha256"], "Vector hash mismatch")
    with np.load(source / "vectors.npz", allow_pickle=False) as saved:
        vectors = {key: saved[key] for key in saved.files}
    require(vectors["frame_indices"].tolist() == manifest["selected_frame_indices"], "Wrong frames")
    for stage, input_key, output_key in (("full", "inputs", "outputs"),
                                          ("prefix", "inputs", "boundaries"),
                                          ("suffix", "boundaries", "outputs")):
        path = source / f"{stage}.tflite"
        spec = manifest["models"][stage]
        require(digest(path) == spec["sha256"], f"Model hash mismatch: {stage}")
        shutil.copyfile(path, fixtures / path.name)
        lines = []
        for role in ("input", "output"):
            tensor = spec[role]
            require(tensor["dtype"] == "int8" and len(tensor["scales"]) == 1
                    and len(tensor["zero_points"]) == 1, "Unexpected INT8 specification")
            shape = tensor["shape"]
            lines.append(" ".join(map(str, [tensor["logical_value_bytes"], tensor["scales"][0],
                                           tensor["zero_points"][0], len(shape), *shape])))
        (fixtures / f"{stage}.spec").write_text("\n".join(lines) + "\n")
        for sample in range(3):
            vectors[input_key][sample].tofile(fixtures / f"input_{stage}_{sample}.bin")
            vectors[output_key][sample].tofile(fixtures / f"expected_{stage}_{sample}.bin")
    return {"frame_indices": vectors["frame_indices"].tolist(), "vectors_sha256": manifest["vectors_sha256"],
            "model_sha256": {name: manifest["models"][name]["sha256"] for name in ("full", "prefix", "suffix")}}


def verify_int8_files(fixtures):
    results = {}
    for stage in ("full", "prefix", "suffix", "suffix_chain"):
        results[stage] = []
        expected_stage = "suffix" if stage == "suffix_chain" else stage
        for sample in range(3):
            actual = (fixtures / f"actual_{stage}_{sample}.bin").read_bytes()
            expected = (fixtures / f"expected_{expected_stage}_{sample}.bin").read_bytes()
            a = np.frombuffer(actual, np.int8).astype(np.int16)
            e = np.frombuffer(expected, np.int8).astype(np.int16)
            require(a.shape == e.shape, "INT8 output length mismatch")
            results[stage].append({"sample": sample, "exact_match": actual == expected,
                                   "mismatched_values": int(np.count_nonzero(a != e)),
                                   "max_integer_error": int(np.max(np.abs(a - e)))})
    results["micro_full_vs_micro_chain_exact"] = [
        (fixtures / f"actual_full_{i}.bin").read_bytes() ==
        (fixtures / f"actual_suffix_chain_{i}.bin").read_bytes() for i in range(3)]
    return results


def diagnose_int8_desktop(fixtures):
    """Keep the archived oracle; separately identify differences between kernels."""
    import tensorflow as tf
    results = {}
    for name, resolver in (("BUILTIN_REF", tf.lite.experimental.OpResolverType.BUILTIN_REF),
                           ("BUILTIN_WITHOUT_DEFAULT_DELEGATES",
                            tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)):
        results[name] = {}
        for stage in ("full", "prefix", "suffix"):
            runtime = tf.lite.Interpreter(model_path=str(fixtures / f"{stage}.tflite"),
                                         num_threads=1, experimental_op_resolver_type=resolver)
            runtime.allocate_tensors()
            input_spec, output_spec = runtime.get_input_details()[0], runtime.get_output_details()[0]
            results[name][stage] = []
            for sample in range(3):
                values = np.fromfile(fixtures / f"input_{stage}_{sample}.bin", np.int8).reshape(input_spec["shape"])
                runtime.set_tensor(input_spec["index"], values)
                runtime.invoke()
                actual = runtime.get_tensor(output_spec["index"]).tobytes()
                archived = (fixtures / f"expected_{stage}_{sample}.bin").read_bytes()
                micro = (fixtures / f"actual_{stage}_{sample}.bin").read_bytes()
                results[name][stage].append({"sample": sample, "matches_archived": actual == archived,
                                             "matches_micro": actual == micro})
    return results


def prepare_float(fixtures):
    import tensorflow as tf
    from compose_float_prefix import compose_prefix
    from split_tflite import unpack

    model = tf.keras.models.load_model(MODEL_DIR / "test_model.h5", compile=False)
    residuals = {}
    for index, layer in enumerate(model.layers[1:]):
        if isinstance(layer.input, (list, tuple)) and len(layer.input) == 2:
            sources = [model.layers.index(t._keras_history.layer) - 1 for t in layer.input]
            require(index - 1 in sources, "Unexpected residual topology")
            residuals[index] = next(i for i in sources if i != index - 1)
    require(residuals == RESIDUALS, "Original residual graph changed")
    binaries, runtimes, hashes = [], [], {}
    for index in range(59):
        path = MODEL_DIR / f"layers/tflite/submodel_{index}.tflite"
        binaries.append(path.read_bytes())
        hashes[path.name] = digest(path)
        (fixtures / f"layer_{index}.tflite").write_bytes(binaries[-1])
        runtime = tf.lite.Interpreter(model_content=binaries[-1], num_threads=1,
                                     experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
        runtime.allocate_tensors()
        runtimes.append(runtime)
    inputs = np.stack([np.zeros((96, 96, 3), np.float32),
                       np.random.default_rng(20261019).random((96, 96, 3), dtype=np.float32),
                       np.linspace(0, 1, 96 * 96 * 3, dtype=np.float32).reshape(96, 96, 3)])
    references = {}
    for sample, values in enumerate(inputs):
        values.tofile(fixtures / f"input_{sample}.bin")
        work, residual = values[None], None
        for index, runtime in enumerate(runtimes):
            details = runtime.get_input_details()
            runtime.set_tensor(details[0]["index"], work)
            if len(details) == 2:
                runtime.set_tensor(details[1]["index"], residual)
            runtime.invoke()
            work = runtime.get_tensor(runtime.get_output_details()[0]["index"])
            if index in (16, 34, 43):
                residual = work.copy()
            if index in SPLITS:
                references[sample, index] = work.copy()
                work.tofile(fixtures / f"reference_{sample}_{index}.bin")
    prefixes = {}
    max_error = 0.0
    for split in SPLITS:
        binary = compose_prefix(binaries[:split + 1], RESIDUALS)
        path = fixtures / f"prefix_{split}.tflite"
        path.write_bytes(binary)
        # Audit preserved operator options/versions and constant data structurally.
        composed = unpack(binary)
        actual_ops = composed.subgraphs[0].operators
        cursor = 0
        for layer_binary in binaries[:split + 1]:
            original = unpack(layer_binary)
            for op in original.subgraphs[0].operators:
                actual = actual_ops[cursor]
                source_code = original.operatorCodes[op.opcodeIndex]
                target_code = composed.operatorCodes[actual.opcodeIndex]
                require(vars(source_code) == vars(target_code), "Changed operator code")
                require(op.builtinOptionsType == actual.builtinOptionsType, "Changed options type")
                # Flatbuffer packing checks fields including array-valued options.
                from split_tflite import pack
                import copy
                expected_op, observed_op = copy.deepcopy(op), copy.deepcopy(actual)
                for item in (expected_op, observed_op):
                    item.inputs = item.outputs = item.intermediates = None
                    item.opcodeIndex = 0
                left, right = copy.deepcopy(original), copy.deepcopy(original)
                left.subgraphs[0].operators, right.subgraphs[0].operators = [expected_op], [observed_op]
                require(pack(left) == pack(right), "Changed operator options")
                cursor += 1
        require(cursor == len(actual_ops), "Changed operator count")
        expected_constants = [(None if buf.data is None else bytes(buf.data)) for content in binaries[:split + 1]
                              for buf in unpack(content).buffers[1:]]
        actual_constants = [(None if buf.data is None else bytes(buf.data)) for buf in composed.buffers[1:]]
        require(expected_constants == actual_constants, "Changed constant buffers")
        runtime = tf.lite.Interpreter(model_content=binary, num_threads=1,
                                     experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
        runtime.allocate_tensors()
        for sample in range(3):
            runtime.set_tensor(runtime.get_input_details()[0]["index"], inputs[sample:sample + 1])
            runtime.invoke()
            actual = runtime.get_tensor(runtime.get_output_details()[0]["index"])
            expected = references[sample, split]
            np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-5)
            max_error = max(max_error, float(np.max(np.abs(actual - expected))))
        prefixes[str(split)] = {"sha256": digest(path), "file_bytes": len(binary), "operators": cursor,
                                "source_layer_count": split + 1}
    return {"source_model_sha256": digest(MODEL_DIR / "test_model.h5"), "source_layer_sha256": hashes,
            "prefixes": prefixes, "desktop_grouped_max_absolute_error": max_error,
            "residual_sources": residuals, "operators_options_constants_preserved": True}


def timing_summary(path):
    with path.open() as source:
        rows = list(csv.DictReader(source))
    require(len(rows) == 4 * 3 * 3 * 30, "Incomplete benchmark")
    grouped = {}
    for split in SPLITS:
        grouped[str(split)] = {}
        for sample in range(3):
            grouped[str(split)][str(sample)] = {}
            for mode in ("separate", "grouped_recreated", "grouped_persistent"):
                selected = [row for row in rows if int(row["split"]) == split
                            and int(row["sample"]) == sample and row["mode"] == mode]
                require(sorted(int(row["round"]) for row in selected) == list(range(30)), "Missing/duplicate sample")
                values = np.array([float(row["total_us"]) for row in selected])
                require(np.all(np.isfinite(values)) and np.all(values > 0), "Invalid timing")
                grouped[str(split)][str(sample)][mode] = dict(zip(
                    ("p10_us", "median_us", "p90_us"), np.percentile(values, [10, 50, 90]).tolist()))
    return grouped


def provenance(runtime):
    paths = [Path(__file__), Path(__file__).with_name("CMakeLists.txt"),
             Path(__file__).with_name("experiment_host.cpp"), ROOT / "src/client/common/float_layer.h",
             EXPERIMENTS / "compose_float_prefix.py", EXPERIMENTS / "test_compose_float_prefix.py"]
    properties = dict(line.split("=", 1) for line in (runtime.parent / "library.properties").read_text().splitlines()
                      if "=" in line)
    require(properties.get("name") == "TensorFlowLite_ESP32" and properties.get("version") == "1.0.0",
            "This experiment requires TensorFlowLite_ESP32 1.0.0")
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    runtime_files = sorted(p for p in runtime.rglob("*") if p.is_file() and p.suffix in (".h", ".cpp", ".c"))
    runtime_hash = hashlib.sha256()
    for path in runtime_files:
        runtime_hash.update(str(path.relative_to(runtime)).encode() + b"\0" + bytes.fromhex(digest(path)))
    return {"cpu": cpu, "platform": platform.platform(), "python": sys.version,
            "compiler": subprocess.check_output(["c++", "--version"], text=True).splitlines()[0],
            "cmake": subprocess.check_output(["cmake", "--version"], text=True).splitlines()[0],
            "tensorflow": __import__("tensorflow").__version__, "numpy": np.__version__,
            "runtime_path": str(runtime), "runtime_version": properties["version"],
            "runtime_source_tree_sha256": runtime_hash.hexdigest(),
            "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in paths},
            "command": [sys.executable, *sys.argv]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=("int8", "float"))
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    runtime, out = args.runtime.resolve(), args.output_dir.resolve()
    require((runtime / "tensorflow/lite/micro/micro_interpreter.cpp").is_file(), "Install pinned runtime first")
    require(not out.exists(), "Use a new output directory; previous evidence is never overwritten")
    out.mkdir(parents=True)
    fixtures = out / "fixtures"
    fixtures.mkdir()
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", TF_CPP_MIN_LOG_LEVEL="3", TF_ENABLE_ONEDNN_OPTS="0")
    sys.path.insert(0, str(EXPERIMENTS))
    report = {"experiment": args.experiment, "scope": "Native host only; no ESP32 verification", "passed": False}
    try:
        report["provenance"] = provenance(runtime)
        if args.experiment == "int8":
            report["artifacts"] = prepare_int8(fixtures)
            report["native"] = native(build(runtime, out, True), "int8", fixtures, out)
            report["independent_output_check"] = verify_int8_files(fixtures)
            report["desktop_kernel_diagnostics"] = diagnose_int8_desktop(fixtures)
        else:
            report["artifacts"] = prepare_float(fixtures)
            report["correctness"] = native(build(runtime, out, True), "float-check", fixtures, out)
            report["benchmark"] = native(build(runtime, out, False), "float-bench", fixtures, out)
            report["timings"] = timing_summary(fixtures / "timings.csv")
            shutil.copyfile(fixtures / "timings.csv", out / "timings.csv")
            report["benchmark_method"] = {
                "warmups_per_input_mode_split": 5, "runs_per_input_mode_split": 30,
                "ordering": "Round/sample-dependent cyclic mode order; inputs alternate each round",
                "timer": "C++ steady_clock, microseconds; wall time on this host",
                "timed": "Input copy to working buffer, per-frame preparation, invocation, output copy, destruction",
                "excluded": "File loading, arena reservation, resolver construction, comparisons, logging, persistent setup",
                "copy_counts": "Explicit application copies including initial input-to-work; not physical memory traffic",
                "buffers": "work 460992 bytes each mode; residual 460992 separate only; arenas 8 MiB each",
                "memory_scope": "Native ABI; no inference about ESP32 memory requirement",
                "timing_scope": "Host core inference harness; excludes firmware model-name lookup, camera, watchdog, network",
                "release_flags": "-O3 -fno-fast-math -ffp-contract=off -UNDEBUG; no sanitizers",
                "cpu_affinity": "Not pinned; background host activity not controlled",
            }
        report["passed"] = args.experiment != "int8" or report["native"]["exact_match"]
        if not report["passed"]:
            report["error"] = "Micro differs from archived desktop INT8 outputs; exact parity failed, diagnostics retained"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["builds"] = {}
        for directory in (out / "build-sanitized", out / "build-release"):
            binary = directory / "experiment_host"
            if binary.exists():
                commands = json.loads((directory / "compile_commands.json").read_text())
                report["builds"][directory.name] = {
                    "executable_sha256": digest(binary), "sanitizers": directory.name == "build-sanitized",
                    "runner_compile_command": next(e["command"] for e in commands
                                                   if e["file"].endswith("experiment_host.cpp"))}
        write_json(out / "summary.json", report)
    print(json.dumps({"passed": report["passed"], "experiment": args.experiment, "report": str(out / "summary.json")}, indent=2))
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
