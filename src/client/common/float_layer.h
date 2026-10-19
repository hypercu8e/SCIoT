#ifndef SCIOT_FLOAT_LAYER_H
#define SCIOT_FLOAT_LAYER_H

#include <cstddef>
#include <cstdint>
#include <cstring>

#include "tensorflow/lite/micro/micro_interpreter.h"

namespace sciot {

enum class LayerError {
  Ok, InvalidArgument, SchemaMismatch, AllocationFailed, UnsupportedInputs,
  InvalidInput, InvalidResidual, InvalidOutput, InvokeFailed
};

inline const char* layerErrorText(LayerError error) {
  switch (error) {
    case LayerError::Ok: return "ok";
    case LayerError::InvalidArgument: return "invalid layer arguments";
    case LayerError::SchemaMismatch: return "model schema mismatch";
    case LayerError::AllocationFailed: return "AllocateTensors failed";
    case LayerError::UnsupportedInputs: return "unsupported input/output count";
    case LayerError::InvalidInput: return "invalid float32 input size/type";
    case LayerError::InvalidResidual: return "invalid FOMO residual size/type";
    case LayerError::InvalidOutput: return "invalid float32 output size/type";
    case LayerError::InvokeFailed: return "Invoke failed";
  }
  return "unknown layer error";
}

inline bool validFloatTensor(const TfLiteTensor* tensor, size_t bytes) {
  return tensor && tensor->type == kTfLiteFloat32 && tensor->data.f &&
         bytes != 0 && bytes % sizeof(float) == 0 && tensor->bytes == bytes;
}

// One interpreter owns the arena at a time. No tensor or interpreter pointer
// escapes: copy the output to the external working buffer before destruction.
// The caller owns the resolver, model and arena for this entire call.
inline LayerError runFloatLayer(
    const tflite::Model* model, const tflite::MicroOpResolver& resolver,
    uint8_t* arena, size_t arenaBytes, tflite::ErrorReporter* reporter,
    float* work, size_t inputBytes, size_t workCapacityBytes,
    const float* residual, size_t residualBytes, size_t& outputBytes,
    void (*feedWatchdog)() = nullptr) {
  outputBytes = 0;
  if (!model || !arena || !reporter || !work || !arenaBytes ||
      reinterpret_cast<uintptr_t>(arena) % 16 != 0 || inputBytes == 0 ||
      inputBytes > workCapacityBytes || inputBytes % sizeof(float) != 0) return LayerError::InvalidArgument;
  if (model->version() != TFLITE_SCHEMA_VERSION) return LayerError::SchemaMismatch;
  // This runtime's arena-taking constructor dereferences Create() unchecked.
  // Check the allocator explicitly so an undersized arena is a recoverable error.
  tflite::MicroAllocator* allocator = tflite::MicroAllocator::Create(arena, arenaBytes, reporter);
  if (!allocator) return LayerError::AllocationFailed;
  tflite::MicroInterpreter interpreter(model, resolver, allocator, reporter);
  if (interpreter.AllocateTensors() != kTfLiteOk) return LayerError::AllocationFailed;
  if ((interpreter.inputs_size() != 1 && interpreter.inputs_size() != 2) ||
      interpreter.outputs_size() != 1) return LayerError::UnsupportedInputs;
  TfLiteTensor* input = interpreter.input(0);
  if (!validFloatTensor(input, inputBytes)) return LayerError::InvalidInput;
  TfLiteTensor* second = nullptr;
  if (interpreter.inputs_size() == 2) {
    second = interpreter.input(1);
    if (!residual || !validFloatTensor(second, residualBytes)) return LayerError::InvalidResidual;
  }
  TfLiteTensor* output = interpreter.output(0);
  if (!output || !validFloatTensor(output, output->bytes) ||
      output->bytes > workCapacityBytes) return LayerError::InvalidOutput;
  std::memcpy(input->data.f, work, inputBytes);
  if (second) std::memcpy(second->data.f, residual, residualBytes);
  if (feedWatchdog) feedWatchdog();
  const TfLiteStatus status = interpreter.Invoke();
  if (feedWatchdog) feedWatchdog();
  if (status != kTfLiteOk) return LayerError::InvokeFailed;
  std::memcpy(work, output->data.f, output->bytes);
  outputBytes = output->bytes;
  return LayerError::Ok;
}

}  // namespace sciot
#endif
