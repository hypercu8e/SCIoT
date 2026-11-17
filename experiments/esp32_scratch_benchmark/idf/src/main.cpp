#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <new>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"
#include "esp_memory_utils.h"
#include "esp_timer.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_profiler_interface.h"
#include "generated/assets.h"
#include "generated/nopad_model.h"
#include "probe.h"

#if CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ != 240 || CONFIG_SPIRAM_SPEED != 80
#error Frozen CPU and PSRAM clocks required
#endif
#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error ESP-NN is required
#endif
#if defined(TF_LITE_STRIP_ERROR_STRINGS)
#error TFLM profiling hooks require operator names
#endif

extern "C" {
void sciot_set_strip_rows(int);
int sciot_get_strip_rows(void);
int sciot_get_strip_effective(void);
int sciot_get_strip_bytes(void);
int sciot_scratch_configuration_safe(void);
}
namespace {
// Same split-arena API everywhere: fixed structures in PSRAM, planned
// activations and ESP-NN scratch in PSRAM or internal RAM.
constexpr size_t kPersistentBytes=64*1024,kActivationBytes=240*1024,kOutputBytes=4608;
constexpr int kFramesCount=35,kRounds=3,kRepeats=30,kWarmup=5,kMaxEvents=64;
enum Model {kWithPad=0,kWithoutPad=1};
enum Memory {kPsram=0,kInternal=1};
const char* const kModelNames[2]={"pad","nopad"};
const char* const kMemoryNames[2]={"psram","internal"};
struct Variant {Model model;Memory memory;};

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
tflite::MicroMutableOpResolver<5> resolver;
tflite::MicroInterpreter* runtime=nullptr;
alignas(tflite::MicroInterpreter) unsigned char interpreterStorage[sizeof(tflite::MicroInterpreter)];
uint8_t* persistent;
uint8_t* activations[2];
size_t peaks[5];
int stripIndex=0;
constexpr int strips[5]={0,3,5,7,9};
constexpr size_t guardBytes=32;
size_t activeBytes=0;
uint8_t* activeBuffer=nullptr;
int8_t* inputs;
int8_t* golden;
bool goldenReady=false;
const tflite::Model* models[2];
Variant current{kWithPad,kPsram};

bool fail(const char* reason) {
  printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);return false;
}
void hex(const int8_t* p,size_t n) {for(size_t i=0;i<n;++i) printf("%02x",uint8_t(p[i]));}
void heap(const char* stage) {
  constexpr uint32_t internal=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT;
  printf("{\"event\":\"heap\",\"stage\":\"%s\",\"internal_free\":%u,\"internal_largest_block\":%u,\"internal_min\":%u,\"psram_free\":%u}\n",
    stage,unsigned(heap_caps_get_free_size(internal)),unsigned(heap_caps_get_largest_free_block(internal)),
    unsigned(heap_caps_get_minimum_free_size(internal)),unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
}
void destroy() {if(runtime) {runtime->~MicroInterpreter();runtime=nullptr;}}
// Builds an interpreter on the given activation buffer/size; false if TFLM cannot plan it.
bool guards() {
  if(!activeBuffer) return true;
  for(size_t i=0;i<guardBytes;++i)
    if(activeBuffer[-int(guardBytes)+int(i)]!=0xa5 || activeBuffer[activeBytes+i]!=0xa5) return false;
  return true;
}
bool build(Model model,uint8_t* buffer,size_t bytes,bool profiled) {
  destroy();
  if(!guards() || !sciot_scratch_configuration_safe()) return fail("scratch_or_guard_unsafe");
  sciot_set_strip_rows(strips[stripIndex]);
  activeBuffer=buffer;activeBytes=bytes;
  memset(buffer-guardBytes,0xa5,guardBytes);memset(buffer+bytes,0xa5,guardBytes);
  sciotKernelTiming=profiled;profiler.reset();
  auto* allocator=tflite::MicroAllocator::Create(persistent,kPersistentBytes,buffer,bytes);
  if(!allocator) return false;
  runtime=new(interpreterStorage) tflite::MicroInterpreter(models[model],resolver,allocator,nullptr,profiled?&profiler:nullptr);
  return runtime->AllocateTensors()==kTfLiteOk;
}
bool activationPeak() {
  size_t lo=16,hi=kActivationBytes;
  if(!build(kWithoutPad,activations[kPsram],hi,false)) return fail("peak_upper");
  while(hi-lo>16) {
    const size_t mid=(lo+hi)/2/16*16;
    if(build(kWithoutPad,activations[kPsram],mid,false)) hi=mid;else lo=mid;
    vTaskDelay(1);
  }
  destroy();peaks[stripIndex]=hi;
  printf("{\"event\":\"activation_peak\",\"variant\":%d,\"min_activation_bytes\":%u,\"effective_rows\":%d,\"scratch_bytes\":%d}\n",
    strips[stripIndex],unsigned(hi),sciot_get_strip_effective(),sciot_get_strip_bytes());
  return true;
}
bool create(Memory memory,bool profiled,Model model=kWithoutPad) {
  current={model,memory};
  const size_t bytes=model==kWithPad?kActivationBytes:peaks[stripIndex];
  if(!build(model,activations[memory],bytes,profiled)) return fail("allocate_tensors");
  if(runtime->input(0)->bytes!=kPixels || runtime->output(0)->bytes!=kOutputBytes) return fail("tensor_shape");
  bool correct=memory==kInternal?
    esp_ptr_internal(runtime->input(0)->data.data)&&esp_ptr_internal(runtime->output(0)->data.data):
    esp_ptr_external_ram(runtime->input(0)->data.data)&&esp_ptr_external_ram(runtime->output(0)->data.data);
  if(!correct) return fail("activation_location");
  return true;
}
int frameId(int frame) {return frame<3?kFrameIds[frame]:1000+frame-3;}
bool invoke(int frame,bool profiled,bool measured,int round,int iteration) {
  memcpy(runtime->input(0)->data.int8,inputs+frame*kPixels,kPixels);
  profiler.reset();sciotConvCalls=sciotDepthwiseCalls=0;sciotConvUs=sciotDepthwiseUs=0;sciotFastPadCalls=0;
  const int64_t start=esp_timer_get_time();
  const TfLiteStatus status=runtime->Invoke();
  const int64_t elapsed=esp_timer_get_time()-start;
  if(status!=kTfLiteOk || !guards()) return fail("invoke_or_guard");
  if(!sciot_scratch_configuration_safe() || sciot_get_strip_rows()!=strips[stripIndex]) return fail("scratch_configuration");
  if(sciotConvCalls!=6 || sciotDepthwiseCalls!=3 || sciotFastPadCalls!=unsigned(current.model==kWithPad)) return fail("kernel_count");
  auto* result=runtime->output(0)->data.int8;
  if(!goldenReady) {
    memcpy(golden+frame*kOutputBytes,result,kOutputBytes);
    if(frame<3) {
      printf("{\"event\":\"golden\",\"frame\":%d,\"activation_hex\":\"",frameId(frame));
      hex(result,kOutputBytes);printf("\"}\n");
    }
  } else if(memcmp(result,golden+frame*kOutputBytes,kOutputBytes)) return fail("activation_mismatch");
  int64_t sum=0;
  if(profiled) {
    const auto* graph=models[current.model]->subgraphs()->Get(0);
    if(profiler.overflow || profiler.count!=int(graph->operators()->size())) return fail("profiler_count");
    for(int i=0;i<profiler.count;++i) {
      const auto& e=profiler.events[i];
      const auto* op=graph->operators()->Get(i);
      if(!e.done || strcmp(e.tag,tflite::EnumNameBuiltinOperator(models[current.model]->operator_codes()->Get(op->opcode_index())->builtin_code()))) return fail("profiler_order");
      if(e.convUs+e.depthUs>e.elapsed) return fail("kernel_timing");
      sum+=e.elapsed;
    }
    if(sum>elapsed) return fail("operator_timing");
  }
  if(measured) {
    printf("{\"event\":\"sample\",\"variant\":%d,\"memory\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"invoke_us\":%lld,\"exact\":true,\"guards\":true,\"conv_calls\":%u,\"depthwise_calls\":%u,\"operator_sum_us\":%lld}\n",
      strips[stripIndex],kMemoryNames[current.memory],profiled?"profiled":"plain",round,frameId(frame),iteration,elapsed,unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls),sum);
    if(profiled) for(int i=0;i<profiler.count;++i) {
      auto& e=profiler.events[i];
      printf("{\"event\":\"operator\",\"variant\":%d,\"memory\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"index\":%d,\"op\":\"%s\",\"elapsed_us\":%lld,\"esp_nn_us\":%lld}\n",
        strips[stripIndex],kMemoryNames[current.memory],round,frameId(frame),iteration,i,e.tag,e.elapsed,e.convUs+e.depthUs);
    }
  }
  vTaskDelay(1);return true;
}
bool block(Memory memory,bool profiled,int round) {
  if(!create(memory,profiled)) return false;
  printf("{\"event\":\"block\",\"variant\":%d,\"memory\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"activation_address\":\"%p\",\"persistent_address\":\"%p\",\"arena_bytes\":%u,\"arena_used\":%u}\n",
    strips[stripIndex],kMemoryNames[memory],profiled?"profiled":"plain",round,activations[memory],persistent,unsigned(peaks[stripIndex]),unsigned(runtime->arena_used_bytes()));
  for(int f=0;f<3;++f) {
    for(int i=0;i<kWarmup;++i) if(!invoke(f,profiled,false,round,i)) return false;
    for(int i=0;i<kRepeats;++i) if(!invoke(f,profiled,true,round,i)) return false;
  }
  printf("{\"event\":\"block_done\",\"variant\":%d,\"memory\":\"%s\",\"mode\":\"%s\",\"round\":%d}\n",
    strips[stripIndex],kMemoryNames[memory],profiled?"profiled":"plain",round);
  return true;
}
bool run() {
  goldenReady=false;stripIndex=0;
  if(!create(kPsram,false,kWithPad)) return false;
  for(int f=0;f<kFramesCount;++f) if(!invoke(f,false,false,0,0)) return false;
  goldenReady=true;
  for(stripIndex=0;stripIndex<5;++stripIndex) if(!activationPeak()) return false;
  for(stripIndex=0;stripIndex<5;++stripIndex) for(int mem=0;mem<2;++mem) {
    if(!create(Memory(mem),false)) return false;
    for(int f=0;f<kFramesCount;++f) if(!invoke(f,false,false,0,0)) return false;
    printf("{\"event\":\"validation\",\"variant\":%d,\"memory\":\"%s\",\"inputs\":35,\"exact\":true,\"guards\":true}\n",strips[stripIndex],kMemoryNames[mem]);
  }
  for(int round=1;round<=3;++round) for(int mode=0;mode<2;++mode) for(int k=0;k<10;++k) {
    const int v=((mode?9-k:k)+round-1)%10;stripIndex=v/2;
    if(!block(Memory(v%2),mode,round)) return false;
  }
  destroy();heap("after_run");
  printf("{\"event\":\"done\",\"samples\":5400,\"operator_records\":27000,\"warmup_invocations\":900,\"all_activations_exact\":true}\n");
  return true;
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment\":\"scratch_benchmark\",\"model_sha256\":\"%s\",\"nopad_model_sha256\":\"%s\",\"cpu_mhz\":240,\"psram_mhz\":80,\"wifi\":false,\"camera\":false,\"http\":false}\n",
    kInt8Sha,kNoPadSha);
  ESP_ERROR_CHECK(resolver.AddAdd());ESP_ERROR_CHECK(resolver.AddConv2D());ESP_ERROR_CHECK(resolver.AddDepthwiseConv2D());
  ESP_ERROR_CHECK(resolver.AddPad(RegisterFastPad()));ESP_ERROR_CHECK(resolver.AddSoftmax());
  models[kWithPad]=tflite::GetModel(kInt8Model);models[kWithoutPad]=tflite::GetModel(kNoPadModel);
  heap("boot");
  // Internal first, while the heap is least fragmented.
  activations[kInternal]=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kActivationBytes+2*guardBytes,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
  if(!activations[kInternal]) {
    printf("{\"event\":\"internal_arena_unavailable\",\"requested\":%u,\"internal_largest_block\":%u}\n",
      unsigned(kActivationBytes),unsigned(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)));
    return;
  }
  constexpr uint32_t psram=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
  persistent=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kPersistentBytes,psram));
  activations[kPsram]=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kActivationBytes+2*guardBytes,psram));
  inputs=static_cast<int8_t*>(heap_caps_malloc(kFramesCount*kPixels,psram));
  golden=static_cast<int8_t*>(heap_caps_malloc(kFramesCount*kOutputBytes,psram));
  if(!persistent || !activations[kPsram] || !inputs || !golden) {fail("buffers");return;}
  activations[kInternal]+=guardBytes;activations[kPsram]+=guardBytes;
  heap("allocated");
  for(int f=0;f<3;++f) for(int i=0;i<kPixels;++i) {
    float value;memcpy(&value,kFrames[f]+i*sizeof(float),sizeof(value));
    const double q=std::nearbyint(double(value)/kInputScale+kInputZero);
    inputs[f*kPixels+i]=int8_t(std::max(-128.0,std::min(127.0,q)));
  }
  uint32_t rng=20261116u;
  for(int f=3;f<kFramesCount;++f) for(int i=0;i<kPixels;++i) {
    rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;inputs[f*kPixels+i]=int8_t(rng&255);
  }
  printf("{\"event\":\"ready\",\"command\":\"g\"}\n");
  fcntl(fileno(stdin),F_SETFL,O_NONBLOCK);
  for(;;) {
    if(getchar()=='g') {run();printf("{\"event\":\"ready\",\"command\":\"g\"}\n");}
    clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(10));
  }
}
