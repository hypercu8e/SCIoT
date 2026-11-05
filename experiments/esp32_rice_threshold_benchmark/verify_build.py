"""Freeze successful build evidence and verify ESP-NN wrapping in the ELF."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    build=HERE/'idf/.pio/build/threshold';log=(HERE/'results/build.log').read_text()
    if '[SUCCESS]' not in log:raise ValueError('Build log does not show success')
    nm=Path.home()/'.platformio/packages/toolchain-xtensa-esp-elf/bin/xtensa-esp32s3-elf-nm'
    symbols=subprocess.check_output([str(nm),str(build/'firmware.elf')],text=True)
    for s in ('__wrap_esp_nn_conv_s8_esp32s3','__wrap_esp_nn_depthwise_conv_s8_esp32s3'):
        if s not in symbols:raise ValueError('Missing ESP-NN probe wrapper')
    sdk=(HERE/'idf/sdkconfig.threshold').read_text()
    for key in ('CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN=y','CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ=240'):
        if key not in sdk:raise ValueError('Wrong runtime configuration: '+key)
    manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    tests=(HERE/'results/tests.txt').read_text()
    if not tests.rstrip().endswith('OK'):raise ValueError('Tests did not pass')
    data=dict(build='PlatformIO 6.1.18 / espressif32 6.10.0 / ESP-IDF 5.4.0',firmware_sha256=sha(build/'firmware.bin'),elf_sha256=sha(build/'firmware.elf'),native_tests_passed=int(re.search(r'Ran (\d+) tests',tests)[1]),prefix_model_sha256=manifest['models']['int8']['prefix']['sha256'],suffix_model_sha256=manifest['models']['int8']['suffix']['sha256'],video_input_binary_sha256=manifest['video_input_binary_sha256'],camera_xclk_hz=20000000,http_timeout_ms=60000,experiment_sha256=manifest['experiment_sha256'],source_sha256={str(p.relative_to(HERE)):sha(p) for p in [HERE/'idf/src/main.cpp',HERE/'include/codec.h',HERE/'include/legacy_codec.h',HERE/'include/generated/assets.h',HERE/'idf/platformio.ini',HERE/'idf/src/CMakeLists.txt',HERE/'protocol.py',HERE/'server.py',HERE/'run_hardware.py',HERE/'flash_ops.py',HERE/'proxy.py']})
    (HERE/'results/build-verification.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))
if __name__=='__main__':main()
