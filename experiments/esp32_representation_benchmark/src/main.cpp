#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <esp_camera.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "generated/assets.h"
#include "network.local.h"

namespace {
constexpr size_t kArenaBytes = 1024*1024;
constexpr int kWarmups = 2;
constexpr int kRepetitions = 6;
constexpr int kLivePairs = 6;
constexpr size_t kMaxBody = 32+96*96*2+24*24*8*4;
constexpr size_t kResponseBytes = 32+432*4;
tflite::MicroErrorReporter reporter;
tflite::MicroMutableOpResolver<5> resolver;
struct Model {
  const char* name;
  const uint8_t* binary;
  const char* sha;
  tflite::MicroInterpreter* runtime;
  TfLiteTensor* input;
  TfLiteTensor* output;
};
Model models[] = {{"float32",kFloatModel,kFloatSha,nullptr,nullptr,nullptr},
                  {"int8",kInt8Model,kInt8Sha,nullptr,nullptr,nullptr}};
float* canonical = nullptr;
uint8_t* message = nullptr;
uint8_t response[kResponseBytes];
uint32_t firstHash[2][3] = {};
bool ready = false;

uint32_t hash32(const uint8_t* p, size_t n) {
  uint32_t hash=2166136261u;
  while(n--) {hash ^= *p++;hash *= 16777619u;}
  return hash;
}
uint32_t crc32(const uint8_t* p, size_t n) {
  uint32_t crc=0xffffffffu;
  while(n--) {
    crc ^= *p++;
    for(int bit=0;bit<8;++bit) crc=(crc>>1) ^ (0xedb88320u & (0u-(crc&1u)));
  }
  return ~crc;
}
void fail(const char* reason) {
  Serial.printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);
}
bool prepareInput(int mode) {
  Model& m=models[mode];
  if(mode==0) memcpy(m.input->data.f,canonical,kPixels*sizeof(float));
  else for(int i=0;i<kPixels;++i) {
    const double rounded=std::nearbyint(double(canonical[i])/kInputScale+kInputZero);
    m.input->data.int8[i]=int8_t(std::max(-128.0,std::min(127.0,rounded)));
  }
  return true;
}
bool warm(int mode) {
  for(int i=0;i<kWarmups;++i) {
    prepareInput(mode);
    if(models[mode].runtime->Invoke()!=kTfLiteOk) {fail("warmup_invoke_failed");return false;}
    delay(1);
  }
  return true;
}
bool sample(int mode, int frame, int iteration, const uint8_t* image, size_t imageBytes,
            int64_t acquisitionUs, int64_t preprocessingUs, int fixedCase, int64_t cycleStart=0) {
  Model& m=models[mode];
  const int64_t start=esp_timer_get_time();
  prepareInput(mode); // Fresh input before EVERY invocation, outside Invoke timer.
  const int64_t prepared=esp_timer_get_time();
  uint32_t inputBefore=hash32(m.input->data.uint8,m.input->bytes);
  const int64_t invokeStart=esp_timer_get_time();
  if(m.runtime->Invoke()!=kTfLiteOk) {fail("invoke_failed");return false;}
  const int64_t invoked=esp_timer_get_time();
  uint32_t inputAfter=hash32(m.input->data.uint8,m.input->bytes);
  const uint32_t activationHash=hash32(m.output->data.uint8,m.output->bytes);
  bool stable=true;
  if(fixedCase>=0) {
    if(iteration==0) firstHash[mode][fixedCase]=activationHash;
    stable=firstHash[mode][fixedCase]==activationHash;
  }
  const int64_t packingStart=esp_timer_get_time();
  uint32_t header[8]={0x31424353u,1u,uint32_t(mode),uint32_t(frame),uint32_t(iteration),
                      uint32_t(imageBytes),uint32_t(m.output->bytes),0u};
  if(imageBytes) memcpy(message+32,image,imageBytes);
  memcpy(message+32+imageBytes,m.output->data.uint8,m.output->bytes);
  header[7]=crc32(message+32,imageBytes+m.output->bytes);
  memcpy(message,header,sizeof(header));
  const size_t bodyBytes=32+imageBytes+m.output->bytes;
  const int64_t packed=esp_timer_get_time();
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(15000);
  const int64_t networkStart=esp_timer_get_time();
  if(!http.begin(client,SERVER_URL)) {fail("http_begin_failed");return false;}
  http.addHeader("Content-Type","application/octet-stream");
  http.addHeader("X-Model-SHA256",m.sha);
  const int status=http.POST(message,bodyBytes);
  const int length=http.getSize();
  if(status!=200 || length!=int(kResponseBytes)) {
    Serial.printf("{\"event\":\"error\",\"reason\":\"http_response\",\"status\":%d,\"length\":%d}\n",status,length);
    http.end();return false;
  }
  const size_t got=http.getStreamPtr()->readBytes(response,kResponseBytes);
  http.end();
  const int64_t finished=esp_timer_get_time();
  uint32_t reply[8];memcpy(reply,response,32);
  if(got!=kResponseBytes || reply[0]!=0x31524353u || reply[1]!=1 ||
     reply[2]!=uint32_t(frame) || reply[3]!=uint32_t(iteration) || reply[4]!=432) {
    fail("invalid_response");return false;
  }
  const int64_t prepareUs=prepared-start;
  const int64_t invokeUs=invoked-invokeStart;
  const int64_t packingUs=packed-packingStart;
  const int64_t networkUs=finished-networkStart;
  // Phase sum excludes diagnostic hashes, serial logs, warmups and initialization.
  const int64_t activeUs=acquisitionUs+preprocessingUs+prepareUs+invokeUs+packingUs+networkUs;
  // Actual timer plus the acquisition/preprocessing shared by both members of a pair.
  const int64_t observedUs=cycleStart?finished-cycleStart:finished-start;
  Serial.printf("{\"event\":\"sample\",\"mode\":\"%s\",\"frame\":%d,\"iteration\":%d,"
                "\"source\":\"%s\",\"acquisition_us\":%lld,\"preprocessing_us\":%lld,"
                "\"input_prepare_us\":%lld,\"invoke_us\":%lld,\"packing_us\":%lld,"
                "\"request_response_us\":%lld,\"phase_sum_us\":%lld,\"observed_cycle_us\":%lld,"
                "\"server_decode_us\":%u,\"server_invoke_us\":%u,\"server_post_us\":%u,"
                "\"request_body_bytes\":%u,\"image_bytes\":%u,\"activation_bytes\":%u,"
                "\"response_body_bytes\":%u,\"activation_fnv32\":%u,\"response_fnv32\":%u,"
                "\"input_changed_by_invoke\":%s,\"matches_first_output_hash\":%s,\"rssi_dbm\":%d}\n",
                m.name,frame,iteration,fixedCase>=0?"embedded":"camera",acquisitionUs,preprocessingUs,
                prepareUs,invokeUs,packingUs,networkUs,activeUs,observedUs,reply[5],reply[6],reply[7],
                unsigned(bodyBytes),unsigned(imageBytes),unsigned(m.output->bytes),unsigned(kResponseBytes),
                activationHash,hash32(response,kResponseBytes),inputBefore!=inputAfter?"true":"false",
                stable?"true":"false",WiFi.RSSI());
  delay(1);
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
  const esp_err_t status=esp_camera_init(&c);
  Serial.printf("{\"event\":\"camera_init\",\"status\":%d}\n",int(status));
  return status==ESP_OK;
}
void run() {
  const int64_t sessionStart=esp_timer_get_time();
  for(int test=0;test<3;++test) {
    memcpy(canonical,kFrames[test],kPixels*sizeof(float));
    if(!warm(0)||!warm(1)) return;
    for(int repetition=0;repetition<kRepetitions;++repetition) {
      for(int position=0;position<2;++position) {
        const int mode=(repetition+position)%2;
        if(!sample(mode,kFrameIds[test],repetition,nullptr,0,0,0,test)) return;
      }
    }
  }
  if(cameraInit()) {
    // Camera is initialized only after the identical fixed-image comparison.
    for(int pair=0;pair<kLivePairs;++pair) {
     for(int position=0;position<2;++position) {
      const int mode=(pair+position)%2;
      const int64_t start=esp_timer_get_time();
      camera_fb_t* fb=esp_camera_fb_get();
      const int64_t captured=esp_timer_get_time();
      if(!fb || fb->width!=96 || fb->height!=96 || fb->len!=96*96*2 || fb->format!=PIXFORMAT_RGB565) {
        if(fb) esp_camera_fb_return(fb);
        fail("camera_frame_shape");return;
      }
      for(int i=0;i<kPixels;++i) {
        // esp32-camera delivers RGB565 high byte first.
        const uint16_t pixel=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];
        const float red=float((pixel>>11)&31)/31.0f;
        const float green=float((pixel>>5)&63)/63.0f;
        const float blue=float(pixel&31)/31.0f;
        canonical[i]=red*0.299f+green*0.587f+blue*0.114f;
      }
      const int64_t processed=esp_timer_get_time();
        if(!sample(mode,1000+2*pair+position,pair,fb->buf,fb->len,captured-start,processed-captured,-1,start)) {
          esp_camera_fb_return(fb);return;
        }
      esp_camera_fb_return(fb);
     }
    }
    esp_camera_deinit();
  }
  Serial.printf("{\"event\":\"done\",\"embedded_pairs\":%d,\"camera_pairs_requested\":%d,\"session_us\":%lld}\n",
                3*kRepetitions,kLivePairs,esp_timer_get_time()-sessionStart);
}
}

