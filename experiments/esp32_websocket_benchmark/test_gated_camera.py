"""Exercise the actual C++ framebuffer owner against a strict fake camera.

This checks lifecycle failures, not sensor behavior or electrical recovery.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).parent / 'idf/src'


class GatedCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        (root / 'esp_err.h').write_text('#pragma once\n')
        (root / 'esp_timer.h').write_text('#pragma once\n#include <cstdint>\nint64_t esp_timer_get_time();\n')
        (root / 'esp_camera.h').write_text('''#pragma once
#include <cstdint>
#include <cstddef>
#include <sys/time.h>
enum pixformat_t { PIXFORMAT_RGB565 };
struct camera_fb_t { uint8_t* buf; size_t len,width,height; pixformat_t format; timeval timestamp; };
camera_fb_t* esp_camera_fb_get();
void esp_camera_fb_return(camera_fb_t*);
''')
        (root / 'harness.cpp').write_text(r'''
#include "gated_camera.h"
#include <cassert>
#include <cstring>
bool clockOn=true,owned=false;
int gets=0,returns=0,scenario=0;
int64_t now=1000000;
uint8_t pixels[96*96*2]={};
camera_fb_t frame={pixels,sizeof(pixels),96,96,PIXFORMAT_RGB565,{0,0}};
int64_t esp_timer_get_time(){return now;}
namespace xclk_probe {
bool clock(bool enabled,unsigned){
  // Gating a successful capture must retain the sole buffer throughout.
  if(!(scenario==4 && gets==2))assert(owned);
  clockOn=enabled;now+=200000;return true;
}
}
camera_fb_t* esp_camera_fb_get(){
  assert(clockOn && !owned);++gets;now+=40000;
  if(scenario==4 && gets==2)return nullptr;
  owned=true;
  frame.timestamp={long(now/1000000),long(now%1000000)};
  if(scenario==2 && gets==2)frame.timestamp={0,1};
  if(scenario==3 && gets==3)frame.len=sizeof(pixels)-2;
  return &frame;
}
void esp_camera_fb_return(camera_fb_t* fb){
  // Returning a gated buffer would allow a partial capture at next resume.
  assert(clockOn && owned && fb==&frame);owned=false;++returns;
}
int main(int argc,char** argv){
  scenario=argv[1][0]-'0';
  assert(gated_camera::park());assert(!clockOn && owned);
  if(scenario==1){pixels[12]^=1;assert(!gated_camera::unchanged());
    assert(!gated_camera::acquire(0));assert(gets==1 && returns==0);return 0;}
  auto* fb=gated_camera::acquire(0);
  if(scenario>=2){assert(!fb && !clockOn);return 0;}
  assert(fb==&frame && !clockOn && owned && returns==2 && gets==3);
  assert(gated_camera::unchanged());
  fb=gated_camera::acquire(1);
  assert(fb==&frame && !clockOn && owned && returns==4 && gets==5);
  assert(gated_camera::unchanged());
}
''')
        cls.binary = root / 'test'
        subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-I', str(root), '-I', str(SOURCE),
                        str(SOURCE / 'gated_camera.cpp'), str(root / 'harness.cpp'),
                        '-o', str(cls.binary)], check=True)

    def check_scenario(self, scenario):
        result = subprocess.run([str(self.binary), str(scenario)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repeated_resume_keeps_buffer_owned_while_clock_off(self):
        self.check_scenario(0)

    def test_modified_held_buffer_prevents_resume(self):
        self.check_scenario(1)

    def test_pre_resume_frame_is_rejected(self):
        self.check_scenario(2)

    def test_truncated_frame_is_rejected(self):
        self.check_scenario(3)

    def test_capture_timeout_turns_clock_off(self):
        self.check_scenario(4)


if __name__ == '__main__':
    unittest.main()
