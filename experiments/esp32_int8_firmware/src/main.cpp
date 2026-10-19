// Isolated INT8 probe. Fixed, prequantized inputs exclude camera preprocessing.
#include <Arduino.h>
#include <algorithm>
#include <cstring>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "generated/assets.h"

namespace {
constexpr int kWarmup = 2;
constexpr int kRuns = 10;
tflite::MicroErrorReporter reporter;
tflite::MicroMutableOpResolver<5> resolver;
tflite::MicroInterpreter* runtime = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;
uint8_t* arena = nullptr;
bool ready = false;

void failure(const char* reason) {
  Serial.printf("{\"event\":\"error\",\"stage\":\"%s\",\"reason\":\"%s\"}\n", kStage, reason);
}

void memory(const char* phase) {
  const uint32_t internal = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  const uint32_t external = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
  Serial.printf("{\"event\":\"memory\",\"phase\":\"%s\","
                "\"internal_free\":%u,\"internal_min_free\":%u,\"internal_largest_free\":%u,"
                "\"psram_free\":%u,\"psram_min_free\":%u,\"psram_largest_free\":%u}\n",
                phase, (unsigned)heap_caps_get_free_size(internal),
                (unsigned)heap_caps_get_minimum_free_size(internal),
                (unsigned)heap_caps_get_largest_free_block(internal),
                (unsigned)heap_caps_get_free_size(external),
                (unsigned)heap_caps_get_minimum_free_size(external),
                (unsigned)heap_caps_get_largest_free_block(external));
}

bool matchesSpec(const TfLiteTensor* tensor, int bytes, float scale, int zero,
                 const int* shape, size_t dims) {
  if (!tensor || tensor->type != kTfLiteInt8 || tensor->bytes != (size_t)bytes ||
      tensor->params.scale != scale || tensor->params.zero_point != zero ||
      !tensor->dims || tensor->dims->size != (int)dims) return false;
  for (size_t i = 0; i < dims; ++i) if (tensor->dims->data[i] != shape[i]) return false;
  return true;
}

void runCases() {
  if (!ready) return;
  for (int test = 0; test < kCases; ++test) {
    memcpy(input->data.int8, kInputCases[test], kInputBytes);
    for (int i = 0; i < kWarmup; ++i) {
      if (runtime->Invoke() != kTfLiteOk) { failure("warmup_invoke_failed"); return; }
    }
    int64_t times[kRuns];
    int mismatches = 0, maxError = 0;
    for (int run = 0; run < kRuns; ++run) {
      const int64_t start = esp_timer_get_time();
      const TfLiteStatus status = runtime->Invoke();
      times[run] = esp_timer_get_time() - start;
      if (status != kTfLiteOk) { failure("invoke_failed"); return; }
      // Verify every run; comparison and serial output are outside the timer.
      int currentMismatch = 0;
      for (int j = 0; j < kOutputBytes; ++j) {
        const int expected = (int)(int8_t)kOutputCases[test][j];
        const int delta = abs((int)output->data.int8[j] - expected);
        if (delta) ++currentMismatch;
        maxError = std::max(maxError, delta);
      }
      mismatches = std::max(mismatches, currentMismatch);
    }
    std::sort(times, times + kRuns);
    // p50 uses the arithmetic mean of the two middle observations.
    const double p50 = (times[kRuns / 2 - 1] + times[kRuns / 2]) / 2.0;
    Serial.printf("{\"event\":\"case\",\"stage\":\"%s\",\"frame_index\":%d,"
                  "\"warmups\":%d,\"runs\":%d,\"invoke_min_us\":%lld,\"invoke_p50_us\":%.1f,"
                  "\"invoke_max_us\":%lld,\"max_mismatched_values_per_run\":%d,"
                  "\"max_abs_error_integer_steps\":%d,\"exact_match_all_runs\":%s,\"output_hex\":\"",
                  kStage, kFrameIndices[test], kWarmup, kRuns, times[0], p50, times[kRuns - 1],
                  mismatches, maxError, mismatches == 0 ? "true" : "false");
    // Retain the actual final output for independent desktop comparison.
    const char hex[] = "0123456789abcdef";
    for (int j = 0; j < kOutputBytes; ++j) {
      const uint8_t value = (uint8_t)output->data.int8[j];
      Serial.write(hex[value >> 4]); Serial.write(hex[value & 15]);
    }
    Serial.println("\"}");
    memory("after_case");
    delay(1);
  }
  Serial.printf("{\"event\":\"done\",\"stage\":\"%s\",\"cases\":%d}\n", kStage, kCases);
}
}  // namespace

