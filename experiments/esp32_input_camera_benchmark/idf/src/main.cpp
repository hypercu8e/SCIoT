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
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "generated/assets.h"
#include "cJSON.h"
#include "esp_mac.h"
#include "network.local.h"


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
Model models[]={{"unused",nullptr,nullptr,nullptr,nullptr,nullptr},
                {"int8",kInt8Model,kInt8Sha,nullptr,nullptr,nullptr}};
float* canonical;
int variant=0;
bool localMode=false;
int8_t* rgbLut=nullptr;
int8_t grayLut[256];
const char* variantName() {
  static const char* names[]={"reference_hold","lut_hold","reference_early","lut_early","gray_early"};
  return names[variant];
}
float referenceGray(uint16_t p) {
  return (float((p>>11)&31)/31.0f)*.299f+(float((p>>5)&63)/63.0f)*.587f+(float(p&31)/31.0f)*.114f;
}
int8_t referenceQuant(float value) {
  const double q=std::nearbyint(double(value)/kInputScale+kInputZero);
  return int8_t(std::max(-128.0,std::min(127.0,q)));
}
bool makeLut() {
  const int64_t start=esp_timer_get_time();
  rgbLut=static_cast<int8_t*>(heap_caps_malloc(65536,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!rgbLut) return false;
  for(int p=0;p<65536;++p) rgbLut[p]=referenceQuant(referenceGray(uint16_t(p)));
  for(int p=0;p<256;++p) grayLut[p]=referenceQuant(float(p)/255.0f);
  printf("{\"event\":\"lut_ready\",\"bytes\":65536,\"initialization_us\":%lld}\n",esp_timer_get_time()-start);
  return true;
}

uint8_t* message;
uint8_t response[kReplyBytes];
EventGroupHandle_t wifiEvents;


// Diagnostic only: stop the camera driver while each frame is processed and sent.
#ifndef MULTICLIENT_DEINIT_CAMERA
#define MULTICLIENT_DEINIT_CAMERA 0
#endif
// Diagnostic only: after one camera frame, resend the embedded inputs instead.
#ifndef MULTICLIENT_EMBEDDED_AFTER_CAMERA
#define MULTICLIENT_EMBEDDED_AFTER_CAMERA 0
#endif
#ifndef MULTICLIENT_CAMERA_FRAMES
#define MULTICLIENT_CAMERA_FRAMES 1000
#endif
char clientId[32]={},sessionId[33]={},inferUrl[256]={};
uint64_t requestSequence=0;
struct ReplyIdentity {char client[65],session[65],sequence[65];};
esp_err_t onHttpEvent(esp_http_client_event_t* event) {
  if(event->event_id==HTTP_EVENT_ON_HEADER && event->user_data) {
    auto* identity=static_cast<ReplyIdentity*>(event->user_data);
    char* target=nullptr;
    if(strcasecmp(event->header_key,"x-client-id")==0) target=identity->client;
    if(strcasecmp(event->header_key,"x-session-id")==0) target=identity->session;
    if(strcasecmp(event->header_key,"x-request-id")==0) target=identity->sequence;
    if(target) snprintf(target,65,"%s",event->header_value);
  }
  return ESP_OK;
}
bool registerClient() {
  char url[256],body[256],response[1024]={};
  snprintf(url,sizeof(url),"%s/api/v2/registration",SERVER_BASE_URL);
  snprintf(inferUrl,sizeof(inferUrl),"%s/api/v2/infer",SERVER_BASE_URL);
  uint8_t mac[6];esp_efuse_mac_get_default(mac);
  snprintf(clientId,sizeof(clientId),"eye-%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
  snprintf(body,sizeof(body),"{\"client_id\":\"%s\",\"model_sha256\":\"%s\"}",clientId,kInt8Sha);
  esp_http_client_config_t config={};config.url=url;config.timeout_ms=15000;
  auto http=esp_http_client_init(&config);if(!http) return false;
  esp_http_client_set_method(http,HTTP_METHOD_POST);
  esp_http_client_set_header(http,"Content-Type","application/json");
  bool ok=esp_http_client_open(http,strlen(body))==ESP_OK;
  int sent=0;
  while(ok && sent<int(strlen(body))) {
    int n=esp_http_client_write(http,body+sent,strlen(body)-sent);
    if(n<=0) ok=false;else sent+=n;
  }
  int64_t length=ok?esp_http_client_fetch_headers(http):-1;
  ok=ok && esp_http_client_get_status_code(http)==200 && length>0 && length<int64_t(sizeof(response));
  int received=0;
  while(ok && received<length) {
    int n=esp_http_client_read(http,response+received,length-received);
    if(n<=0) ok=false;else received+=n;
  }
  esp_http_client_cleanup(http);
  auto json=ok?cJSON_Parse(response):nullptr;
  auto session=json?cJSON_GetObjectItem(json,"session_id"):nullptr;
  ok=cJSON_IsString(session) && strlen(session->valuestring)==32;
  if(ok) {snprintf(sessionId,sizeof(sessionId),"%s",session->valuestring);requestSequence=0;}
  cJSON_Delete(json);
  printf("{\"event\":\"registration\",\"client_id\":\"%s\",\"success\":%s}\n",clientId,ok?"true":"false");
  return ok;
}

uint32_t hash32(const uint8_t* p,size_t n) {
  uint32_t h=2166136261u; while(n--) {h^=*p++;h*=16777619u;} return h;
}
uint32_t crc32(const uint8_t* p,size_t n) {
  uint32_t crc=0xffffffffu;
  while(n--) {crc^=*p++;for(int b=0;b<8;++b) crc=(crc>>1)^(0xedb88320u&(0u-(crc&1u)));}
  return ~crc;
}
void fail(const char* reason) {printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);fflush(stdout);}
void memory() {
  printf("{\"event\":\"memory\",\"uptime_us\":%lld,\"internal_free\":%u,\"internal_min_free\":%u,\"psram_free\":%u,\"psram_min_free\":%u}\n",
    esp_timer_get_time(),unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM)));
}
void input(int mode) {
  auto& m=models[mode];
  if(!mode) memcpy(m.input->data.f,canonical,kPixels*sizeof(float));
  else for(int i=0;i<kPixels;++i) {
    const double value=std::nearbyint(double(canonical[i])/kInputScale+kInputZero);
    m.input->data.int8[i]=int8_t(std::max(-128.0,std::min(127.0,value)));
  }
}
struct Sample {
  int mode,frame,iteration; const char* source;
  int64_t acquisition,preprocess,prepare,invoke,packing,network,cycle;
  uint32_t activationHash,responseHash,serverDecode,serverInvoke,serverPost;
  int rssi;
  int64_t frameStart=0,frameDelivered=0,resultReady=0;
};
void emit(const Sample& s) {
  printf("{\"event\":\"frame_timing\",\"variant\":\"%s\",\"frame\":%d,\"iteration\":%d,\"source\":\"%s\",\"frame_start_us\":%lld,\"delivered_us\":%lld,\"result_us\":%lld,\"age_at_delivery_us\":%lld,\"age_at_result_us\":%lld}\n",
    variantName(),s.frame,s.iteration,s.source,s.frameStart,s.frameDelivered,s.resultReady,
    s.frameStart?s.frameDelivered-s.frameStart:0,s.frameStart?s.resultReady-s.frameStart:0);
  printf("{\"event\":\"measurement_transport\",\"frame\":%d,\"iteration\":%d,\"transport\":\"%s\"}\n",s.frame,s.iteration,localMode?"local_no_http":"http_v2");
  const int bytes=s.mode?4608:18432;
  printf("{\"event\":\"sample\",\"mode\":\"%s\",\"frame\":%d,\"iteration\":%d,"
    "\"source\":\"%s\",\"acquisition_us\":%lld,\"preprocessing_us\":%lld,"
    "\"input_prepare_us\":%lld,\"invoke_us\":%lld,\"packing_us\":%lld,"
    "\"request_response_us\":%lld,\"observed_cycle_us\":%lld,\"phase_sum_us\":%lld,"
    "\"server_decode_us\":%u,\"server_invoke_us\":%u,\"server_post_us\":%u,"
    "\"request_body_bytes\":%d,\"activation_bytes\":%d,\"image_bytes\":0,"
    "\"response_body_bytes\":%u,\"activation_fnv32\":%u,\"response_fnv32\":%u,\"rssi_dbm\":%d}\n",
    models[s.mode].name,s.frame,s.iteration,s.source,s.acquisition,s.preprocess,s.prepare,s.invoke,
    s.packing,s.network,s.cycle,s.acquisition+s.preprocess+s.prepare+s.invoke+s.packing+s.network,
    unsigned(s.serverDecode),unsigned(s.serverInvoke),unsigned(s.serverPost),(localMode?0:32+bytes),bytes,unsigned(localMode?0:kReplyBytes),
    unsigned(s.activationHash),unsigned(s.responseHash),s.rssi);
}
bool sample(int mode,int frame,int repetition,const char* source,Sample& s,
            int64_t cycleStart=0,int64_t acquisition=0,int64_t preprocessing=0,bool quantized=false) {
  if(!localMode && !sessionId[0] && !registerClient()) {vTaskDelay(pdMS_TO_TICKS(500));return false;}
  ReplyIdentity replyIdentity={};
  const uint64_t sequence=requestSequence++;
  char sequenceText[24];snprintf(sequenceText,sizeof(sequenceText),"%llu",(unsigned long long)sequence);
  auto& m=models[mode];
  const int64_t start=esp_timer_get_time();
  if(!quantized) input(mode); // Invoke may reuse input memory: restore it for every call.
  const int64_t prepared=esp_timer_get_time();
  if(m.runtime->Invoke()!=kTfLiteOk) {fail("invoke");return false;}
  const int64_t invoked=esp_timer_get_time();
  uint32_t header[8]={0x31424353,1,uint32_t(mode),uint32_t(frame),uint32_t(repetition),0,uint32_t(m.output->bytes),0};
  memcpy(message+32,m.output->data.uint8,m.output->bytes);
  header[7]=crc32(message+32,m.output->bytes);memcpy(message,header,32);
  const int64_t packed=esp_timer_get_time();
  if(localMode) {
    s={mode,frame,repetition,source,acquisition,preprocessing,prepared-start,invoked-prepared,
       packed-invoked,0,packed-(cycleStart?cycleStart:start),hash32(message+32,m.output->bytes),0,0,0,0,0};
    s.resultReady=packed;return true;
  }
  esp_http_client_config_t config={};
  config.url=inferUrl;config.timeout_ms=15000;config.buffer_size=2048;config.buffer_size_tx=1024;
  config.event_handler=onHttpEvent; config.user_data=&replyIdentity;
  esp_http_client_handle_t http=esp_http_client_init(&config);
  if(!http) {fail("http_init");return false;}
  esp_http_client_set_method(http,HTTP_METHOD_POST);
  esp_http_client_set_header(http,"Content-Type","application/octet-stream");
  esp_http_client_set_header(http,"X-Model-SHA256",m.sha);
  esp_http_client_set_header(http,"Connection","close");
  esp_http_client_set_header(http,"X-Client-ID",clientId);
  esp_http_client_set_header(http,"X-Session-ID",sessionId);
  esp_http_client_set_header(http,"X-Request-ID",sequenceText);
  const int bodyBytes=32+m.output->bytes;
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
  const int httpStatus=esp_http_client_get_status_code(http);
  esp_http_client_cleanup(http);
  if(httpStatus==429) {
    printf("{\"event\":\"rejected\",\"status\":429,\"request_id\":%llu}\n",(unsigned long long)sequence);
    vTaskDelay(pdMS_TO_TICKS(250+(esp_random()%251)));return false;
  }
  if(httpStatus!=200 || received!=kReplyBytes) {sessionId[0]=0;}
  uint32_t reply[8];memcpy(reply,response,32);
  if(strcmp(replyIdentity.client,clientId)!=0 || strcmp(replyIdentity.session,sessionId)!=0 ||
     strcmp(replyIdentity.sequence,sequenceText)!=0 || received!=kReplyBytes || reply[0]!=0x31524353 || reply[1]!=1 ||
     reply[2]!=uint32_t(frame) || reply[3]!=uint32_t(repetition) || reply[4]!=432) {
    printf("{\"event\":\"error\",\"reason\":\"http_response\",\"code\":%d,\"http_status\":%d,\"received\":%d,\"length\":%lld}\n",int(status),httpStatus,received,length);sessionId[0]=0;return false;
  }
  wifi_ap_record_t ap={};esp_wifi_sta_get_ap_info(&ap);
  printf("{\"event\":\"correlation\",\"client_id\":\"%s\",\"session_id\":\"%s\",\"request_id\":%llu,\"frame\":%d,\"iteration\":%d}\n",
         clientId,sessionId,(unsigned long long)sequence,frame,repetition);
  s={mode,frame,repetition,source,acquisition,preprocessing,prepared-start,invoked-prepared,
     packed-invoked,finished-packed,finished-(cycleStart?cycleStart:start),
     hash32(message+32,m.output->bytes),hash32(response,kReplyBytes),reply[5],reply[6],reply[7],ap.rssi};
  s.resultReady=finished;
  return true;
}
bool cameraInit() {
  camera_config_t c={};
  c.pin_pwdn=-1;c.pin_reset=-1;c.pin_xclk=15;c.pin_sccb_sda=4;c.pin_sccb_scl=5;
  c.pin_d0=11;c.pin_d1=9;c.pin_d2=8;c.pin_d3=10;c.pin_d4=12;c.pin_d5=18;c.pin_d6=17;c.pin_d7=16;
  c.pin_vsync=6;c.pin_href=7;c.pin_pclk=13;
  c.xclk_freq_hz=16000000;c.ledc_timer=LEDC_TIMER_0;c.ledc_channel=LEDC_CHANNEL_0;
  c.pixel_format=variant==4?PIXFORMAT_GRAYSCALE:PIXFORMAT_RGB565;c.frame_size=FRAMESIZE_96X96;
  c.fb_count=1;c.fb_location=CAMERA_FB_IN_PSRAM;c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  const esp_err_t result=esp_camera_init(&c);
  printf("{\"event\":\"camera_init\",\"status\":%d,\"deinit_camera\":%d}\n",int(result),MULTICLIENT_DEINIT_CAMERA);return result==ESP_OK;
}
bool capture(Sample& s,int mode,int frame,int iteration) {
  const int64_t start=esp_timer_get_time();
  camera_fb_t* fb=esp_camera_fb_get();
  const int64_t acquired=esp_timer_get_time();
  const bool gray=variant==4, lut=variant==1 || variant==3 || gray;
  if(!fb || fb->len!=size_t(kPixels*(gray?1:2)) || fb->format!=(gray?PIXFORMAT_GRAYSCALE:PIXFORMAT_RGB565)) {
    if(fb) esp_camera_fb_return(fb);
    fail("camera_frame");return false;
  }
  const int64_t frameStart=int64_t(fb->timestamp.tv_sec)*1000000+fb->timestamp.tv_usec;
  for(int i=0;i<kPixels;++i) {
    if(gray) models[mode].input->data.int8[i]=grayLut[fb->buf[i]];
    else {
      const uint16_t p=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];
      if(lut) models[mode].input->data.int8[i]=rgbLut[p];
      else canonical[i]=referenceGray(p);
    }
  }
  const int64_t processed=esp_timer_get_time();
  if(variant>=2) {esp_camera_fb_return(fb);fb=nullptr;}
  const bool ok=sample(mode,frame,iteration,"camera",s,start,acquired-start,processed-acquired,lut);
  s.frameStart=frameStart;s.frameDelivered=acquired;
  if(fb) esp_camera_fb_return(fb);
  return ok;
}
bool validateInput() {
  variant=0;
  // Independent original two-pass conversion, including its double rounding.
  int mismatches=0;
  for(int base=0;base<65536;base+=kPixels) {
    const int n=std::min(kPixels,65536-base);
    for(int i=0;i<n;++i) {
      const uint16_t p=base+i;
      canonical[i]=(float((p>>11)&31)/31.0f)*.299f+(float((p>>5)&63)/63.0f)*.587f+(float(p&31)/31.0f)*.114f;
    }
    input(1);
    for(int i=0;i<n;++i) if(models[1].input->data.int8[i]!=rgbLut[base+i]) ++mismatches;
  }
  printf("{\"event\":\"exhaustive_validation\",\"colors\":65536,\"mismatches\":%d}\n",mismatches);
  if(mismatches) {fail("lut_mismatch");return false;}
  auto* savedInput=static_cast<int8_t*>(heap_caps_malloc(kPixels,MALLOC_CAP_SPIRAM));
  auto* savedOutput=static_cast<int8_t*>(heap_caps_malloc(4608,MALLOC_CAP_SPIRAM));
  if(!savedInput || !savedOutput) {free(savedInput);free(savedOutput);fail("validation_buffers");return false;}
  bool ok=cameraInit();
  for(int f=0;ok && f<100;++f) {
    auto* fb=esp_camera_fb_get();
    if(!fb || fb->len!=kPixels*2) {if(fb) esp_camera_fb_return(fb);ok=false;break;}
    for(int i=0;i<kPixels;++i) {
      const uint16_t p=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];
      canonical[i]=(float((p>>11)&31)/31.0f)*.299f+(float((p>>5)&63)/63.0f)*.587f+(float(p&31)/31.0f)*.114f;
    }
    input(1);memcpy(savedInput,models[1].input->data.int8,kPixels);
    ok=models[1].runtime->Invoke()==kTfLiteOk;
    memcpy(savedOutput,models[1].output->data.int8,4608);
    for(int i=0;i<kPixels;++i) {
      const uint16_t p=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];
      models[1].input->data.int8[i]=rgbLut[p];
    }
    ok=ok && memcmp(savedInput,models[1].input->data.int8,kPixels)==0;
    ok=ok && models[1].runtime->Invoke()==kTfLiteOk;
    ok=ok && memcmp(savedOutput,models[1].output->data.int8,4608)==0;
    esp_camera_fb_return(fb);
    // Restore the same input and also verify inference during camera refilling.
    memcpy(models[1].input->data.int8,savedInput,kPixels);
    ok=ok && models[1].runtime->Invoke()==kTfLiteOk;
    ok=ok && memcmp(savedOutput,models[1].output->data.int8,4608)==0;
    printf("{\"event\":\"paired_validation\",\"frame\":%d,\"exact\":%s}\n",f,ok?"true":"false");
    if(f%10==9) vTaskDelay(1);
  }
  esp_camera_deinit();free(savedInput);free(savedOutput);
  if(!ok) fail("paired_input_activation_mismatch");
  printf("{\"event\":\"validation_done\",\"success\":%s}\n",ok?"true":"false");
  return ok;
}

