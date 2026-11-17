#pragma once
#include <cstddef>
#include <cstdint>
#include "tensorflow/lite/micro/micro_common.h"

extern bool sciotKernelTiming;
extern uint32_t sciotConvCalls, sciotDepthwiseCalls;
extern int64_t sciotConvUs, sciotDepthwiseUs;

// Fast PAD instrumentation. In check mode the TFLM reference also runs into
// the scratch buffer and every output byte is compared (never during timing).
extern bool sciotPadCheck;
extern int8_t* sciotPadScratch;
extern size_t sciotPadScratchBytes;
extern uint32_t sciotFastPadCalls, sciotPadChecks, sciotPadMismatchBytes, sciotPadComparedBytes;

TFLMRegistration RegisterFastPad();
