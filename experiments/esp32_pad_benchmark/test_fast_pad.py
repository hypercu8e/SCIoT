"""Compile and run the host comparison of fastPadHW with the TFLM reference."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
TFLM=HERE/'idf/components/esp-tflite-micro'

class FastPad(unittest.TestCase):
    @unittest.skipUnless(TFLM.is_dir(),'copy the frozen components into idf/components first')
    def test_matches_reference_kernel(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'host_fast_pad'
            subprocess.run(['g++','-std=c++17','-O2','-Wall','-I',str(TFLM),'-I',str(HERE/'idf/src'),
                            str(HERE/'host_fast_pad.cpp'),'-o',str(binary)],check=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(result.stdout.startswith('OK 2001 cases'),result.stdout)

if __name__=='__main__':unittest.main()
