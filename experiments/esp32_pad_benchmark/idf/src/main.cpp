#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <new>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "tensorflow/lite/kernels/internal/reference/pad.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_profiler_interface.h"
#include "generated/assets.h"
#include "fast_pad.h"
#include "probe.h"

#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error ESP-NN is required
#endif
#if defined(TF_LITE_STRIP_ERROR_STRINGS)
#error TFLM profiling hooks require operator names
#endif

namespace {
constexpr size_t kArenaBytes=1024*1024,kOutputBytes=4608;
constexpr int kFramesCount=3,kRandomInputs=29,kVerifyInputs=kFramesCount+kRandomInputs;
constexpr int kRounds=3,kRepeats=30,kWarmup=5,kMaxEvents=64;
constexpr int kCalibrationWarmup=3,kCalibrationRepeats=30;
// The frozen model's PAD node: 1x48x48x48 -> 1x49x49x48, zero point -128.
constexpr int kPadH=48,kPadW=48,kPadD=48;
constexpr size_t kPadIn=size_t(kPadH)*kPadW*kPadD,kPadOut=size_t(kPadH+1)*(kPadW+1)*kPadD;
enum Variant {kOriginal=0,kFast=1};
const char* const kVariantNames[2]={"original","fast"};

struct Event {
  const char* tag;
  int64_t start,elapsed,convUs,depthUs;
  uint32_t convCalls,depthCalls;
  bool done;
};
class Profiler final:public tflite::MicroProfilerInterface {
 public:
  Event events[kMaxEvents];
  int count=0;
  bool overflow=false;
  uint32_t BeginEvent(const char* tag) override {
    if(count==kMaxEvents) {overflow=true;return UINT32_MAX;}
    const int index=count++;
    auto& e=events[index];e.tag=tag;e.done=false;
    e.convCalls=sciotConvCalls;e.depthCalls=sciotDepthwiseCalls;
    e.convUs=sciotConvUs;e.depthUs=sciotDepthwiseUs;
    e.start=esp_timer_get_time();
    return index;
  }
  void EndEvent(uint32_t handle) override {
    const int64_t end=esp_timer_get_time();
    if(handle>=uint32_t(count)) {overflow=true;return;}
    auto& e=events[handle];e.elapsed=end-e.start;
    e.convCalls=sciotConvCalls-e.convCalls;e.depthCalls=sciotDepthwiseCalls-e.depthCalls;
    e.convUs=sciotConvUs-e.convUs;e.depthUs=sciotDepthwiseUs-e.depthUs;e.done=true;
  }
  void reset() {count=0;overflow=false;}
} profiler;
tflite::MicroMutableOpResolver<5> resolvers[2];
tflite::MicroInterpreter* runtime=nullptr;
alignas(tflite::MicroInterpreter) unsigned char interpreterStorage[sizeof(tflite::MicroInterpreter)];
uint8_t* arena;
int8_t* inputs;      // kVerifyInputs inputs; the first kFramesCount are canonical
int8_t* references;  // original-variant activation for every input
bool goldenReady=false;
const tflite::Model* model;
Variant current=kOriginal;

bool fail(const char* reason) {
  printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);return false;
}
uint32_t fnv(const int8_t* p,size_t n) {
  uint32_t h=2166136261u;while(n--) {h^=uint8_t(*p++);h*=16777619u;}return h;
}
void hex(const int8_t* p,size_t n) {for(size_t i=0;i<n;++i) printf("%02x",uint8_t(p[i]));}
size_t differing(const int8_t* a,const int8_t* b,size_t n) {size_t d=0;for(size_t i=0;i<n;++i) d+=a[i]!=b[i];return d;}
void memory(const char* phase,Variant variant,const char* mode,int round) {
  printf("{\"event\":\"memory\",\"phase\":\"%s\",\"variant\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"internal_free\":%u,\"psram_free\":%u,\"internal_min\":%u}\n",
    phase,kVariantNames[variant],mode,round,unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)));
}
bool create(Variant variant,bool profiled,const char* phase,int round) {
  if(runtime) {runtime->~MicroInterpreter();runtime=nullptr;}
  current=variant;sciotKernelTiming=profiled;profiler.reset();
  runtime=new(interpreterStorage) tflite::MicroInterpreter(model,resolvers[variant],arena,kArenaBytes,nullptr,profiled?&profiler:nullptr);
  if(runtime->AllocateTensors()!=kTfLiteOk) return fail("allocate_tensors");
  if(runtime->input(0)->bytes!=kPixels || runtime->output(0)->bytes!=kOutputBytes) return fail("tensor_shape");
  printf("{\"event\":\"block\",\"phase\":\"%s\",\"variant\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"arena_address\":\"%p\",\"arena_capacity\":%u,\"arena_used\":%u}\n",
    phase,kVariantNames[variant],profiled?"profiled":"plain",round,arena,unsigned(kArenaBytes),unsigned(runtime->arena_used_bytes()));
  return true;
}
// Runs one inference; the timer covers Invoke() only.
bool invokeRaw(const int8_t* input,int64_t& elapsed) {
  memcpy(runtime->input(0)->data.int8,input,kPixels);
  profiler.reset();sciotConvCalls=sciotDepthwiseCalls=0;sciotConvUs=sciotDepthwiseUs=0;sciotFastPadCalls=0;
  const int64_t start=esp_timer_get_time();
  const TfLiteStatus status=runtime->Invoke();
  elapsed=esp_timer_get_time()-start;
  if(status!=kTfLiteOk) return fail("invoke");
  if(sciotConvCalls!=6 || sciotDepthwiseCalls!=3) return fail("optimized_kernel_count");
  if(sciotFastPadCalls!=(current==kFast?1u:0u)) return fail("fast_pad_call_count");
  return true;
}

