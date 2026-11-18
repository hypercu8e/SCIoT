#pragma once
#include <cstdint>
#include "esp_camera.h"

// Experimental, single-buffer RGB565 96x96 camera only. Keep ownership of the
// completed framebuffer across network traffic; never stop DMA mid-frame.
namespace gated_camera {
bool park();
camera_fb_t* acquire(unsigned index);
bool unchanged();
uint32_t checksum();
}
