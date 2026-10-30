import hashlib
import json
from pathlib import Path
import unittest
import zlib

import numpy as np
from server.multiclient.engine import Suffix
from server.multiclient.protocol import HEADER, REQUEST_MAGIC, RESPONSE_MAGIC

ARTIFACTS=Path('experiments/esp32_representation_benchmark/artifacts')


class EngineTests(unittest.TestCase):
    def test_frozen_suffix_exact_and_fomo_decoder_matches(self):
        import tensorflow as tf
        from server.multiclient.fomo import decode
        import importlib.util
        spec=importlib.util.spec_from_file_location('reference_fomo',ARTIFACTS.parent/'fomo_quality.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        engine=Suffix(ARTIFACTS)
        direct=tf.lite.Interpreter(model_content=(ARTIFACTS/'int8-suffix.tflite').read_bytes(),num_threads=1,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        direct.allocate_tensors(); inp=direct.get_input_details()[0];out=direct.get_output_details()[0]
        for value in (-128,0,127):
            activation=np.full((1,24,24,8),value,dtype=np.int8)
            data=activation.tobytes()
            reply=engine(HEADER.pack(REQUEST_MAGIC,1,1,42,3,0,4608,zlib.crc32(data))+data)
            self.assertEqual(HEADER.unpack_from(reply)[:5],(RESPONSE_MAGIC,1,42,3,432))
            direct.set_tensor(inp['index'],activation);direct.invoke()
            scores=(direct.get_tensor(out['index']).astype(np.float32)-out['quantization'][1])*out['quantization'][0]
            self.assertEqual(reply[32:],scores.astype('<f4').tobytes())
            self.assertEqual(decode(scores),module.decode(scores))
