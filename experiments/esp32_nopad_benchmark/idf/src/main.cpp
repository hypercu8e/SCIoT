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

#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error ESP-NN is required
#endif
#if defined(TF_LITE_STRIP_ERROR_STRINGS)
#error TFLM profiling hooks require operator names
#endif

namespace {
// Same split-arena API everywhere: fixed structures in PSRAM, planned
// activations and ESP-NN scratch in PSRAM or internal RAM.
constexpr size_t kPersistentBytes=64*1024,kActivationBytes=240*1024,kOutputBytes=4608;
constexpr int kFramesCount=3,kRounds=3,kRepeats=30,kWarmup=5,kMaxEvents=64;
enum Model {kWithPad=0,kWithoutPad=1};
enum Memory {kPsram=0,kInternal=1};
const char* const kModelNames[2]={"pad","nopad"};
const char* const kMemoryNames[2]={"psram","internal"};
struct Variant {Model model;Memory memory;};
constexpr Variant kVariants[4]={{kWithPad,kPsram},{kWithoutPad,kPsram},{kWithoutPad,kInternal},{kWithPad,kInternal}};

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
int8_t* inputs;
int8_t* golden;
bool goldenReady=false;
const tflite::Model* models[2];
Variant current{kWithPad,kPsram};

bool fail(const char* reason) {
  printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);return false;
}
uint32_t fnv(const int8_t* p,size_t n) {
  uint32_t h=2166136261u;while(n--) {h^=uint8_t(*p++);h*=16777619u;}return h;
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
bool build(Model model,uint8_t* buffer,size_t bytes,bool profiled) {
  destroy();sciotKernelTiming=profiled;profiler.reset();
  auto* allocator=tflite::MicroAllocator::Create(persistent,kPersistentBytes,buffer,bytes);
  if(!allocator) return false;
  runtime=new(interpreterStorage) tflite::MicroInterpreter(models[model],resolver,allocator,nullptr,profiled?&profiler:nullptr);
  return runtime->AllocateTensors()==kTfLiteOk;
}
// Smallest activation arena (16-byte steps) that TFLM can plan for this model.
bool activationPeak(Model model) {
  size_t lo=16,hi=kActivationBytes;
  if(!build(model,activations[kPsram],hi,false)) return fail("activation_peak_upper");
  const unsigned used=unsigned(runtime->arena_used_bytes());
  while(hi-lo>16) {
    const size_t mid=(lo+hi)/2/16*16;
    if(build(model,activations[kPsram],mid,false)) hi=mid; else lo=mid;
    vTaskDelay(1);
  }
  destroy();
  printf("{\"event\":\"activation_peak\",\"model\":\"%s\",\"min_activation_bytes\":%u,\"arena_used_at_240k\":%u}\n",
    kModelNames[model],unsigned(hi),used);
  return true;
}
bool create(Variant v,bool profiled,const char* phase,int round) {
  current=v;
  if(!build(v.model,activations[v.memory],kActivationBytes,profiled)) return fail("allocate_tensors");
  if(runtime->input(0)->bytes!=kPixels || runtime->output(0)->bytes!=kOutputBytes) return fail("tensor_shape");
  const void* in=runtime->input(0)->data.data;
  const void* out=runtime->output(0)->data.data;
  const bool internal=esp_ptr_internal(in) && esp_ptr_internal(out);
  const bool external=esp_ptr_external_ram(in) && esp_ptr_external_ram(out);
  if(v.memory==kInternal?!internal:!external) return fail("activation_location");
  printf("{\"event\":\"block\",\"phase\":\"%s\",\"model\":\"%s\",\"memory\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"persistent_address\":\"%p\",\"activation_address\":\"%p\",\"activations_internal\":%s,\"arena_used\":%u}\n",
    phase,kModelNames[v.model],kMemoryNames[v.memory],profiled?"profiled":"plain",round,persistent,activations[v.memory],
    internal?"true":"false",unsigned(runtime->arena_used_bytes()));
  return true;
}
bool invoke(int frame,bool profiled,bool measured,int round,int iteration) {
  memcpy(runtime->input(0)->data.int8,inputs+frame*kPixels,kPixels);
  profiler.reset();sciotConvCalls=sciotDepthwiseCalls=0;sciotConvUs=sciotDepthwiseUs=0;sciotFastPadCalls=0;
  const int64_t start=esp_timer_get_time();
  const TfLiteStatus status=runtime->Invoke();
  const int64_t elapsed=esp_timer_get_time()-start;
  if(status!=kTfLiteOk) return fail("invoke");
  if(sciotConvCalls!=6 || sciotDepthwiseCalls!=3) return fail("optimized_kernel_count");
  if(sciotFastPadCalls!=(current.model==kWithPad?1u:0u)) return fail("fast_pad_call_count");
  const auto* model=models[current.model];
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
  if(!goldenReady) {
    // Reference phase only: the original model on PSRAM.
    if(profiled || current.model!=kWithPad || current.memory!=kPsram || measured) return fail("golden_missing");
    memcpy(golden+frame*kOutputBytes,result,kOutputBytes);
    printf("{\"event\":\"golden\",\"frame\":%d,\"input_hex\":\"",kFrameIds[frame]);hex(inputs+frame*kPixels,kPixels);
    printf("\",\"activation_hex\":\"");hex(result,kOutputBytes);printf("\"}\n");
  } else if(memcmp(result,golden+frame*kOutputBytes,kOutputBytes)) return fail("activation_mismatch");
  if(measured) {
    const char* mode=profiled?"profiled":"plain";
    int64_t sum=0;
    if(profiled) for(int i=0;i<profiler.count;++i) sum+=profiler.events[i].elapsed;
    if(sum>elapsed) return fail("overlapping_operator_time");
    printf("{\"event\":\"sample\",\"model\":\"%s\",\"memory\":\"%s\",\"mode\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"invoke_us\":%lld,\"operator_sum_us\":%lld,\"esp_nn_us\":%lld,\"conv_calls\":%u,\"depthwise_calls\":%u,\"fast_pad_calls\":%u,\"activation_fnv32\":%u,\"exact\":true}\n",
      kModelNames[current.model],kMemoryNames[current.memory],mode,round,kFrameIds[frame],iteration,elapsed,sum,sciotConvUs+sciotDepthwiseUs,
      unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls),unsigned(sciotFastPadCalls),unsigned(fnv(result,kOutputBytes)));
    if(profiled) for(int i=0;i<profiler.count;++i) {
      const auto& e=profiler.events[i];
      printf("{\"event\":\"operator\",\"model\":\"%s\",\"memory\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"index\":%d,\"op\":\"%s\",\"elapsed_us\":%lld,\"esp_nn_us\":%lld,\"conv_calls\":%u,\"depthwise_calls\":%u}\n",
        kModelNames[current.model],kMemoryNames[current.memory],round,kFrameIds[frame],iteration,i,e.tag,e.elapsed,e.convUs+e.depthUs,
        unsigned(e.convCalls),unsigned(e.depthCalls));
    }
  }
  // Outside Invoke timing; keep the idle watchdog active and serviced.
  vTaskDelay(1);
  return true;
}
bool block(const Variant& v,bool profiled,int round) {
  const char* mode=profiled?"profiled":"plain";
  if(!create(v,profiled,"measure",round)) return false;
  for(int frame=0;frame<kFramesCount;++frame) {
    for(int i=0;i<kWarmup;++i) if(!invoke(frame,profiled,false,round,i)) return false;
    for(int i=0;i<kRepeats;++i) if(!invoke(frame,profiled,true,round,i)) return false;
  }
  printf("{\"event\":\"block_done\",\"round\":%d,\"model\":\"%s\",\"memory\":\"%s\",\"mode\":\"%s\",\"samples\":90}\n",
    round,kModelNames[v.model],kMemoryNames[v.memory],mode);
  return true;
}
bool run() {
  goldenReady=false;
  if(!activationPeak(kWithPad) || !activationPeak(kWithoutPad)) return false;
  // Reference activations: original model, PSRAM, before any measured block.
  if(!create({kWithPad,kPsram},false,"reference",0)) return false;
  for(int frame=0;frame<kFramesCount;++frame) if(!invoke(frame,false,false,0,0)) return false;
  goldenReady=true;
  // Round r rotates the variant order by r-1: plain blocks forward, profiled backward.
  for(int round=1;round<=kRounds;++round) {
    for(int k=0;k<4;++k) if(!block(kVariants[(k+round-1)%4],false,round)) return false;
    for(int k=3;k>=0;--k) if(!block(kVariants[(k+round-1)%4],true,round)) return false;
  }
  destroy();
  heap("after_run");
  printf("{\"event\":\"done\",\"samples\":2160,\"operator_records\":11340,\"warmup_invocations\":360,\"all_activations_exact\":true}\n");
  return true;
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment\":\"nopad_benchmark\",\"model_sha256\":\"%s\",\"nopad_model_sha256\":\"%s\",\"cpu_mhz\":240,\"psram_mhz\":80,\"wifi\":false,\"camera\":false,\"http\":false}\n",
    kInt8Sha,kNoPadSha);
  ESP_ERROR_CHECK(resolver.AddAdd());ESP_ERROR_CHECK(resolver.AddConv2D());ESP_ERROR_CHECK(resolver.AddDepthwiseConv2D());
  ESP_ERROR_CHECK(resolver.AddPad(RegisterFastPad()));ESP_ERROR_CHECK(resolver.AddSoftmax());
  models[kWithPad]=tflite::GetModel(kInt8Model);models[kWithoutPad]=tflite::GetModel(kNoPadModel);
  heap("boot");
  // Internal first, while the heap is least fragmented.
  activations[kInternal]=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kActivationBytes,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
  if(!activations[kInternal]) {
    printf("{\"event\":\"internal_arena_unavailable\",\"requested\":%u,\"internal_largest_block\":%u}\n",
      unsigned(kActivationBytes),unsigned(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)));
    return;
  }
  constexpr uint32_t psram=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
  persistent=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kPersistentBytes,psram));
  activations[kPsram]=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kActivationBytes,psram));
  inputs=static_cast<int8_t*>(heap_caps_malloc(kFramesCount*kPixels,psram));
  golden=static_cast<int8_t*>(heap_caps_malloc(kFramesCount*kOutputBytes,psram));
  if(!persistent || !activations[kPsram] || !inputs || !golden) {fail("buffers");return;}
  heap("allocated");
  for(int f=0;f<kFramesCount;++f) for(int i=0;i<kPixels;++i) {
    float value;memcpy(&value,kFrames[f]+i*sizeof(float),sizeof(value));
    const double q=std::nearbyint(double(value)/kInputScale+kInputZero);
    inputs[f*kPixels+i]=int8_t(std::max(-128.0,std::min(127.0,q)));
  }
  printf("{\"event\":\"ready\",\"command\":\"g\"}\n");
  fcntl(fileno(stdin),F_SETFL,O_NONBLOCK);
  for(;;) {
    if(getchar()=='g') {run();printf("{\"event\":\"ready\",\"command\":\"g\"}\n");}
    clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(10));
  }
}
