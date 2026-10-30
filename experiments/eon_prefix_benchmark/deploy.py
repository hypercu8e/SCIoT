"""Export the frozen prefix through Edge Impulse using a project API key file.

The high-level SDK 1.0.20 rejects four-dimensional freeform outputs. Use its
official API bindings for upload/configuration and experimental.impulse.build
for compilation (the same entrypoint used internally by SDK model.deploy).
Never present an export as a verified firmware integration.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent


def failure_kind(message):
    if "EON Compiler is only available for pretrained models for enterprise projects" in message:
        return "enterprise_required_for_imported_model"
    if "insufficient permissions" in message:
        return "api_key_role_insufficient"
    return "export_error"


def verify_preparation(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("Unsafe manifest filename")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Prepared artifact changed: {name}")
    binary = directory / "int8-prefix.tflite"
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["models"]["prefix"]["sha256"]:
        raise ValueError("Prefix does not match frozen model")
    return manifest


def freeform_parameters():
    from edgeimpulse_api.models.save_pretrained_model_request import SavePretrainedModelRequest
    return SavePretrainedModelRequest.from_dict({
        "input": {"inputType": "other"}, "model": {"modelType": "freeform"},
    })


def check_sdk():
    from edgeimpulse.experimental.impulse import build
    from edgeimpulse_api.models.build_on_device_model_request import BuildOnDeviceModelRequest
    if not callable(build):
        raise ValueError("SDK build entrypoint unavailable")
    request = BuildOnDeviceModelRequest.from_dict({"engine": "tflite-eon", "modelType": "int8"})
    if request.to_dict() != {"engine": "tflite-eon", "modelType": "int8"}:
        raise ValueError("SDK did not preserve EON/INT8 build parameters")


def inspect_archive(path):
    # Inspect in place; do not extract or execute downloaded source code.
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 20000 or sum(i.file_size for i in archive.infolist()) > 512 * 1024**2:
            raise ValueError("Export archive exceeds inspection limits")
        records, compiled, metadata = [], [], []
        for item in archive.infolist():
            if item.is_dir():
                continue
            data = archive.read(item)
            records.append({"name": item.filename, "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
            if "compiled" in item.filename and item.filename.endswith((".cpp", ".h")):
                compiled.append(item.filename)
            if item.filename.endswith("model_metadata.h"):
                metadata.append(item.filename)
    if not records:
        raise ValueError("Empty export archive")
    return {"export_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "files": records, "compiled_source_candidates": compiled,
            "metadata_candidates": metadata,
            "raw_int8_access_verified": False, "esp_nn_calls_verified": False,
            "firmware_built": False, "hardware_validated": False}


def export(directory, output, key):
    from edgeimpulse.experimental.impulse import build
    from edgeimpulse.util import (configure_generic_client, default_project_id_for,
                                 upload_pretrained_model_and_data, check_response_errors)
    from edgeimpulse_api import LearnApi

    manifest = verify_preparation(directory)
    output.mkdir(parents=True, exist_ok=False)
    with configure_generic_client(key) as client:
        project = default_project_id_for(client)
        with tempfile.TemporaryDirectory() as tempdir:
            upload_pretrained_model_and_data(
                tempdir=tempdir, client=client, project_id=project,
                model=str(directory / "int8-prefix.tflite"),
                representative_data=None, timeout_sec=600)
        print(json.dumps({"event": "prefix_uploaded"}), flush=True)
        learn = LearnApi(client)
        info = learn.get_pretrained_model_info(project_id=project)
        check_response_errors(info)
        (output / "uploaded-model-info.json").write_text(info.to_json() + "\n")
        if "int8" not in info.available_model_types:
            raise ValueError("Service did not retain an INT8 model")
        if info.model is None or len(info.model.outputs) != 1 or list(info.model.outputs[0].shape) != [1, 24, 24, 8]:
            raise ValueError("Uploaded output shape differs from frozen prefix")
        response = learn.save_pretrained_model_parameters(
            project_id=project, save_pretrained_model_request=freeform_parameters())
        check_response_errors(response)
        print(json.dumps({"event": "freeform_configured"}), flush=True)
        artifact = build(deploy_model_type="int8", engine="tflite-eon",
                         deploy_target="zip", api_key=key, timeout_sec=600)
        target = output / "eon-prefix.zip"
        target.write_bytes(artifact.getvalue())
    report = inspect_archive(target)
    report.update({"project_id": project, "engine_requested": "tflite-eon",
                   "model_sha256": manifest["models"]["prefix"]["sha256"],
                   "edgeimpulse_version": importlib.metadata.version("edgeimpulse"),
                   "edgeimpulse_api_version": importlib.metadata.version("edgeimpulse-api")})
    (output / "export-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=HERE / "artifacts")
    parser.add_argument("--output", type=Path, default=HERE / "exports/first")
    parser.add_argument("--api-key-file", type=Path, default=Path("/tmp/sciot-eon-api-key"))
    parser.add_argument("--check", action="store_true", help="Validate artifacts and SDK parameters without network")
    args = parser.parse_args()
    verify_preparation(args.prepared)
    check_sdk()
    params = freeform_parameters().to_dict()
    if params != {"input": {"inputType": "other"}, "model": {"modelType": "freeform"}}:
        raise ValueError("SDK did not preserve freeform configuration")
    if args.check:
        print(json.dumps({"status": "offline_checks_passed", "parameters": params}))
        return
    if not args.api_key_file.is_file():
        parser.error("Missing project API key file; save it locally, not in chat or Git")
    key = args.api_key_file.read_text().strip()
    if not key or any(c.isspace() for c in key):
        parser.error("API key file must contain one key")
    try:
        report = export(args.prepared, args.output, key)
    except Exception as error:
        # Never print str(ApiException): it contains session-cookie headers.
        # The service error body is useful for permission diagnostics.
        if hasattr(error, "headers"):
            message = getattr(error, "body", None) or type(error).__name__
        else:
            message = str(error)
        message = str(message).replace(key, "[REDACTED]")
        failure = {"status": "export_failed", "failure_kind": failure_kind(message),
                   "error_type": type(error).__name__,
                   "http_status": getattr(error, "status", None), "message": message[:1000]}
        # Retain the exact service reason without overwriting prior run evidence.
        if args.output.is_dir() and not (args.output / "error-report.json").exists():
            with (args.output / "error-report.json").open("x") as stream:
                json.dump(failure, stream, indent=2)
                stream.write("\n")
        print(json.dumps(failure))
        raise SystemExit(1) from None
    print(json.dumps({"status": "export_downloaded_not_validated", "sha256": report["export_sha256"]}))


if __name__ == "__main__":
    main()
