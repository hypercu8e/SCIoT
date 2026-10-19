// Execute the production helpers with real TFLite Micro on the host CPU.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include "float_layer.h"
#include "inference_message.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"

namespace {
constexpr size_t kValues = 49 * 49 * 48;
constexpr size_t kCapacity = kValues * sizeof(float);
constexpr size_t kArenaBytes = 1000 * 1024;
alignas(16) uint8_t arena[kArenaBytes];
tflite::MicroErrorReporter reporter;
int watchdogCalls = 0;
void watchdog() { ++watchdogCalls; }
TfLiteStatus failInvoke(TfLiteContext*, TfLiteNode*) { return kTfLiteError; }

template <typename T> std::vector<T> read(const std::string& path) {
  std::ifstream file(path, std::ios::binary | std::ios::ate);
  assert(file.good());
  const size_t bytes = static_cast<size_t>(file.tellg());
  assert(bytes % sizeof(T) == 0);
  std::vector<T> result(bytes / sizeof(T));
  file.seekg(0); file.read(reinterpret_cast<char*>(result.data()), bytes);
  assert(file.good());
  return result;
}
void write(const std::string& path, const uint8_t* bytes, size_t length) {
  std::ofstream file(path, std::ios::binary);
  file.write(reinterpret_cast<const char*>(bytes), length);
  assert(file.good());
}

void messageChecks(const std::string& fixtures) {
  static_assert(sciot::inferenceMessageCapacity(kValues, 59) == 461261, "capacity changed");
  std::vector<float> output(kValues), times(59);
  for (size_t i = 0; i < output.size(); ++i) output[i] = (static_cast<int>(i % 257) - 128) / 32.0f;
  for (size_t i = 0; i < times.size(); ++i) times[i] = (i + 1) / 1024.0f;
  size_t written = 999;
  for (int split : {0, 11, 25, 58}) {
    const size_t values = (split == 11 || split == 58) ? kValues : 12;
    const size_t size = sciot::inferenceMessageCapacity(values, split + 1);
    std::vector<uint8_t> packet(size + 2, 0xcd);
    assert(sciot::serializeInferenceResult(packet.data() + 1, size, 1234567890.125,
      "device_01", 9, "a1b2", 4, split, 59, output.data(), values, times.data(), split + 1, written));
    assert(written == size && packet.front() == 0xcd && packet.back() == 0xcd);
    write(fixtures + "/packet_" + std::to_string(split) + ".bin", packet.data() + 1, written);
    const auto before = packet;
    assert(!sciot::serializeInferenceResult(packet.data() + 1, size - 1, 0,
      "device_01", 9, "a1b2", 4, split, 59, output.data(), values, times.data(), split + 1, written));
    assert(written == 0 && packet == before);
  }
  std::vector<uint8_t> packet(256, 0xcd);
  const auto before = packet;
  for (int split : {-1, 59}) {
    assert(!sciot::serializeInferenceResult(packet.data(), packet.size(), 0,
      "device_01", 9, "a1b2", 4, split, 59, output.data(), 12, times.data(), 1, written));
    assert(written == 0 && packet == before);
  }
  assert(!sciot::serializeInferenceResult(packet.data(), packet.size(), 0,
    "short", 5, "a1b2", 4, 0, 59, output.data(), 12, times.data(), 1, written));
  assert(!sciot::serializeInferenceResult(packet.data(), packet.size(), 0,
    "device_01", 9, "", 0, 0, 59, output.data(), 12, times.data(), 1, written));
  assert(!sciot::serializeInferenceResult(packet.data(), packet.size(), 0,
    "device_01", 9, "a1b2", 4, 0, 59, output.data(), 12, times.data(), 59, written));
  assert(!sciot::serializeInferenceResult(packet.data(), packet.size(), 0,
    "device_01", 9, "a1b2", 4, 0, 59, output.data(), SIZE_MAX, times.data(), 1, written));
  assert(!sciot::serializeInferenceResult(nullptr, 256, 0,
    "device_01", 9, "a1b2", 4, 0, 59, output.data(), 12, times.data(), 1, written));
  assert(packet == before && written == 0);
}
}  // namespace

