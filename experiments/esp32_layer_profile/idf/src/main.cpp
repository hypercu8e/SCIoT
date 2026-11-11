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
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_profiler_interface.h"
#include "generated/assets.h"
#include "probe.h"

#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error ESP-NN is required
#endif
#if defined(TF_LITE_STRIP_ERROR_STRINGS)
#error TFLM profiling hooks require operator names
#endif

namespace {
constexpr size_t kArenaBytes=1024*1024,kOutputBytes=4608;
constexpr int kFramesCount=3,kRounds=3,kRepeats=30,kWarmup=5,kMaxEvents=64;
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
uint8_t* arena;
int8_t* inputs;
int8_t* golden;
bool goldenReady[kFramesCount]={};
const tflite::Model* model;

bool fail(const char* reason) {
  printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);return false;
}
uint32_t fnv(const int8_t* p,size_t n) {
  uint32_t h=2166136261u;while(n--) {h^=uint8_t(*p++);h*=16777619u;}return h;
}
void hex(const int8_t* p,size_t n) {for(size_t i=0;i<n;++i) printf("%02x",uint8_t(p[i]));}
void memory(const char* mode,int round) {
  printf("{\"event\":\"memory\",\"mode\":\"%s\",\"round\":%d,\"internal_free\":%u,\"psram_free\":%u,\"internal_min\":%u}\n",
    mode,round,unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)));
}
bool create(bool profiled,int round) {
  if(runtime) {runtime->~MicroInterpreter();runtime=nullptr;}
  sciotKernelTiming=profiled;
  profiler.reset();
  runtime=new(interpreterStorage) tflite::MicroInterpreter(model,resolver,arena,kArenaBytes,nullptr,profiled?&profiler:nullptr);
  if(runtime->AllocateTensors()!=kTfLiteOk) return fail("allocate_tensors");
  if(runtime->input(0)->bytes!=kPixels || runtime->output(0)->bytes!=kOutputBytes) return fail("tensor_shape");
  printf("{\"event\":\"block\",\"mode\":\"%s\",\"round\":%d,\"arena_address\":\"%p\",\"arena_capacity\":%u,\"arena_used\":%u}\n",
    profiled?"profiled":"plain",round,arena,unsigned(kArenaBytes),unsigned(runtime->arena_used_bytes()));
  return true;
}
bool invoke(int frame,bool profiled,bool measured,int round,int iteration) {
  memcpy(runtime->input(0)->data.int8,inputs+frame*kPixels,kPixels);
  profiler.reset();sciotConvCalls=sciotDepthwiseCalls=0;sciotConvUs=sciotDepthwiseUs=0;
  const int64_t start=esp_timer_get_time();
  const TfLiteStatus status=runtime->Invoke();
  const int64_t elapsed=esp_timer_get_time()-start;
  if(status!=kTfLiteOk) return fail("invoke");
  if(sciotConvCalls!=6 || sciotDepthwiseCalls!=3) return fail("optimized_kernel_count");
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
  if(!goldenReady[frame]) {
    if(profiled) return fail("golden_missing");
    memcpy(golden+frame*kOutputBytes,result,kOutputBytes);goldenReady[frame]=true;
    printf("{\"event\":\"golden\",\"frame\":%d,\"input_hex\":\"",kFrameIds[frame]);hex(inputs+frame*kPixels,kPixels);
    printf("\",\"activation_hex\":\"");hex(result,kOutputBytes);printf("\"}\n");
  }
  if(memcmp(result,golden+frame*kOutputBytes,kOutputBytes)) return fail("activation_mismatch");
  if(measured) {
    const char* mode=profiled?"profiled":"plain";
    int64_t sum=0;
    if(profiled) for(int i=0;i<profiler.count;++i) sum+=profiler.events[i].elapsed;
    if(sum>elapsed) return fail("overlapping_operator_time");
    printf("{\"event\":\"sample\",\"mode\":\"%s\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"invoke_us\":%lld,\"operator_sum_us\":%lld,\"esp_nn_us\":%lld,\"conv_calls\":%u,\"depthwise_calls\":%u,\"activation_fnv32\":%u,\"exact\":true}\n",
      mode,round,kFrameIds[frame],iteration,elapsed,sum,sciotConvUs+sciotDepthwiseUs,
      unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls),unsigned(fnv(result,kOutputBytes)));
    if(profiled) for(int i=0;i<profiler.count;++i) {
      const auto& e=profiler.events[i];
      printf("{\"event\":\"operator\",\"round\":%d,\"frame\":%d,\"iteration\":%d,\"index\":%d,\"op\":\"%s\",\"elapsed_us\":%lld,\"esp_nn_us\":%lld,\"conv_calls\":%u,\"depthwise_calls\":%u}\n",
        round,kFrameIds[frame],iteration,i,e.tag,e.elapsed,e.convUs+e.depthUs,unsigned(e.convCalls),unsigned(e.depthCalls));
    }
  }
  // Outside Invoke timing; keep the idle watchdog active and serviced.
  vTaskDelay(1);
  return true;
}
bool run() {
  memset(goldenReady,0,sizeof(goldenReady));
  for(int round=1;round<=kRounds;++round) {
    const bool order[2]={round==2,round!=2};
    for(bool profiled:order) {
      const char* mode=profiled?"profiled":"plain";
      if(!create(profiled,round)) return false;
      memory(mode,round);
      for(int frame=0;frame<kFramesCount;++frame) {
        for(int i=0;i<kWarmup;++i) if(!invoke(frame,profiled,false,round,i)) return false;
        for(int i=0;i<kRepeats;++i) if(!invoke(frame,profiled,true,round,i)) return false;
      }
      memory(mode,round);
      printf("{\"event\":\"block_done\",\"round\":%d,\"mode\":\"%s\",\"samples\":90}\n",round,mode);
    }
  }
  printf("{\"event\":\"done\",\"samples\":540,\"operator_records\":2970,\"warmup_invocations\":90,\"all_activations_exact\":true}\n");
  return true;
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment\":\"layer_profile\",\"model_sha256\":\"%s\",\"cpu_mhz\":240,\"psram_mhz\":80,\"wifi\":false,\"camera\":false,\"http\":false}\n",kInt8Sha);
  ESP_ERROR_CHECK(resolver.AddAdd());ESP_ERROR_CHECK(resolver.AddConv2D());
  ESP_ERROR_CHECK(resolver.AddDepthwiseConv2D());ESP_ERROR_CHECK(resolver.AddPad());ESP_ERROR_CHECK(resolver.AddSoftmax());
  model=tflite::GetModel(kInt8Model);
  arena=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  inputs=static_cast<int8_t*>(heap_caps_malloc(kFramesCount*kPixels,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  golden=static_cast<int8_t*>(heap_caps_malloc(kFramesCount*kOutputBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!arena || !inputs || !golden) {fail("buffers");return;}
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
