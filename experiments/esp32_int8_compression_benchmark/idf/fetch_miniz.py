"""Fetch immutable upstream miniz sources; build just its zlib-compatible codec."""
from pathlib import Path
import subprocess

COMMIT='293d4db1b7d0ffee9756d035b9ac6f7431ef8492'
here=Path(__file__).resolve().parent
path=here/'vendor/miniz'
path.parent.mkdir(parents=True,exist_ok=True)
if not path.exists():
    subprocess.run(['git','clone','--no-checkout','--filter=blob:none','https://github.com/richgel999/miniz.git',str(path)],check=True)
    subprocess.run(['git','-C',str(path),'checkout','--detach',COMMIT],check=True)
if subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()!=COMMIT:
    raise ValueError('Unexpected miniz revision')
# Keep upstream unchanged: place our IDF adapter in a separate wrapper component.
wrapper=here/'components/miniz_idf'
wrapper.mkdir(exist_ok=True)
(wrapper/'miniz_export.h').write_text('#pragma once\n#define MINIZ_EXPORT\n')
(wrapper/'sciot_miniz.h').write_text('#pragma once\n#include "../../vendor/miniz/miniz.h"\n')
(wrapper/'CMakeLists.txt').write_text('''idf_component_register(
    SRCS "../../vendor/miniz/miniz.c" "../../vendor/miniz/miniz_tdef.c" "../../vendor/miniz/miniz_tinfl.c"
    INCLUDE_DIRS "." "../../vendor/miniz")
target_compile_definitions(${COMPONENT_LIB} PUBLIC MINIZ_NO_ARCHIVE_APIS MINIZ_NO_STDIO MINIZ_NO_TIME MINIZ_NO_ZLIB_COMPATIBLE_NAMES)
''')
print('miniz',COMMIT)
