#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <new>
#include <atomic>
#include <memory>
#include "esp_memory_utils.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "generated/nopad_model.h"
#include "probe.h"
#include "xclk_probe.h"
#include "gated_camera.h"
#include "frame_skip.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_camera.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "generated/assets.h"
#include "cJSON.h"
#include "esp_mac.h"
#include "../../include/network.local.h"


extern "C" {
// Frozen camera driver's stop disables VSYNC interrupts and capture, without
// deinitializing the sensor or freeing camera buffers. Diagnostic use only.
void cam_stop(void);
void sciot_set_strip_rows(int);
int sciot_get_strip_rows(void);
int sciot_get_strip_effective(void);
int sciot_get_strip_bytes(void);
int sciot_scratch_configuration_safe(void);
}
#if CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ != 240 || CONFIG_SPIRAM_SPEED != 80
#error Frozen CPU and PSRAM clocks required
#endif
#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error ESP-NN required
#endif
#if CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP
#error Wi-Fi buffer placement must match the operational client
#endif
#ifndef FIT_EARLY_ARENA
#define FIT_EARLY_ARENA 0
#endif

#include "transport.h"
namespace {
constexpr bool kEarlyArena=FIT_EARLY_ARENA;
constexpr size_t kActivationBytes=145760,kPersistentBytes=64*1024,kGuardBytes=32,kOutputBytes=4608;
constexpr uint32_t kInternal=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT,kPsram=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
constexpr int kInputs=35,kCameraFrames=1000;
tflite::MicroMutableOpResolver<5> resolver;
tflite::MicroInterpreter* runtime=nullptr;
alignas(tflite::MicroInterpreter) unsigned char interpreterStorage[sizeof(tflite::MicroInterpreter)];
uint8_t *persistent=nullptr,*activation=nullptr,*internalRaw=nullptr;
bool reserveMonitoring=false;
size_t activeBytes=0;
int8_t *inputs=nullptr,*golden=nullptr,*rgbLut=nullptr;
float* canonical=nullptr;
uint8_t* message=nullptr;
volatile uint8_t response[32+432*4];
EventGroupHandle_t wifiEvents;
std::atomic<bool> measuring{false};
std::atomic<unsigned> disconnections{0};
bool fail(const char* reason) {printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);return false;}
void hex(const int8_t* p,size_t n) {for(size_t i=0;i<n;++i) printf("%02x",uint8_t(p[i]));}
bool reservedGuards() {
  if(!internalRaw)return true;
  for(size_t i=0;i<kGuardBytes;++i)if(internalRaw[i]!=0xa5 || internalRaw[kGuardBytes+kActivationBytes+i]!=0xa5)return false;
  return true;
}
bool guards() {
  if(!reservedGuards())return false;
  if(!activation)return true;
  for(size_t i=0;i<kGuardBytes;++i)if(activation[-int(kGuardBytes)+int(i)]!=0xa5 || activation[activeBytes+i]!=0xa5)return false;
  return true;
}
bool connected() {return (xEventGroupGetBits(wifiEvents)&1)!=0;}
bool memory(const char* stage) {
  const size_t free=heap_caps_get_free_size(kInternal),low=heap_caps_get_minimum_free_size(kInternal);
  printf("{\"event\":\"memory\",\"stage\":\"%s\",\"internal_free\":%u,\"internal_min_free\":%u,\"largest_block\":%u,\"psram_free\":%u,\"measuring\":%s}\n",
    stage,unsigned(free),unsigned(low),unsigned(heap_caps_get_largest_free_block(kInternal)),unsigned(heap_caps_get_free_size(kPsram)),reserveMonitoring?"true":"false");
  if(!reservedGuards())return fail("reserved_guard_corrupted");
  return !reserveMonitoring || (free>=32768 && low>=32768) || fail("internal_reserve");
}
void destroy() {if(runtime){runtime->~MicroInterpreter();runtime=nullptr;}}
bool create(const uint8_t* binary,size_t bytes,bool internal) {
  activeBytes=bytes;
  memset(activation-kGuardBytes,0xa5,kGuardBytes);memset(activation+bytes,0xa5,kGuardBytes);
  auto* allocator=tflite::MicroAllocator::Create(persistent,kPersistentBytes,activation,bytes);
  if(!allocator)return fail("allocator");
  runtime=new(interpreterStorage)tflite::MicroInterpreter(tflite::GetModel(binary),resolver,allocator);
  if(runtime->AllocateTensors()!=kTfLiteOk)return fail("allocate_tensors");
  if(runtime->input(0)->bytes!=kPixels || runtime->output(0)->bytes!=kOutputBytes)return fail("tensor_shape");
  const void* in=runtime->input(0)->data.data;const void* out=runtime->output(0)->data.data;
  if(internal?!(esp_ptr_internal(in)&&esp_ptr_internal(out)):!(esp_ptr_external_ram(in)&&esp_ptr_external_ram(out)))return fail("tensor_location");
  return true;
}
bool invoke(bool reference,int64_t* elapsed=nullptr) {
  sciotConvCalls=sciotDepthwiseCalls=sciotFastPadCalls=0;sciotKernelTiming=false;
  const int64_t start=esp_timer_get_time();const auto status=runtime->Invoke();
  if(elapsed)*elapsed=esp_timer_get_time()-start;
  if(status!=kTfLiteOk || !guards())return fail("invoke_or_guards");
  if(sciotConvCalls!=6 || sciotDepthwiseCalls!=3 || sciotFastPadCalls!=unsigned(reference))return fail("kernel_count");
  if(!sciot_scratch_configuration_safe())return fail("scratch_configuration");
  if(measuring && (!connected() || disconnections))return fail("wifi_lost_during_measurement");
  return true;
}
int8_t quantize(float value) {
  const double q=std::nearbyint(double(value)/kInputScale+kInputZero);
  return int8_t(std::max(-128.0,std::min(127.0,q)));
}
bool buffers() {
  persistent=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kPersistentBytes,kPsram));
  canonical=static_cast<float*>(heap_caps_aligned_alloc(16,kPixels*sizeof(float),kPsram));
  message=static_cast<uint8_t*>(heap_caps_malloc(32+kOutputBytes,kPsram));
  rgbLut=static_cast<int8_t*>(heap_caps_malloc(65536,kPsram));
  inputs=static_cast<int8_t*>(heap_caps_malloc(kInputs*kPixels,kPsram));
  golden=static_cast<int8_t*>(heap_caps_malloc(kInputs*kOutputBytes,kPsram));
  if(!persistent||!canonical||!message||!rgbLut||!inputs||!golden)return fail("psram_buffers");
  // Touch retained client buffers so the linker cannot remove their footprint.
  for(size_t i=0;i<sizeof(response);++i) {response[i]=0;}
  response[0]=uint8_t(esp_timer_get_time());
  memset(message,response[0],32+kOutputBytes);memset(canonical,0,kPixels*sizeof(float));
  for(int p=0;p<65536;++p)rgbLut[p]=quantize((float((p>>11)&31)/31.0f)*.299f+(float((p>>5)&63)/63.0f)*.587f+(float(p&31)/31.0f)*.114f);
  for(int f=0;f<3;++f)for(int i=0;i<kPixels;++i) {
    float value;memcpy(&value,kFrames[f]+i*sizeof(float),sizeof(value));inputs[f*kPixels+i]=quantize(value);
  }
  uint32_t rng=20261116u;
  for(int f=3;f<kInputs;++f)for(int i=0;i<kPixels;++i){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;inputs[f*kPixels+i]=int8_t(rng&255);}
  return true;
}
bool cameraInit() {
  camera_config_t c={};
  c.pin_pwdn=-1;c.pin_reset=-1;c.pin_xclk=15;c.pin_sccb_sda=4;c.pin_sccb_scl=5;
  c.pin_d0=11;c.pin_d1=9;c.pin_d2=8;c.pin_d3=10;c.pin_d4=12;c.pin_d5=18;c.pin_d6=17;c.pin_d7=16;
  c.pin_vsync=6;c.pin_href=7;c.pin_pclk=13;
  c.xclk_freq_hz=16000000;c.ledc_timer=LEDC_TIMER_0;c.ledc_channel=LEDC_CHANNEL_0;
  c.pixel_format=PIXFORMAT_RGB565;c.frame_size=FRAMESIZE_96X96;
  c.fb_count=1;c.fb_location=CAMERA_FB_IN_PSRAM;c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  const esp_err_t result=esp_camera_init(&c);
  printf("{\"event\":\"camera_init\",\"status\":%d,\"deinit_camera\":%d}\n",int(result),0);return result==ESP_OK;
}
void wifiEvent(void*,esp_event_base_t base,int32_t event,void* data) {
  if(base==WIFI_EVENT && event==WIFI_EVENT_STA_START) esp_wifi_connect();
  if(base==WIFI_EVENT && event==WIFI_EVENT_STA_DISCONNECTED) {
    if(measuring)++disconnections;
    const auto* reason=static_cast<wifi_event_sta_disconnected_t*>(data);
    printf("{\"event\":\"wifi_disconnected\",\"reason\":%u,\"measuring\":%s}\n",unsigned(reason->reason),measuring?"true":"false");
    xEventGroupClearBits(wifiEvents,1);
    esp_wifi_connect();
  }
  if(base==IP_EVENT && event==IP_EVENT_STA_GOT_IP) xEventGroupSetBits(wifiEvents,1);
}
bool network() {
  esp_err_t nvs=nvs_flash_init();
  if(nvs==ESP_ERR_NVS_NO_FREE_PAGES || nvs==ESP_ERR_NVS_NEW_VERSION_FOUND) {fail("nvs_requires_recovery");return false;}
  ESP_ERROR_CHECK(nvs);ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();
  wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifiEvent,nullptr));
  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifiEvent,nullptr));
  wifi_config_t wifi={};
  strncpy(reinterpret_cast<char*>(wifi.sta.ssid),WIFI_SSID,sizeof(wifi.sta.ssid));
  strncpy(reinterpret_cast<char*>(wifi.sta.password),WIFI_PASSWORD,sizeof(wifi.sta.password));
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));ESP_ERROR_CHECK(esp_wifi_start());
  ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
  if(!(xEventGroupWaitBits(wifiEvents,1,pdFALSE,pdFALSE,pdMS_TO_TICKS(30000))&1)) {return fail("wifi_connection");}
  return true;
}
bool reserveInternal(bool useInternal=true) {
  if(!memory("before_internal_allocation"))return false;
  internalRaw=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kActivationBytes+2*kGuardBytes,useInternal?kInternal:kPsram));
  if(!internalRaw)return fail("internal_allocation");
  memset(internalRaw,0xa5,kGuardBytes);memset(internalRaw+kGuardBytes+kActivationBytes,0xa5,kGuardBytes);
  reserveMonitoring=true;
  ESP_ERROR_CHECK(heap_caps_monitor_local_minimum_free_size_start());
  printf("{\"event\":\"arena_reserved\",\"allocation_order\":\"%s\",\"requested_bytes\":%u,\"internal\":%s}\n",kEarlyArena?"early":"late",unsigned(kActivationBytes+2*kGuardBytes),esp_ptr_internal(internalRaw)?"true":"false");
  return memory("after_internal_allocation");
}
const char* frameReason(frame_skip::Reason reason) {
  using frame_skip::Reason;
  switch (reason) {
    case Reason::Baseline: return "baseline";
    case Reason::First: return "first";
    case Reason::Change: return "change";
    case Reason::Refresh: return "refresh";
    case Reason::Similar: return "similar";
  }
  return "unknown";
}