// Phase 1: reference activations from the original kernel, then the fast kernel
// with the in-kernel full comparison of the PAD tensor against TFLM.
bool verify() {
  int64_t elapsed;
  if(!create(kOriginal,false,"verify",0)) return false;
  for(int i=0;i<kVerifyInputs;++i) {
    if(!invokeRaw(inputs+i*kPixels,elapsed)) return false;
    memcpy(references+i*kOutputBytes,runtime->output(0)->data.int8,kOutputBytes);
    if(i<kFramesCount) {
      printf("{\"event\":\"golden\",\"frame\":%d,\"input_hex\":\"",kFrameIds[i]);hex(inputs+i*kPixels,kPixels);
      printf("\",\"activation_hex\":\"");hex(references+i*kOutputBytes,kOutputBytes);printf("\"}\n");
    }
    vTaskDelay(1);
  }
  goldenReady=true;
  if(!create(kFast,false,"verify",0)) return false;
  sciotPadCheck=true;
  for(int i=0;i<kVerifyInputs;++i) {
    sciotPadChecks=sciotPadMismatchBytes=sciotPadComparedBytes=0;
    if(!invokeRaw(inputs+i*kPixels,elapsed)) {sciotPadCheck=false;return false;}
    const auto* result=runtime->output(0)->data.int8;
    const size_t activationDiff=differing(result,references+i*kOutputBytes,kOutputBytes);
    printf("{\"event\":\"verify\",\"input\":%d,\"frame\":%d,\"pad_checks\":%u,\"pad_compared_bytes\":%u,\"pad_mismatch_bytes\":%u,\"activation_bytes\":%u,\"activation_mismatch_bytes\":%u,\"reference_fnv32\":%u,\"fast_fnv32\":%u}\n",
      i,i<kFramesCount?kFrameIds[i]:-1,unsigned(sciotPadChecks),unsigned(sciotPadComparedBytes),unsigned(sciotPadMismatchBytes),
      unsigned(kOutputBytes),unsigned(activationDiff),unsigned(fnv(references+i*kOutputBytes,kOutputBytes)),unsigned(fnv(result,kOutputBytes)));
    if(sciotPadChecks!=1 || sciotPadComparedBytes!=kPadOut) {sciotPadCheck=false;return fail("pad_check_missing");}
    if(sciotPadMismatchBytes || activationDiff) {sciotPadCheck=false;return fail("fast_pad_mismatch");}
    vTaskDelay(1);
  }
  sciotPadCheck=false;
  printf("{\"event\":\"verify_done\",\"inputs\":%d,\"pad_bytes_compared\":%u,\"all_exact\":true}\n",kVerifyInputs,unsigned(kVerifyInputs*kPadOut));
  return true;
}

