#pragma once
#include "esp_err.h"

// Diagnostic only. Ping sessions and result storage are allocated before the
// camera and retained across all phases. No HTTP traffic or clock-rate changes.
namespace xclk_probe {
constexpr unsigned kCount = 50;
bool init(const char* serverBaseUrl);
bool phase(unsigned index, const char* name, bool cameraInitialized, bool clockEnabled);
bool clock(bool enabled, unsigned phaseIndex);
void close();
}