void foregroundGrid(char (&grid)[145]) {
  for (int cell = 0; cell < 144; ++cell) {
    float first, second;
    memcpy(&first, transport::rx + 32 + (3 * cell + 1) * sizeof(float), sizeof(float));
    memcpy(&second, transport::rx + 32 + (3 * cell + 2) * sizeof(float), sizeof(float));
    grid[cell] = '0' + (first >= .5f) + 2 * (second >= .5f);
  }
  grid[144] = '\0';
}

bool run(bool cameraEnabled=true,bool useInternal=true,bool pauseCamera=false,bool diagnoseXclk=false,bool gateCamera=false,
         const frame_skip::Config* policyConfig=nullptr, int cameraFrames=kCameraFrames) {
  const bool captureCamera=cameraEnabled && !pauseCamera;
  if (!captureCamera) cameraFrames = 0;
  const auto config = policyConfig ? *policyConfig : frame_skip::Config{};
  const bool compareFrames = config.mode != frame_skip::Mode::Baseline;
  static_assert(kPixels == frame_skip::pixels);
  printf("{\"event\":\"configuration\",\"camera_enabled\":%s,\"camera_paused\":%s,\"activation_memory\":\"%s\"}\n",cameraEnabled?"true":"false",pauseCamera?"true":"false",useInternal?"internal":"psram");
  if(kEarlyArena && !reserveInternal(useInternal))return false;
  if(!buffers()||!transport::init())return false;
  if(!network())return false;
  wifi_ap_record_t ap={};ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap));
  printf("{\"event\":\"wifi_connected\",\"has_ip\":true,\"rssi_dbm\":%d,\"channel\":%u}\n",int(ap.rssi),unsigned(ap.primary));
  if(diagnoseXclk && (!xclk_probe::init(SERVER_BASE_URL) || !xclk_probe::phase(0,"baseline",false,false)))return fail("xclk_baseline");
  if((cameraEnabled && !cameraInit()) || !memory("services_ready"))return false;
  if(gateCamera && !gated_camera::park())return fail("camera_gate_park");
  printf("{\"event\":\"camera_clock_policy\",\"gated\":%s,\"settling_ms\":%u,\"discard_frames\":%u}\n",gateCamera?"true":"false",gateCamera?200:0,gateCamera?1:0);
  // Reference lives in PSRAM and is destroyed before constructing the candidate.
  // In early mode the internal block stays reserved throughout service startup.
  auto* reference=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,240*1024+2*kGuardBytes,kPsram));
  if(!reference)return fail("reference_arena");
  activation=reference+kGuardBytes;sciot_set_strip_rows(0);
  if(!create(kInt8Model,240*1024,false))return false;
  for(int f=0;f<kInputs;++f) {
    memcpy(runtime->input(0)->data.int8,inputs+f*kPixels,kPixels);
    if(!invoke(true))return false;
    memcpy(golden+f*kOutputBytes,runtime->output(0)->data.int8,kOutputBytes);
    if(f<3){printf("{\"event\":\"golden\",\"frame\":%d,\"activation_hex\":\"",kFrameIds[f]);hex(golden+f*kOutputBytes,kOutputBytes);printf("\"}\n");}
    vTaskDelay(1);
  }
  destroy();heap_caps_free(reference);activation=nullptr;
  if(!connected())return fail("wifi_not_connected_before_allocation");
  if(!kEarlyArena && !reserveInternal(useInternal))return false;
  if(!reservedGuards())return fail("reserved_guard_corrupted");
  activation=internalRaw+kGuardBytes;activeBytes=kActivationBytes;
  measuring=true;disconnections=0;
  sciot_set_strip_rows(3);
  if(!create(kNoPadModel,kActivationBytes,useInternal))return false;
  printf("{\"event\":\"candidate_allocated\",\"activation_bytes\":%u,\"guard_bytes_each\":32,\"internal\":%s,\"input_internal\":%s,\"output_internal\":%s,\"persistent_psram\":%s,\"strip_rows\":%d,\"scratch_bytes\":%d,\"arena_used\":%u,\"address\":\"%p\"}\n",
    unsigned(kActivationBytes),esp_ptr_internal(activation)?"true":"false",esp_ptr_internal(runtime->input(0)->data.int8)?"true":"false",esp_ptr_internal(runtime->output(0)->data.int8)?"true":"false",esp_ptr_external_ram(persistent)?"true":"false",sciot_get_strip_effective(),sciot_get_strip_bytes(),unsigned(runtime->arena_used_bytes()),activation);
  for(int f=0;f<kInputs;++f){
    memcpy(runtime->input(0)->data.int8,inputs+f*kPixels,kPixels);
    if(!invoke(false))return false;
    if(memcmp(runtime->output(0)->data.int8,golden+f*kOutputBytes,kOutputBytes))return fail("validation_mismatch");
    vTaskDelay(1);
  }
  printf("{\"event\":\"validation\",\"inputs\":35,\"exact\":true,\"guards\":true}\n");
  if(!memory("validation_done"))return false;
  if(diagnoseXclk){
    cam_stop();
    printf("{\"event\":\"xclk_camera_paused\",\"buffers_retained\":true,\"clock_not_disabled\":true}\n");
    const char* names[]={"on_1","off_1","on_2","off_2"};
    for(unsigned phase=1;phase<=4;++phase){
      const bool enabled=phase%2==1;
      if(!xclk_probe::clock(enabled,phase) || !xclk_probe::phase(phase,names[phase-1],true,enabled))return fail("xclk_phase");
      if(!memory("xclk_phase") || !guards() || !heap_caps_check_integrity_all(true))return fail("xclk_integrity");
    }
    xclk_probe::close();
    printf("{\"event\":\"done\",\"experiment\":\"xclk_diagnostic\",\"phases_completed\":5,\"probes_expected\":500,\"camera_completed\":0,\"validation_inputs\":35,\"guards\":true,\"heap_integrity\":true,\"wifi_disconnections\":%u}\n",unsigned(disconnections));
    measuring=false;reserveMonitoring=false;heap_caps_monitor_local_minimum_free_size_stop();destroy();return true;
  }
  if(pauseCamera){
    const size_t before=heap_caps_get_free_size(kInternal);
    cam_stop();vTaskDelay(pdMS_TO_TICKS(50));
    printf("{\"event\":\"camera_paused\",\"buffers_retained\":true,\"clock_not_disabled\":true,\"internal_free_before\":%u,\"internal_free_after\":%u}\n",unsigned(before),unsigned(heap_caps_get_free_size(kInternal)));
    if(!memory("camera_paused") || !heap_caps_check_integrity_all(true))return fail("camera_pause_state");
  }
  if(!transport::connect())return fail("transport_connect");
  if(!memory("socket_ready"))return false;
  if (policyConfig) {
    using frame_skip::Mode;
    printf("{\"event\":\"frame_policy_config\",\"mode\":\"%s\",\"metric\":\"%s\",\"threshold\":%d,\"refresh_ms\":%d,\"camera_frames\":%d,\"session_id\":\"%s\"}\n",
           config.mode == Mode::Baseline ? "baseline" : config.mode == Mode::Shadow ? "shadow" : "active",
           config.metric == frame_skip::Metric::Global ? "global" : "local",
           config.threshold, config.refreshMs, cameraFrames, transport::session);
  }
  for(int f=0;f<1100;++f){
    int c=f%3;memcpy(runtime->input(0)->data.int8,inputs+c*kPixels,kPixels);
    if(!invoke(false)||!transport::exchange(reinterpret_cast<uint8_t*>(runtime->output(0)->data.int8),c,f))return fail("deterministic_exchange");
    if(!memory("network"))return false;
    vTaskDelay(1);
  }
  std::unique_ptr<int8_t, decltype(&heap_caps_free)> policyStorage(
      compareFrames ? static_cast<int8_t*>(heap_caps_malloc(2 * kPixels, kPsram)) : nullptr,
      heap_caps_free);
  if (compareFrames && !policyStorage) return fail("frame_policy_psram");
  frame_skip::Policy policy(config, policyStorage.get());
  for(int f=0;f<cameraFrames;++f) {
    const int64_t start=esp_timer_get_time();camera_fb_t* fb=gateCamera?gated_camera::acquire(f):esp_camera_fb_get();const int64_t acquired=esp_timer_get_time();
    if(!fb || fb->len!=96*96*2 || fb->format!=PIXFORMAT_RGB565) {if(fb && !gateCamera)esp_camera_fb_return(fb);return fail("camera_frame");}
    auto* image = runtime->input(0)->data.int8;
    for(int i=0;i<kPixels;++i){const uint16_t p=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];image[i]=rgbLut[p];}
    const int64_t captureUs = int64_t(fb->timestamp.tv_sec) * 1000000 + fb->timestamp.tv_usec;
    const auto policyStart = policyConfig ? esp_timer_get_time() : 0;
    const int reference = policy.referenceFrame();
    const auto decision = policy.decide(image, captureUs);
    const bool send = decision.selected() || config.mode == frame_skip::Mode::Shadow;
    if (compareFrames && decision.selected()) policy.stage(image);
    const auto policyUs = policyConfig ? esp_timer_get_time() - policyStart : 0;
    int64_t invokeUs = 0;
    const bool ok = !send || invoke(false, &invokeUs);
    if (send && ok) memcpy(message+32,runtime->output(0)->data.int8,kOutputBytes);
    if(!gateCamera)esp_camera_fb_return(fb);
    if(gateCamera && !gated_camera::unchanged())return fail("camera_buffer_changed_before_send");
    if(!ok)return false;
    if (send) {
      if(!transport::exchange(message+32,1000+f,f))return fail("camera_exchange");
      if(gateCamera && !gated_camera::unchanged())return fail("camera_buffer_changed_during_send");
      if (compareFrames && decision.selected()) policy.acknowledge(captureUs, f);
    } else if (!connected() || disconnections || !guards()) {
      return fail("frame_skip_state");
    }
    const int64_t cycleUs = esp_timer_get_time() - start;
    printf("{\"event\":\"sample\",\"index\":%d,\"invoke_us\":%lld,\"acquisition_us\":%lld,\"local_cycle_us\":%lld,\"guards\":true,\"wifi_connected\":true,\"conv_calls\":%u,\"depthwise_calls\":%u,\"internal_free\":%u,\"internal_min_free\":%u,\"largest_block\":%u}\n",
      f,invokeUs,acquired-start,cycleUs,send?unsigned(sciotConvCalls):0,send?unsigned(sciotDepthwiseCalls):0,unsigned(heap_caps_get_free_size(kInternal)),unsigned(heap_caps_get_minimum_free_size(kInternal)),unsigned(heap_caps_get_largest_free_block(kInternal)));
    if (policyConfig) {
      char grid[145] = {};
      if (send) foregroundGrid(grid);
      printf("{\"event\":\"frame_policy\",\"index\":%d,\"capture_us\":%lld,\"reference_index\":%d,\"age_us\":%lld,\"difference\":%d,\"decision_us\":%lld,\"reason\":\"%s\",\"sent\":%s,\"http_connections\":%u,\"grid\":\"%s\"}\n",
             f, static_cast<long long>(captureUs), reference, static_cast<long long>(decision.ageUs),
             decision.difference, static_cast<long long>(policyUs), frameReason(decision.reason),
             send ? "true" : "false", transport::httpConnections, grid);
    }
    if(!memory("frame"))return false;
    if((f+1)%100==0) {
      for(int c=0;c<3;++c){memcpy(runtime->input(0)->data.int8,inputs+c*kPixels,kPixels);if(!invoke(false))return false;
        if(memcmp(runtime->output(0)->data.int8,golden+c*kOutputBytes,kOutputBytes))return fail("canonical_mismatch");}
      printf("{\"event\":\"canonical_check\",\"after_frames\":%d,\"inputs\":3,\"exact\":true,\"guards\":true}\n",f+1);
    }
    vTaskDelay(1);
  }
  if(gateCamera && !gated_camera::unchanged())return fail("camera_buffer_changed_at_end");
  if(!memory("end") || !connected() || disconnections || !guards())return fail("final_state");
  if(!heap_caps_check_integrity_all(true))return fail("heap_integrity");
  printf("{\"event\":\"done\",\"camera_completed\":%d,\"validation_inputs\":35,\"canonical_checks\":%d,\"all_exact\":true,\"guards\":true,\"wifi_disconnections\":%u,\"heap_integrity\":true,\"response_buffer_bytes\":%u}\n",cameraFrames,cameraFrames/100,unsigned(disconnections),unsigned(sizeof(response)));
  transport::disconnect();
  measuring=false;reserveMonitoring=false;heap_caps_monitor_local_minimum_free_size_stop();destroy();return true;
}