// Phase 2 (descriptive): the bare kernels and a plain copy outside TFLM.
void calibrateOne(const char* location,int8_t* in,int8_t* out,int8_t* check) {
  tflite::PadParams p{};
  p.left_padding_count=p.right_padding_count=4;
  const int32_t right[4]={0,1,1,0};
  for(int i=0;i<4;++i) {p.left_padding[i]=0;p.right_padding[i]=right[i];}
  p.resizing_category=tflite::ResizingCategory::kImageStyle;
  const int32_t inDims[4]={1,kPadH,kPadW,kPadD},outDims[4]={1,kPadH+1,kPadW+1,kPadD};
  const tflite::RuntimeShape inShape(4,inDims),outShape(4,outDims);
  const int8_t value=-128;
  for(size_t i=0;i<kPadIn;++i) in[i]=int8_t(i*131+7);
  const char* const kernels[3]={"memcpy","fast_pad","reference_pad"};
  for(int k=0;k<3;++k) {
    for(int r=0;r<kCalibrationWarmup+kCalibrationRepeats;++r) {
      const int64_t start=esp_timer_get_time();
      if(k==0) memcpy(out,in,kPadIn);
      else if(k==1) fastPadHW(in,1,kPadH,kPadW,kPadD,0,1,0,1,value,out);
      else tflite::reference_ops::PadImageStyle(p,inShape,in,&value,outShape,out);
      const int64_t elapsed=esp_timer_get_time()-start;
      if(r>=kCalibrationWarmup)
        printf("{\"event\":\"calibration\",\"location\":\"%s\",\"kernel\":\"%s\",\"iteration\":%d,\"bytes_in\":%u,\"elapsed_us\":%lld}\n",
          location,kernels[k],r-kCalibrationWarmup,unsigned(kPadIn),elapsed);
      vTaskDelay(1);
    }
    if(k==1) memcpy(check,out,kPadOut);
  }
  printf("{\"event\":\"calibration_check\",\"location\":\"%s\",\"fast_equals_reference\":%s}\n",
    location,memcmp(check,out,kPadOut)==0?"true":"false");
}
bool calibrate() {
  int8_t* check=static_cast<int8_t*>(heap_caps_malloc(kPadOut,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!check) return fail("calibration_buffers");
  const uint32_t caps[2]={MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT};
  const char* const names[2]={"psram","internal"};
  for(int l=0;l<2;++l) {
    auto* in=static_cast<int8_t*>(heap_caps_malloc(kPadIn,caps[l]));
    auto* out=static_cast<int8_t*>(heap_caps_malloc(kPadOut,caps[l]));
    if(in && out) calibrateOne(names[l],in,out,check);
    else printf("{\"event\":\"calibration_skipped\",\"location\":\"%s\",\"largest_free_block\":%u}\n",
      names[l],unsigned(heap_caps_get_largest_free_block(caps[l])));
    heap_caps_free(in);heap_caps_free(out);
  }
  heap_caps_free(check);
  return true;
}

// Phase 3: timed comparison. Every activation, warmups included, must match
// the original kernel's reference for the same canonical input.
bool invokeMeasured(int frame,bool profiled,bool measured,int round,int iteration) {
  int64_t elapsed;
  if(!invokeRaw(inputs+frame*kPixels,elapsed)) return false;
  if(profiled) {
    const auto* graph=model->subgraphs()->Get(0);
    if(profiler.overflow || profiler.count!=int(graph->operators()->size())) return fail("profiler_event_count");
    for(int i=0;i<profiler.count;++i) {
      const auto& e=profiler.events[i];
      const auto* op=graph->operators()->Get(i);
      const auto code=model->operator_codes()->Get(op->opcode_index())->builtin_code();
      if(!e.done || strcmp(e.tag,tflite::EnumNameBuiltinOperator(code))!=0) return fail("profiler_operator_order");
      if(e.convUs+e.depthUs>e.elapsed) return fail("kernel_time_outside_operator");
    }
  }
  auto* result=runtime->output(0)->data.int8;
  if(!goldenReady || memcmp(result,references+frame*kOutputBytes,kOutputBytes)) return fail("activation_mismatch");
  if(measured) {
    const char* mode=profiled?"profiled":"plain";
    const char* variant=kVariantNames[current];
    int64_t sum=0;
    if(profiled) for(int i=0;i<profiler.count;++i) sum+=profiler.events[i].elapsed;
    if(sum>elapsed) return fail("overlapping_operator_time");
    printf("{\"event\":\"sample\",\"variant\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"invoke_us\":%lld,\"operator_sum_us\":%lld,\"esp_nn_us\":%lld,\"conv_calls\":%u,\"depthwise_calls\":%u,\"fast_pad_calls\":%u,\"activation_fnv32\":%u,\"exact\":true}\n",
      variant,mode,round,kFrameIds[frame],iteration,elapsed,sum,sciotConvUs+sciotDepthwiseUs,
      unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls),unsigned(sciotFastPadCalls),unsigned(fnv(result,kOutputBytes)));
    if(profiled) for(int i=0;i<profiler.count;++i) {
      const auto& e=profiler.events[i];
      printf("{\"event\":\"operator\",\"variant\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"index\":%d,\"op\":\"%s\",\"elapsed_us\":%lld,\"esp_nn_us\":%lld,\"conv_calls\":%u,\"depthwise_calls\":%u}\n",
        variant,round,kFrameIds[frame],iteration,i,e.tag,e.elapsed,e.convUs+e.depthUs,unsigned(e.convCalls),unsigned(e.depthCalls));
    }
  }
  // Outside Invoke timing; keep the idle watchdog active and serviced.
  vTaskDelay(1);
  return true;
}
struct Block {Variant variant;bool profiled;};
// Order alternates which variant runs first; see README.
constexpr Block kOrder[kRounds][4]={
  {{kOriginal,false},{kFast,false},{kFast,true},{kOriginal,true}},
  {{kFast,true},{kOriginal,true},{kOriginal,false},{kFast,false}},
  {{kFast,false},{kOriginal,false},{kOriginal,true},{kFast,true}},
};
bool measure() {
  for(int round=1;round<=kRounds;++round) {
    for(const auto& block:kOrder[round-1]) {
      const char* mode=block.profiled?"profiled":"plain";
      if(!create(block.variant,block.profiled,"measure",round)) return false;
      memory("measure",block.variant,mode,round);
      for(int frame=0;frame<kFramesCount;++frame) {
        for(int i=0;i<kWarmup;++i) if(!invokeMeasured(frame,block.profiled,false,round,i)) return false;
        for(int i=0;i<kRepeats;++i) if(!invokeMeasured(frame,block.profiled,true,round,i)) return false;
      }
      memory("measure",block.variant,mode,round);
      printf("{\"event\":\"block_done\",\"round\":%d,\"variant\":\"%s\",\"mode\":\"%s\",\"samples\":90}\n",round,kVariantNames[block.variant],mode);
    }
  }
  return true;
}
bool run() {
  goldenReady=false;
  if(!verify() || !calibrate() || !measure()) return false;
  printf("{\"event\":\"done\",\"verify_inputs\":%d,\"samples\":1080,\"operator_records\":5940,\"warmup_invocations\":180,\"all_activations_exact\":true}\n",kVerifyInputs);
  return true;
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment\":\"pad_benchmark\",\"model_sha256\":\"%s\",\"cpu_mhz\":240,\"psram_mhz\":80,\"wifi\":false,\"camera\":false,\"http\":false}\n",kInt8Sha);
  for(int v=0;v<2;++v) {
    auto& r=resolvers[v];
    ESP_ERROR_CHECK(r.AddAdd());ESP_ERROR_CHECK(r.AddConv2D());ESP_ERROR_CHECK(r.AddDepthwiseConv2D());
    ESP_ERROR_CHECK(v==kFast?r.AddPad(RegisterFastPad()):r.AddPad());ESP_ERROR_CHECK(r.AddSoftmax());
  }
  model=tflite::GetModel(kInt8Model);
  arena=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  inputs=static_cast<int8_t*>(heap_caps_malloc(kVerifyInputs*kPixels,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  references=static_cast<int8_t*>(heap_caps_malloc(kVerifyInputs*kOutputBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  sciotPadScratch=static_cast<int8_t*>(heap_caps_malloc(kPadOut,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  sciotPadScratchBytes=kPadOut;
  if(!arena || !inputs || !references || !sciotPadScratch) {fail("buffers");return;}
  for(int f=0;f<kFramesCount;++f) for(int i=0;i<kPixels;++i) {
    float value;memcpy(&value,kFrames[f]+i*sizeof(float),sizeof(value));
    const double q=std::nearbyint(double(value)/kInputScale+kInputZero);
    inputs[f*kPixels+i]=int8_t(std::max(-128.0,std::min(127.0,q)));
  }
  // Fixed-seed xorshift32: reproducible extra inputs covering the full int8 range.
  uint32_t state=20261111u;
  for(int i=kFramesCount*kPixels;i<kVerifyInputs*kPixels;++i) {
    state^=state<<13;state^=state>>17;state^=state<<5;inputs[i]=int8_t(state>>24);
  }
  printf("{\"event\":\"ready\",\"command\":\"g\",\"random_seed\":20261111,\"random_inputs\":%d}\n",kRandomInputs);
  fcntl(fileno(stdin),F_SETFL,O_NONBLOCK);
  for(;;) {
    if(getchar()=='g') {run();printf("{\"event\":\"ready\",\"command\":\"g\"}\n");}
    clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(10));
  }
}