void setup() {
  Serial.begin(115200);
  const uint32_t start = millis();
  while (!Serial && millis() - start < 10000) delay(10);
  delay(500);
  Serial.printf("{\"event\":\"boot\",\"stage\":\"%s\",\"model_sha256\":\"%s\","
                "\"vectors_sha256\":\"%s\",\"model_bytes\":%u,\"cpu_mhz\":%u,"
                "\"psram_bytes\":%u,\"sdk\":\"%s\",\"runtime\":\"TensorFlowLite_ESP32@1.0.0\","
                "\"arena_capacity_bytes\":%u,\"arena_in_psram\":%s,\"esp_nn_enabled\":false}\n",
                kStage, kModelSha256, kVectorsSha256, (unsigned)sizeof(kModel),
                (unsigned)ESP.getCpuFreqMHz(), (unsigned)ESP.getPsramSize(), ESP.getSdkVersion(),
                (unsigned)ARENA_BYTES, ARENA_IN_PSRAM ? "true" : "false");
  memory("before_arena");
  const uint32_t caps = MALLOC_CAP_8BIT | (ARENA_IN_PSRAM ? MALLOC_CAP_SPIRAM : MALLOC_CAP_INTERNAL);
  arena = (uint8_t*)heap_caps_aligned_alloc(16, ARENA_BYTES, caps);
  if (!arena) { failure("arena_allocation_failed"); return; }
  const tflite::Model* model = tflite::GetModel(kModel);
  if (model->version() != TFLITE_SCHEMA_VERSION) { failure("schema_version_mismatch"); return; }
  if (resolver.AddAdd() != kTfLiteOk || resolver.AddConv2D() != kTfLiteOk ||
      resolver.AddDepthwiseConv2D() != kTfLiteOk || resolver.AddPad() != kTfLiteOk ||
      resolver.AddSoftmax() != kTfLiteOk) { failure("resolver_registration_failed"); return; }
  // All referenced objects have program lifetime, including the resolver.
  static tflite::MicroInterpreter instance(model, resolver, arena, ARENA_BYTES, &reporter);
  runtime = &instance;
  if (runtime->AllocateTensors() != kTfLiteOk) { failure("allocate_tensors_failed"); return; }
  input = runtime->input(0); output = runtime->output(0);
  if (!matchesSpec(input, kInputBytes, kInputScale, kInputZero, kInputShape,
                   sizeof(kInputShape) / sizeof(int)) ||
      !matchesSpec(output, kOutputBytes, kOutputScale, kOutputZero, kOutputShape,
                   sizeof(kOutputShape) / sizeof(int))) { failure("io_spec_mismatch"); return; }
  Serial.printf("{\"event\":\"allocated\",\"arena_used_bytes\":%u,\"input_bytes\":%d,\"output_bytes\":%d}\n",
                (unsigned)runtime->arena_used_bytes(), kInputBytes, kOutputBytes);
  memory("after_allocate_tensors");
  ready = true;
  runCases();
}

void loop() {
  if (Serial.available() && Serial.read() == 'r') {
    // A full reboot repeats boot/allocation evidence as well as the cases.
    Serial.flush(); ESP.restart();
  }
  delay(10);
}