bool parseFramePolicy(const char* line, frame_skip::Config& config, int& cameraFrames) {
  char mode, metric, extra;
  int threshold, refresh;
  if (sscanf(line, "%c %c %3d %4d %4d %c", &mode, &metric, &threshold, &refresh, &cameraFrames, &extra) != 5 ||
      (mode != 'b' && mode != 's' && mode != 'a') || (metric != 'g' && metric != 'l') ||
      threshold < 1 || threshold > 255 || refresh < 1 || refresh > 5000 ||
      cameraFrames < 100 || cameraFrames > kCameraFrames) return false;
  using frame_skip::Mode;
  config = {mode == 'b' ? Mode::Baseline : mode == 's' ? Mode::Shadow : Mode::Active,
            metric == 'g' ? frame_skip::Metric::Global : frame_skip::Metric::Local,
            threshold, refresh};
  return true;
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment\":\"websocket_benchmark\",\"model_sha256\":\"%s\",\"reference_sha256\":\"%s\",\"cpu_mhz\":240,\"psram_mhz\":80,\"allocation_order\":\"%s\"}\n",kNoPadSha,kInt8Sha,kEarlyArena?"early":"late");
  ESP_ERROR_CHECK(resolver.AddAdd());ESP_ERROR_CHECK(resolver.AddConv2D());ESP_ERROR_CHECK(resolver.AddDepthwiseConv2D());
  ESP_ERROR_CHECK(resolver.AddPad(RegisterFastPad()));ESP_ERROR_CHECK(resolver.AddSoftmax());
  wifiEvents=xEventGroupCreate();
  if(!wifiEvents){fail("wifi_events");return;}
  printf("{\"event\":\"ready\",\"command\":\"w|h|c|W|H|C|r|p|x|1|2|3|F<mode> <metric> <threshold> <refresh_ms> <frames>\\n\"}\n");
  fcntl(fileno(stdin),F_SETFL,O_NONBLOCK);
  char policyLine[32] = {};
  size_t policyLength = 0;
  bool readingPolicy = false;
  for (;;) {
    int command = getchar();
    if (readingPolicy && command != EOF) {
      if (command == '\n' || command == '\r') {
        frame_skip::Config config;
        int cameraFrames = 0;
        readingPolicy = false;
        if (policyLength >= sizeof(policyLine) || !parseFramePolicy(policyLine, config, cameraFrames)) {
          fail("frame_policy_command");
        } else {
          transport::mode = 'h';
          run(true, true, false, false, true, &config, cameraFrames);
          for (;;) vTaskDelay(pdMS_TO_TICKS(100));
        }
      } else {
        if (policyLength < sizeof(policyLine) - 1) {
          policyLine[policyLength++] = char(command);
          policyLine[policyLength] = '\0';
        } else {
          policyLength = sizeof(policyLine);
        }
      }
      continue;
    }
    if (command == 'F') {
      readingPolicy = true;
      policyLength = 0;
      policyLine[0] = '\0';
      continue;
    }
    bool cameraEnabled=true,useInternal=true,pauseCamera=false,diagnoseXclk=false,gateCamera=false;
    if(command>='1' && command<='3'){gateCamera=true;command="whc"[command-'1'];}
    if(command=='x'){diagnoseXclk=true;command='h';}
    if(command=='r'){useInternal=false;command='h';}
    if(command=='p'){pauseCamera=true;command='h';}
    if(command=='W'||command=='H'||command=='C'){cameraEnabled=false;command+='a'-'A';}
    if(command=='w'||command=='h'||command=='c'){
      transport::mode=char(command);
      run(cameraEnabled,useInternal,pauseCamera,diagnoseXclk,gateCamera);
      for(;;)vTaskDelay(pdMS_TO_TICKS(100));
    }
    clearerr(stdin);
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
