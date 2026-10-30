#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
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
#include "sciot_miniz.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "generated/assets.h"
#include "generated/quality.h"
#include "network.local.h"

extern const uint8_t qualityInputs[] asm("_binary_quality_inputs_bin_start");
extern uint32_t sciotConvCalls,sciotDepthwiseCalls;

#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error This benchmark requires the official ESP-NN kernel integration
#endif

namespace {
constexpr size_t kArenaBytes=1024*1024;
constexpr int kRepeats=20, kLivePairs=20;
constexpr size_t kReplyBytes=32+432*4;
tflite::MicroMutableOpResolver<5> resolver;
struct Model { const char* name; const uint8_t* binary; const char* sha;
  tflite::MicroInterpreter* runtime; TfLiteTensor* input; TfLiteTensor* output; };
Model models[]={{"raw",kInt8Model,kInt8Sha,nullptr,nullptr,nullptr},
                {"zlib",kInt8Model,kInt8Sha,nullptr,nullptr,nullptr}};
mz_stream compressor={};
uint8_t* compressed;
size_t codecAllocatedBytes=0;
void* codecAlloc(void*,size_t count,size_t size) {
  void* p=heap_caps_calloc(count,size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(p) codecAllocatedBytes+=count*size;
  return p;
}
void codecFree(void*,void* p) {heap_caps_free(p);}
float* canonical;
uint8_t* message;
uint8_t response[kReplyBytes];
EventGroupHandle_t wifiEvents;

uint32_t hash32(const uint8_t* p,size_t n) {
  uint32_t h=2166136261u; while(n--) {h^=*p++;h*=16777619u;} return h;
}
uint32_t crc32(const uint8_t* p,size_t n) {
  uint32_t crc=0xffffffffu;
  while(n--) {crc^=*p++;for(int b=0;b<8;++b) crc=(crc>>1)^(0xedb88320u&(0u-(crc&1u)));}
  return ~crc;
}
void fail(const char* reason) {printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);fflush(stdout);}
void input(int mode) {
  auto& m=models[mode];
  for(int i=0;i<kPixels;++i) {
    const double value=std::nearbyint(double(canonical[i])/kInputScale+kInputZero);
    m.input->data.int8[i]=int8_t(std::max(-128.0,std::min(127.0,value)));
  }
}
struct Sample {
  int mode,frame,iteration; const char* source;
  int64_t acquisition,preprocess,prepare,invoke,packing,network,cycle,compression;
  int wireBytes;
  uint32_t activationHash,responseHash,serverDecode,serverInvoke,serverPost;
  int rssi;
};
void emit(const Sample& s) {
  const int bytes=4608;
  printf("{\"event\":\"sample\",\"mode\":\"%s\",\"frame\":%d,\"iteration\":%d,"
    "\"source\":\"%s\",\"acquisition_us\":%lld,\"preprocessing_us\":%lld,"
    "\"input_prepare_us\":%lld,\"invoke_us\":%lld,\"packing_us\":%lld,"
    "\"request_response_us\":%lld,\"observed_cycle_us\":%lld,\"phase_sum_us\":%lld,"
    "\"compression_us\":%lld,\"wire_bytes\":%d,"
    "\"server_decode_us\":%u,\"server_invoke_us\":%u,\"server_post_us\":%u,"
    "\"request_body_bytes\":%d,\"activation_bytes\":%d,\"image_bytes\":0,"
    "\"response_body_bytes\":%u,\"activation_fnv32\":%u,\"response_fnv32\":%u,\"rssi_dbm\":%d}\n",
    models[s.mode].name,s.frame,s.iteration,s.source,s.acquisition,s.preprocess,s.prepare,s.invoke,
    s.packing,s.network,s.cycle,s.acquisition+s.preprocess+s.prepare+s.invoke+s.packing+s.network+s.compression,
    s.compression,s.wireBytes,
    unsigned(s.serverDecode),unsigned(s.serverInvoke),unsigned(s.serverPost),32+s.wireBytes,bytes,unsigned(kReplyBytes),
    unsigned(s.activationHash),unsigned(s.responseHash),s.rssi);
}
bool sample(int mode,int frame,int repetition,const char* source,Sample& s,
            int64_t cycleStart=0,int64_t acquisition=0,int64_t preprocessing=0) {
  auto& m=models[mode];
  const int64_t start=esp_timer_get_time();
  input(mode); // Invoke may reuse input memory: restore it for every call.
  const int64_t prepared=esp_timer_get_time();
  if(m.runtime->Invoke()!=kTfLiteOk) {fail("invoke");return false;}
  const int64_t invoked=esp_timer_get_time();
  const uint32_t checksum=crc32(m.output->data.uint8,m.output->bytes);
  const int64_t compressionStart=esp_timer_get_time();
  size_t wireBytes=m.output->bytes;
  const uint8_t* payload=m.output->data.uint8;
  if(mode==1) {
    if(mz_deflateReset(&compressor)!=MZ_OK) {fail("codec_reset");return false;}
    compressor.next_in=m.output->data.uint8;compressor.avail_in=m.output->bytes;
    compressor.next_out=compressed;compressor.avail_out=8192;
    if(mz_deflate(&compressor,MZ_FINISH)!=MZ_STREAM_END || compressor.avail_in) {fail("codec_compress");return false;}
    wireBytes=compressor.total_out;payload=compressed;
  }
  const int64_t compressionUs=mode?esp_timer_get_time()-compressionStart:0;
  uint32_t header[8]={0x32434353,2,uint32_t(mode),uint32_t(frame),uint32_t(repetition),4608,uint32_t(wireBytes),checksum};
  memcpy(message+32,payload,wireBytes);memcpy(message,header,32);
  const int64_t packed=esp_timer_get_time();
  esp_http_client_config_t config={};
  config.url=SERVER_URL;config.timeout_ms=15000;config.buffer_size=2048;config.buffer_size_tx=1024;
  esp_http_client_handle_t http=esp_http_client_init(&config);
  if(!http) {fail("http_init");return false;}
  esp_http_client_set_method(http,HTTP_METHOD_POST);
  esp_http_client_set_header(http,"Content-Type","application/octet-stream");
  esp_http_client_set_header(http,"X-Model-SHA256",m.sha);
  esp_http_client_set_header(http,"Connection","close");
  const int bodyBytes=32+wireBytes;
  esp_err_t status=esp_http_client_open(http,bodyBytes);
  int sent=0;
  while(status==ESP_OK && sent<bodyBytes) {
    int n=esp_http_client_write(http,reinterpret_cast<char*>(message)+sent,bodyBytes-sent);
    if(n<=0) {status=ESP_FAIL;break;} sent+=n;
  }
  int64_t length=-1;
  if(status==ESP_OK) length=esp_http_client_fetch_headers(http);
  int received=0;
  if(status==ESP_OK && esp_http_client_get_status_code(http)==200 && length==kReplyBytes) {
    while(received<int(kReplyBytes)) {
      int n=esp_http_client_read(http,reinterpret_cast<char*>(response)+received,kReplyBytes-received);
      if(n<=0) break;
      received+=n;
    }
  }
  const int64_t finished=esp_timer_get_time();
  esp_http_client_cleanup(http);
  uint32_t reply[8];memcpy(reply,response,32);
  if(received!=kReplyBytes || reply[0]!=0x31524353 || reply[1]!=2 ||
     reply[2]!=uint32_t(frame) || reply[3]!=uint32_t(repetition) || reply[4]!=432) {
    printf("{\"event\":\"error\",\"reason\":\"http_response\",\"code\":%d,\"received\":%d,\"length\":%lld}\n",int(status),received,length);return false;
  }
  wifi_ap_record_t ap={};esp_wifi_sta_get_ap_info(&ap);
  s={mode,frame,repetition,source,acquisition,preprocessing,prepared-start,invoked-prepared,
     packed-invoked-compressionUs,finished-packed,finished-(cycleStart?cycleStart:start),compressionUs,int(wireBytes),
     hash32(m.output->data.uint8,m.output->bytes),hash32(response,kReplyBytes),reply[5],reply[6],reply[7],ap.rssi};
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
  printf("{\"event\":\"camera_init\",\"status\":%d}\n",int(result));return result==ESP_OK;
}
bool capture(Sample& s,int mode,int frame,int iteration) {
  const int64_t start=esp_timer_get_time();
  camera_fb_t* fb=esp_camera_fb_get();
  const int64_t acquired=esp_timer_get_time();
  if(!fb || fb->len!=96*96*2 || fb->format!=PIXFORMAT_RGB565) {
    if(fb) esp_camera_fb_return(fb);
    fail("camera_frame");return false;
  }
  for(int i=0;i<kPixels;++i) {
    const uint16_t p=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];
    canonical[i]=(float((p>>11)&31)/31.0f)*.299f+(float((p>>5)&63)/63.0f)*.587f+(float(p&31)/31.0f)*.114f;
  }
  esp_camera_fb_return(fb);
  const int64_t processed=esp_timer_get_time();
  return sample(mode,frame,iteration,"camera",s,start,acquired-start,processed-acquired);
}
void run() {
  Sample row;
  for(int f=0;f<3;++f) {
    memcpy(canonical,kFrames[f],kPixels*sizeof(float));
    for(int mode=0;mode<2;++mode) for(int n=0;n<2;++n) {
      input(mode);if(models[mode].runtime->Invoke()!=kTfLiteOk) {fail("warmup");return;}
    }
    for(int n=0;n<kRepeats;++n) for(int p=0;p<2;++p) {
      if(!sample((n+p)%2,kFrameIds[f],n,"embedded",row)) return;
      emit(row);fflush(stdout);
    }
  }
  printf("{\"event\":\"quality_start\",\"count\":%d,\"input_sha256\":\"%s\"}\n",kQualityCount,kQualitySha);
  for(int f=0;f<kQualityCount;++f) {
    memcpy(canonical,qualityInputs+f*kPixels*sizeof(float),kPixels*sizeof(float));
    for(int p=0;p<2;++p) {
      if(!sample((f+p)%2,3000+f,0,"annotated",row)) return;
      emit(row);fflush(stdout);
    }
  }
  if(!cameraInit()) {fail("camera_init");return;}
  for(int n=0;n<kLivePairs;++n) for(int p=0;p<2;++p) {
    if(!capture(row,(n+p)%2,1000+2*n+p,n)) return;
    emit(row);fflush(stdout);
  }
  // Continuous batches buffer serial output until after the timed interval.
  Sample batch[20];
  for(int round=0;round<2;++round) for(int position=0;position<2;++position) {
    int mode=(round+position)%2;
    const int64_t start=esp_timer_get_time();
    for(int n=0;n<20;++n) if(!capture(batch[n],mode,2000+round*40+position*20+n,round)) return;
    const int64_t elapsed=esp_timer_get_time()-start;
    for(const auto& value:batch) emit(value);
    printf("{\"event\":\"throughput\",\"mode\":\"%s\",\"round\":%d,\"frames\":20,\"elapsed_us\":%lld}\n",models[mode].name,round,elapsed);
    fflush(stdout);
  }
  esp_camera_deinit();
  printf("{\"event\":\"done\",\"embedded_pairs\":%d,\"camera_pairs_requested\":%d}\n",3*kRepeats,kLivePairs);
  fflush(stdout);
}
void wifiEvent(void*,esp_event_base_t base,int32_t event,void*) {
  if(base==WIFI_EVENT && event==WIFI_EVENT_STA_START) esp_wifi_connect();
  if(base==IP_EVENT && event==IP_EVENT_STA_GOT_IP) xEventGroupSetBits(wifiEvents,1);
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);
  vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment_sha256\":\"%s\",\"cpu_mhz\":240,\"runtime\":\"esp-tflite-micro-dd40859\","
    "\"arena_capacity_each\":%u,\"arena_in_psram\":true,\"esp_nn_enabled\":true,\"repetitions\":%d}\n",kExperimentSha,unsigned(kArenaBytes),kRepeats);
  ESP_ERROR_CHECK(resolver.AddAdd());ESP_ERROR_CHECK(resolver.AddConv2D());
  ESP_ERROR_CHECK(resolver.AddDepthwiseConv2D());ESP_ERROR_CHECK(resolver.AddPad());ESP_ERROR_CHECK(resolver.AddSoftmax());
  canonical=static_cast<float*>(heap_caps_aligned_alloc(16,kPixels*4,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  message=static_cast<uint8_t*>(heap_caps_malloc(32+8192,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  compressed=static_cast<uint8_t*>(heap_caps_malloc(8192,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!canonical || !message || !compressed) {fail("buffers");return;}
  compressor.zalloc=codecAlloc;compressor.zfree=codecFree;
  if(mz_deflateInit(&compressor,1)!=MZ_OK || mz_deflateBound(&compressor,4608)>8192) {fail("codec_init");return;}
  printf("{\"event\":\"codec_allocated\",\"codec\":\"miniz-3.0.2-level1\",\"workspace_bytes\":%u,\"compressed_capacity_bytes\":8192,\"message_capacity_bytes\":8224}\n",unsigned(codecAllocatedBytes));
  for(int modelIndex=0;modelIndex<1;++modelIndex) {
    auto& m=models[modelIndex];
    auto* arena=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!arena) {fail("arena");return;}
    m.runtime=new tflite::MicroInterpreter(tflite::GetModel(m.binary),resolver,arena,kArenaBytes);
    if(m.runtime->AllocateTensors()!=kTfLiteOk) {fail("allocate_tensors");return;}
    m.input=m.runtime->input(0);m.output=m.runtime->output(0);
    printf("{\"event\":\"allocated\",\"mode\":\"%s\",\"arena_used_bytes\":%u,\"model_sha256\":\"%s\",\"input_bytes\":%u,\"output_bytes\":%u}\n",
      m.name,unsigned(m.runtime->arena_used_bytes()),m.sha,unsigned(m.input->bytes),unsigned(m.output->bytes));
  }
  models[1].runtime=models[0].runtime;models[1].input=models[0].input;models[1].output=models[0].output;
  memcpy(canonical,kFrames[0],kPixels*sizeof(float));
  for(int mode=0;mode<2;++mode) {
    sciotConvCalls=0;sciotDepthwiseCalls=0;input(mode);
    if(models[mode].runtime->Invoke()!=kTfLiteOk) {fail("kernel_probe_invoke");return;}
    printf("{\"event\":\"kernel_check\",\"mode\":\"%s\",\"esp32s3_conv_calls\":%u,\"esp32s3_depthwise_calls\":%u}\n",
      models[mode].name,unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls));
    if(!sciotConvCalls || !sciotDepthwiseCalls) {fail("optimized_kernel_not_reached");return;}
  }
  esp_err_t nvs=nvs_flash_init();
  if(nvs==ESP_ERR_NVS_NO_FREE_PAGES || nvs==ESP_ERR_NVS_NEW_VERSION_FOUND) {ESP_ERROR_CHECK(nvs_flash_erase());nvs=nvs_flash_init();}
  ESP_ERROR_CHECK(nvs);ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();wifiEvents=xEventGroupCreate();
  wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifiEvent,nullptr));
  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifiEvent,nullptr));
  wifi_config_t wifi={};
  strncpy(reinterpret_cast<char*>(wifi.sta.ssid),WIFI_SSID,sizeof(wifi.sta.ssid));
  strncpy(reinterpret_cast<char*>(wifi.sta.password),WIFI_PASSWORD,sizeof(wifi.sta.password));
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));ESP_ERROR_CHECK(esp_wifi_start());
  ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
  if(!(xEventGroupWaitBits(wifiEvents,1,pdFALSE,pdFALSE,pdMS_TO_TICKS(30000))&1)) {fail("wifi_connection");return;}
  printf("{\"event\":\"ready\",\"command\":\"g\"}\n");
  fcntl(fileno(stdin),F_SETFL,O_NONBLOCK);
  for(;;) {
    int c=getchar();if(c=='g') {run();break;} if(c=='r') esp_restart();clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(10));
  }
}
