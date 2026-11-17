"""Explicit, locally verified prefix variants for one frozen suffix."""
import hashlib
import json
from pathlib import Path


def accepted_models(artifacts, registry=None):
    artifacts = Path(artifacts)
    manifest = json.loads((artifacts/'manifest.json').read_text())['models']['int8']
    primary = manifest['prefix']['sha256']
    accepted = {primary}
    if registry is None:
        return accepted
    import numpy as np
    import tensorflow as tf
    registry = Path(registry)
    data = json.loads(registry.read_text())
    if data['suffix_sha256'] != manifest['suffix']['sha256']:
        raise ValueError('Registry suffix mismatch')
    # Validate actual suffix bytes, not just its declared identity.
    suffix = (artifacts/'int8-suffix.tflite').read_bytes()
    if hashlib.sha256(suffix).hexdigest() != data['suffix_sha256']:
        raise ValueError('Suffix hash mismatch')
    expected = manifest['suffix']['input']
    for variant in data['prefixes']:
        blob = (registry.parent/variant['path']).read_bytes()
        actual = hashlib.sha256(blob).hexdigest()
        if actual != variant['sha256']:
            raise ValueError('Prefix hash mismatch')
        runtime = tf.lite.Interpreter(model_content=blob)
        runtime.allocate_tensors()
        detail = runtime.get_output_details()[0]
        quant = detail['quantization_parameters']
        if (detail['shape'].tolist() != expected['shape'] or
            np.dtype(detail['dtype']).name != expected['dtype'] or
            quant['scales'].tolist() != expected['scales'] or
            quant['zero_points'].tolist() != expected['zero_points']):
            raise ValueError('Prefix boundary mismatch')
        accepted.add(actual)
    return accepted