void run(char command) {
  // Commands may be separated by more than the server's idle-session timeout.
  // Register before producing samples so each run starts with a live session.
  sessionId[0]=0;
  if(!localMode && !registerClient()) {fail("registration");return;}
  printf("{\"event\":\"run_config\",\"variant\":\"%s\"}\n",variantName());
  Sample row;
  for(int f=0;f<3;++f) {
    memcpy(canonical,kFrames[f],kPixels*sizeof(float));
    for(int n=0;n<2;++n) { input(1); if(models[1].runtime->Invoke()!=kTfLiteOk) {fail("warmup");return;} }
    for(int n=0;n<kRepeats;++n) { if(sample(1,kFrameIds[f],n,"embedded",row)) emit(row); if(localMode && n%10==9) vTaskDelay(1); }
  }
  if(!cameraInit()) {fail("camera_init");return;}
  if(MULTICLIENT_EMBEDDED_AFTER_CAMERA) {
    camera_fb_t* fb=esp_camera_fb_get();
    printf("{\"event\":\"diagnostic_frame\",\"ok\":%d}\n",fb?1:0);
    if(fb) esp_camera_fb_return(fb);
    esp_camera_deinit();
    int ok=0;
    for(int f=0;f<3;++f) {
      memcpy(canonical,kFrames[f],kPixels*sizeof(float));
      for(int n=0;n<kRepeats;++n) if(sample(1,kFrameIds[f],100+n,"embedded_after_camera",row)) {emit(row);++ok;}
    }
    printf("{\"event\":\"diagnostic_done\",\"embedded_after_camera_completed\":%d}\n",ok);
    return;
  }
  for(int w=0;w<20;++w) {if(!capture(row,1,500+w,w)) {fail("camera_warmup");esp_camera_deinit();return;} if(localMode && w%10==9) vTaskDelay(1);}
  const int64_t start=esp_timer_get_time();
  const int frames=localMode?200:command=='s'?20:MULTICLIENT_CAMERA_FRAMES;
  const int64_t duration=command=='h'?3600000000LL:command=='i'?180000000LL:0;
  int completed=0,n=0;
  memory();
  for(;duration?(esp_timer_get_time()-start<duration):(n<frames);++n) {
    if(capture(row,1,1000+n,n)) { emit(row); ++completed; }
    if(localMode && n%10==9) vTaskDelay(1);
    if(n%50==49) memory();
    fflush(stdout);
  }
  printf("{\"event\":\"done\",\"camera_attempted\":%d,\"camera_completed\":%d,\"elapsed_us\":%lld}\n",
         n,completed,esp_timer_get_time()-start);
  esp_camera_deinit();
  memory();
}
void wifiEvent(void*,esp_event_base_t base,int32_t event,void* data) {
  if(base==WIFI_EVENT && event==WIFI_EVENT_STA_START) esp_wifi_connect();
  if(base==WIFI_EVENT && event==WIFI_EVENT_STA_DISCONNECTED) {
    const auto* reason=static_cast<wifi_event_sta_disconnected_t*>(data);
    printf("{\"event\":\"wifi_disconnected\",\"reason\":%u}\n",unsigned(reason->reason));
    xEventGroupClearBits(wifiEvents,1);
    esp_wifi_connect();
  }
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
  message=static_cast<uint8_t*>(heap_caps_malloc(32+4608,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!canonical || !message) {fail("buffers");return;}
  for(int mode=1;mode<2;++mode) {
    auto& m=models[mode];
    auto* arena=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,kArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!arena) {fail("arena");return;}
    m.runtime=new tflite::MicroInterpreter(tflite::GetModel(m.binary),resolver,arena,kArenaBytes);
    if(m.runtime->AllocateTensors()!=kTfLiteOk) {fail("allocate_tensors");return;}
    m.input=m.runtime->input(0);m.output=m.runtime->output(0);
    printf("{\"event\":\"allocated\",\"mode\":\"%s\",\"arena_used_bytes\":%u,\"model_sha256\":\"%s\",\"input_bytes\":%u,\"output_bytes\":%u}\n",
      m.name,unsigned(m.runtime->arena_used_bytes()),m.sha,unsigned(m.input->bytes),unsigned(m.output->bytes));
  }
  if(!makeLut()) {fail("lut_allocation");return;}
  memcpy(canonical,kFrames[0],kPixels*sizeof(float));
  for(int mode=1;mode<2;++mode) {
    sciotConvCalls=0;sciotDepthwiseCalls=0;input(mode);
    if(models[mode].runtime->Invoke()!=kTfLiteOk) {fail("kernel_probe_invoke");return;}
    printf("{\"event\":\"kernel_check\",\"mode\":\"%s\",\"esp32s3_conv_calls\":%u,\"esp32s3_depthwise_calls\":%u}\n",
      models[mode].name,unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls));
    if((mode==0 && (sciotConvCalls || sciotDepthwiseCalls)) ||
       (mode==1 && (!sciotConvCalls || !sciotDepthwiseCalls))) {fail("optimized_kernel_not_reached");return;}
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
    int c=getchar();
    if(c=='g' || c=='s' || c=='i' || c=='h') {
      run(char(c));printf("{\"event\":\"ready\",\"command\":\"g/s/i/h\"}\n");
    }
    if(c>='0' && c<='4') {variant=c-'0';printf("{\"event\":\"configured\",\"variant\":\"%s\"}\n",variantName());}
    if(c=='v') {validateInput();printf("{\"event\":\"ready\"}\n");}
    if(c=='d') {localMode=true;run('g');localMode=false;printf("{\"event\":\"ready\"}\n");}
    if(c=='r') esp_restart();
    clearerr(stdin);
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
