#include "gated_camera.h"
#include "xclk_probe.h"
#include "esp_timer.h"
#include <cstdio>

namespace gated_camera {
namespace {
camera_fb_t* held=nullptr;
uint32_t digest=0;
int64_t previousTimestamp=-1;
bool parked=false;
bool valid(const camera_fb_t* fb) {
  return fb && fb->buf && fb->len==96*96*2 && fb->width==96 &&
    fb->height==96 && fb->format==PIXFORMAT_RGB565;
}
int64_t timestamp(const camera_fb_t* fb) {
  return int64_t(fb->timestamp.tv_sec)*1000000+fb->timestamp.tv_usec;
}
uint32_t hash(const camera_fb_t* fb) {
  uint32_t h=2166136261u;
  for(size_t i=0;i<fb->len;++i)h=(h^fb->buf[i])*16777619u;
  return h;
}
bool stop(unsigned phase) {
  // Call only after fb_get has transferred the sole completed buffer to us.
  // The driver cannot start another capture until we return it.
  parked=xclk_probe::clock(false,phase);
  return parked;
}
}

bool park() {
  if(held)return false;
  held=esp_camera_fb_get();
  if(!held)return false;
  // Even an invalid frame remains owned: abort without restarting capture.
  if(!stop(0) || !valid(held))return false;
  digest=hash(held);previousTimestamp=timestamp(held);
  return true;
}

bool unchanged() {return parked && valid(held) && hash(held)==digest;}
uint32_t checksum() {return digest;}

camera_fb_t* acquire(unsigned index) {
  if(!unchanged())return nullptr;
  const int64_t resumed=esp_timer_get_time();
  parked=false;
  if(!xclk_probe::clock(true,2*index+1)){
    stop(2*index+2);return nullptr;
  }
  // clock() waits 200 ms with the old framebuffer still owned. Sensor settling
  // is a hypothesis to validate on hardware, not an optical-quality guarantee.
  esp_camera_fb_return(held);held=nullptr;
  // Discard one *complete fresh* frame after the pause; do not accept a queued
  // pre-pause frame, a truncated frame or a repeated driver timestamp.
  for(unsigned pass=0;pass<2;++pass){
    held=esp_camera_fb_get();
    if(!valid(held) || timestamp(held)<resumed || timestamp(held)<=previousTimestamp){
      if(held)stop(2*index+2);
      else xclk_probe::clock(false,2*index+2);
      return nullptr;
    }
    previousTimestamp=timestamp(held);
    if(pass==0){esp_camera_fb_return(held);held=nullptr;}
  }
  digest=hash(held);
  if(!stop(2*index+2) || !unchanged())return nullptr;
  printf("{\"event\":\"camera_gate_frame\",\"index\":%u,\"resume_us\":%lld,\"frame_timestamp_us\":%lld,\"frame_hash\":%u,\"settling_frames_discarded\":1,\"xclk_enabled\":false,\"buffer_retained\":true}\n",
    index,static_cast<long long>(resumed),static_cast<long long>(previousTimestamp),unsigned(digest));
  return held;
}
}