void setup() {
  Serial.begin(115200);
  const uint32_t started=millis();
  while(!Serial && millis()-started<10000) delay(10);
  delay(500);
  Serial.printf("{\"event\":\"boot\",\"experiment_sha256\":\"%s\",\"cpu_mhz\":%u,"
                "\"arena_capacity_each\":%u,\"arena_in_psram\":true,\"esp_nn_enabled\":false,"
                "\"repetitions\":%d,\"warmups_per_model_per_image\":%d}\n",
                kExperimentSha,unsigned(ESP.getCpuFreqMHz()),unsigned(kArenaBytes),kRepetitions,kWarmups);
  if(!psramFound()) {fail("psram_missing");return;}
  if(resolver.AddAdd()!=kTfLiteOk || resolver.AddConv2D()!=kTfLiteOk ||
     resolver.AddDepthwiseConv2D()!=kTfLiteOk || resolver.AddPad()!=kTfLiteOk || resolver.AddSoftmax()!=kTfLiteOk) {
    fail("resolver");return;
  }
  canonical=(float*)heap_caps_aligned_alloc(16,kPixels*sizeof(float),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  message=(uint8_t*)heap_caps_malloc(kMaxBody,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!canonical||!message) {fail("buffer_allocation");return;}
  for(int mode=0;mode<2;++mode) {
    Model& m=models[mode];
    auto* arena=(uint8_t*)heap_caps_aligned_alloc(16,kArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!arena) {fail("arena_allocation");return;}
    m.runtime=new tflite::MicroInterpreter(tflite::GetModel(m.binary),resolver,arena,kArenaBytes,&reporter);
    if(m.runtime->AllocateTensors()!=kTfLiteOk) {fail("allocate_tensors");return;}
    m.input=m.runtime->input(0);m.output=m.runtime->output(0);
    const TfLiteType type=mode==0?kTfLiteFloat32:kTfLiteInt8;
    if(m.input->type!=type || m.output->type!=type ||
       m.input->bytes!=size_t(kPixels*(mode==0?4:1)) || m.output->bytes!=size_t(4608*(mode==0?4:1))) {
      fail("tensor_spec");return;
    }
    Serial.printf("{\"event\":\"allocated\",\"mode\":\"%s\",\"arena_used_bytes\":%u,"
                  "\"model_sha256\":\"%s\",\"input_bytes\":%u,\"output_bytes\":%u}\n",
                  m.name,unsigned(m.runtime->arena_used_bytes()),m.sha,unsigned(m.input->bytes),unsigned(m.output->bytes));
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  const uint32_t wifiStart=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-wifiStart<30000) delay(100);
  if(WiFi.status()!=WL_CONNECTED) {fail("wifi_connection");return;}
  Serial.printf("{\"event\":\"wifi_ready\",\"ip\":\"%s\",\"rssi_dbm\":%d}\n",WiFi.localIP().toString().c_str(),WiFi.RSSI());
  ready=true;
  Serial.println("{\"event\":\"ready\",\"command\":\"g\"}");
}

void loop() {
  if(Serial.available()) {
    const char command=Serial.read();
    if(command=='r') {Serial.flush();ESP.restart();}
    if(command=='g' && ready) {ready=false;run();}
  }
  delay(10);
}
