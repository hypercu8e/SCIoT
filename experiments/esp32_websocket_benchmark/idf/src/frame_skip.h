#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace frame_skip {
constexpr int side = 96;
constexpr int pixels = side * side;
constexpr int tile = 8;

enum class Mode { Baseline, Shadow, Active };
enum class Metric { Global, Local };
enum class Reason { Baseline, First, Change, Refresh, Similar };

struct Config {
  Mode mode = Mode::Baseline;
  Metric metric = Metric::Global;
  int threshold = 1;
  int refreshMs = 1500;
};

struct Decision {
  Reason reason;
  int difference;
  int64_t ageUs;

  bool selected() const { return reason != Reason::Similar; }
};

inline int difference(const int8_t* image, const int8_t* reference, Metric metric) {
  if (metric == Metric::Global) {
    int sum = 0;
    for (int i = 0; i < pixels; ++i) sum += std::abs(int(image[i]) - reference[i]);
    return sum / pixels;
  }
  // Sum in row order for sequential reads from the PSRAM reference.
  int maximum = 0;
  for (int y = 0; y < side; y += tile) {
    int sums[side / tile] = {};
    for (int row = y; row < y + tile; ++row) {
      for (int col = 0; col < side; ++col) {
        const int index = row * side + col;
        sums[col / tile] += std::abs(int(image[index]) - reference[index]);
      }
    }
    maximum = std::max(maximum, *std::max_element(sums, sums + side / tile));
  }
  // Integer division preserves comparisons against integer thresholds.
  return maximum / (tile * tile);
}

class Policy {
 public:
  Policy(Config config, int8_t* storage) : config_(config), reference_(storage),
      pending_(storage ? storage + pixels : nullptr) {}

  Decision decide(const int8_t* image, int64_t captureUs) const {
    if (config_.mode == Mode::Baseline) return {Reason::Baseline, -1, -1};
    if (referenceUs_ < 0) return {Reason::First, -1, -1};
    const auto age = captureUs - referenceUs_;
    const auto value = difference(image, reference_, config_.metric);
    if (value >= config_.threshold) return {Reason::Change, value, age};
    if (age >= int64_t(config_.refreshMs) * 1000) return {Reason::Refresh, value, age};
    return {Reason::Similar, value, age};
  }

  void stage(const int8_t* image) { std::memcpy(pending_, image, pixels); }

  void acknowledge(int64_t captureUs, int frame) {
    std::swap(reference_, pending_);
    referenceUs_ = captureUs;
    referenceFrame_ = frame;
  }

  int referenceFrame() const { return referenceFrame_; }

 private:
  Config config_;
  int8_t* reference_;
  int8_t* pending_;
  int64_t referenceUs_ = -1;
  int referenceFrame_ = -1;
};
}
