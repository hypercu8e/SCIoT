#ifndef SCIOT_INFERENCE_MESSAGE_H
#define SCIOT_INFERENCE_MESSAGE_H

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace sciot {

// Existing server layout: f64 + 9 text bytes + 4 text bytes + i32 + u32 +
// float32 output values + i32 + float32 per-layer times, all little-endian.
constexpr size_t kInferenceHeaderBytes = 8 + 9 + 4 + 4 + 4 + 4;
constexpr size_t inferenceMessageCapacity(size_t outputValues, size_t layers) {
  return kInferenceHeaderBytes + (outputValues + layers) * 4;
}

inline bool validSplit(int split, size_t layers) {
  return split >= 0 && static_cast<size_t>(split) < layers;
}

namespace detail {
inline void writeU32(uint8_t* destination, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) destination[i] = static_cast<uint8_t>(value >> (8 * i));
}
inline void writeFloats(uint8_t* destination, const float* values, size_t count) {
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
  std::memcpy(destination, values, count * sizeof(float));
#else
  for (size_t i = 0; i < count; ++i) {
    uint32_t bits;
    std::memcpy(&bits, values + i, sizeof(bits));
    writeU32(destination + i * 4, bits);
  }
#endif
}
}  // namespace detail

// Failure leaves destination unchanged and written == 0. Identifiers are text
// spans, not String objects; no terminators are transmitted.
inline bool serializeInferenceResult(
    uint8_t* destination, size_t capacity, double timestamp,
    const char* deviceId, size_t deviceIdBytes, const char* messageId, size_t messageIdBytes,
    int split, size_t maxLayers, const float* output, size_t outputValues,
    const float* times, size_t timeCount, size_t& written) {
  static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
                "SCIoT requires IEEE754 float32");
  static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
                "SCIoT requires IEEE754 float64");
  written = 0;
  if (!destination || !deviceId || !messageId || !output || !times ||
      deviceIdBytes != 9 || messageIdBytes != 4 || !validSplit(split, maxLayers) ||
      timeCount != static_cast<size_t>(split) + 1 || outputValues == 0 ||
      outputValues > UINT32_MAX / 4 || timeCount > INT32_MAX / 4 ||
      std::memchr(deviceId, '\0', deviceIdBytes) || std::memchr(messageId, '\0', messageIdBytes)) return false;
  const size_t outputBytes = outputValues * 4;
  const size_t timeBytes = timeCount * 4;
  // Subtraction checks also prevent size_t overflow on the 32-bit target.
  if (capacity < kInferenceHeaderBytes || outputBytes > capacity - kInferenceHeaderBytes ||
      timeBytes > capacity - kInferenceHeaderBytes - outputBytes) return false;
  uint64_t timestampBits;
  std::memcpy(&timestampBits, &timestamp, sizeof(timestampBits));
  for (unsigned i = 0; i < 8; ++i) destination[i] = static_cast<uint8_t>(timestampBits >> (8 * i));
  std::memcpy(destination + 8, deviceId, 9);
  std::memcpy(destination + 17, messageId, 4);
  detail::writeU32(destination + 21, static_cast<uint32_t>(split));
  detail::writeU32(destination + 25, static_cast<uint32_t>(outputBytes));
  detail::writeFloats(destination + 29, output, outputValues);
  detail::writeU32(destination + 29 + outputBytes, static_cast<uint32_t>(timeBytes));
  detail::writeFloats(destination + kInferenceHeaderBytes + outputBytes, times, timeCount);
  written = kInferenceHeaderBytes + outputBytes + timeBytes;
  return true;
}

}  // namespace sciot
#endif