int main(int argc, char** argv) {
  assert(argc == 3);
  const std::string models = argv[1], fixtures = argv[2];
  messageChecks(fixtures);
  tflite::MicroMutableOpResolver<8> resolver;
  assert(resolver.AddAdd() == kTfLiteOk);
  assert(resolver.AddMul() == kTfLiteOk);
  assert(resolver.AddConv2D() == kTfLiteOk);
  assert(resolver.AddDepthwiseConv2D() == kTfLiteOk);
  assert(resolver.AddPad() == kTfLiteOk);
  assert(resolver.AddSoftmax() == kTfLiteOk);
  assert(resolver.AddRelu6() == kTfLiteOk);
  TfLiteRegistration failed = {};
  failed.invoke = failInvoke;
  assert(resolver.AddCustom("SCIoTFail", &failed) == kTfLiteOk);
  std::vector<std::vector<uint8_t>> binaries;
  for (int layer = 0; layer < 59; ++layer) binaries.push_back(read<uint8_t>(models + "/submodel_" + std::to_string(layer) + ".tflite"));
  std::vector<float> work(kValues, -99), residual(kValues, 0);
  size_t bytes = 0;
  const auto* first = tflite::GetModel(binaries[0].data());
  auto run = [&](const tflite::Model* model, size_t inputBytes, size_t capacity, const float* skip, size_t skipBytes) {
    return sciot::runFloatLayer(model, resolver, arena, sizeof(arena), &reporter,
        work.data(), inputBytes, capacity, skip, skipBytes, bytes, watchdog);
  };
  assert(run(nullptr, 96 * 96 * 3 * 4, kCapacity, nullptr, 0) == sciot::LayerError::InvalidArgument);
  assert(bytes == 0);
  assert(run(first, 96 * 96 * 3 * 4 - 4, kCapacity, nullptr, 0) == sciot::LayerError::InvalidInput);
  assert(bytes == 0 && work[0] == -99);
  assert(run(first, 96 * 96 * 3 * 4, 96 * 96 * 3 * 4, nullptr, 0) == sciot::LayerError::InvalidOutput);
  assert(bytes == 0 && work[0] == -99);
  const auto* add = tflite::GetModel(binaries[25].data());
  assert(run(add, 24 * 24 * 8 * 4, kCapacity, nullptr, 0) == sciot::LayerError::InvalidResidual);
  assert(run(add, 24 * 24 * 8 * 4, kCapacity, residual.data(), 4) == sciot::LayerError::InvalidResidual);
  assert(bytes == 0 && work[0] == -99);
  auto badSchema = read<uint8_t>(fixtures + "/bad_schema.tflite");
  assert(run(tflite::GetModel(badSchema.data()), 4, kCapacity, nullptr, 0) == sciot::LayerError::SchemaMismatch);
  auto failedModel = read<uint8_t>(fixtures + "/failed_invoke.tflite");
  assert(run(tflite::GetModel(failedModel.data()), 4, kCapacity, nullptr, 0) == sciot::LayerError::InvokeFailed);
  assert(bytes == 0 && work[0] == -99);
  auto int8Input = read<uint8_t>(fixtures + "/int8_input.tflite");
  assert(run(tflite::GetModel(int8Input.data()), 4, kCapacity, nullptr, 0) == sciot::LayerError::InvalidInput);
  auto int8Output = read<uint8_t>(fixtures + "/int8_output.tflite");
  assert(run(tflite::GetModel(int8Output.data()), 4, kCapacity, nullptr, 0) == sciot::LayerError::InvalidOutput);
  assert(sciot::runFloatLayer(first, resolver, arena + 1, sizeof(arena) - 1, &reporter,
    work.data(), 96 * 96 * 3 * 4, kCapacity, nullptr, 0, bytes) == sciot::LayerError::InvalidArgument);
  assert(bytes == 0 && work[0] == -99);
  // Real allocator failure must stop before copying or invoking.
  assert(sciot::runFloatLayer(first, resolver, arena, 256, &reporter, work.data(),
    96 * 96 * 3 * 4, kCapacity, nullptr, 0, bytes) == sciot::LayerError::AllocationFailed);
  assert(bytes == 0 && work[0] == -99);

  double maxError = 0;
  size_t compared = 0;
  int invocations = 0;
  // Repeated full chains force destruction/reconstruction and residual resets.
  // Different split lengths additionally exercise early termination and reuse.
  for (int repeat = 0; repeat < 2; ++repeat) {
    for (int sample = 0; sample < 3; ++sample) {
      for (int split : {0, 11, 25, 43, 52, 58}) {
        auto input = read<float>(fixtures + "/input_" + std::to_string(sample) + ".bin");
        std::copy(input.begin(), input.end(), work.begin());
        size_t inputBytes = input.size() * sizeof(float), residualBytes = 0;
        for (int layer = 0; layer <= split; ++layer) {
          const auto status = run(tflite::GetModel(binaries[layer].data()), inputBytes, kCapacity,
                                  residual.data(), residualBytes);
          if (status != sciot::LayerError::Ok) {
            fprintf(stderr, "layer %d: %s\n", layer, sciot::layerErrorText(status));
            return 2;
          }
          ++invocations;
          auto reference = read<float>(fixtures + "/reference_" + std::to_string(sample) + "_" + std::to_string(layer) + ".bin");
          assert(bytes == reference.size() * sizeof(float));
          for (size_t i = 0; i < reference.size(); ++i) {
            const double error = std::abs(static_cast<double>(work[i]) - reference[i]);
            if (!std::isfinite(work[i]) || error > 1e-5 + 1e-5 * std::abs(reference[i])) {
              fprintf(stderr, "Mismatch repeat=%d sample=%d split=%d layer=%d value=%zu actual=%.9g expected=%.9g error=%.9g\n",
                      repeat, sample, split, layer, i, work[i], reference[i], error);
              return 3;
            }
            maxError = std::max(maxError, error);
          }
          compared += reference.size(); inputBytes = bytes;
          if (layer == 16 || layer == 34 || layer == 43) {
            std::copy(work.begin(), work.begin() + bytes / sizeof(float), residual.begin());
            residualBytes = bytes;
          }
        }
      }
    }
  }
  printf("{\"invocations\":%d,\"compared_float_values\":%zu,\"max_absolute_error\":%.17g,"
         "\"watchdog_calls\":%d,\"checks_passed\":true}\n", invocations, compared, maxError, watchdogCalls);
}
