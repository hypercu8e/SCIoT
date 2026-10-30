#include <algorithm>
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
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "sciot_miniz.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "generated/assets.h"
#include "network.local.h"
#include "codec.h"

extern const uint8_t videoInputs[] asm("_binary_video_inputs_bin_start");
extern uint32_t sciotConvCalls,sciotDepthwiseCalls;
#if !CONFIG_ESP_TFLITE_MICRO_USE_ESP_NN
#error ESP-NN is required
#endif
namespace {
constexpr size_t ArenaBytes=1024*1024;
constexpr int CameraFrames=30;
tflite::MicroMutableOpResolver<5> resolver;
tflite::MicroInterpreter* runtime;
TfLiteTensor *inputTensor,*outputTensor;
float *canonical,*previous,*state,*work;
int8_t *symbols,*diagnostics;
uint8_t *message,*compressed;
uint8_t response[dz::ReplyBytes];
mz_stream compressor={};
int compressorLevel=-1;
size_t codecLive=0,codecPeak=0;
uint32_t deviceId,sessionId,sequence;
EventGroupHandle_t wifiEvents;

void* allocate(size_t size) {return heap_caps_malloc(size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);}
void* codecAlloc(void*,size_t count,size_t size) {
  if(size && count>SIZE_MAX/size)return nullptr;
  size_t bytes=count*size;
  auto p=static_cast<size_t*>(allocate(bytes+16));
  if(!p)return nullptr;
  *p=bytes+16;codecLive+=bytes+16;codecPeak=std::max(codecPeak,codecLive);return reinterpret_cast<uint8_t*>(p)+16;
}
void codecFree(void*,void* data) {
  if(data){auto p=reinterpret_cast<size_t*>(static_cast<uint8_t*>(data)-16);codecLive-=*p;heap_caps_free(p);}
}
bool compressorInit(int level) {
  if(level==compressorLevel)return true;
  if(compressorLevel>=0)mz_deflateEnd(&compressor);
  compressor={};compressor.zalloc=codecAlloc;compressor.zfree=codecFree;
  if(mz_deflateInit(&compressor,level)!=MZ_OK)return false;
  compressorLevel=level;return mz_deflateBound(&compressor,dz::N)<=dz::Capacity;
}
void fail(const char* reason) {printf("{\"event\":\"error\",\"reason\":\"%s\"}\n",reason);}
void memory(const char* phase) {
  printf("{\"event\":\"memory\",\"phase\":\"%s\",\"codec_live_bytes\":%u,\"codec_peak_bytes\":%u,"
    "\"internal_free\":%u,\"internal_min\":%u,\"internal_largest\":%u,\"psram_free\":%u,\"psram_min\":%u,\"psram_largest\":%u}\n",
    phase,unsigned(codecLive),unsigned(codecPeak),unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),
    unsigned(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM)),
    unsigned(heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM)));
}
struct Sample {
  uint32_t session,seq,frame,source,config,originalCRC,stateCRC,inputCRC,activationCRC;
  int wireBytes,kind;
  int64_t acquisition,preprocess,prepare,invoke,quantization,compression,packing,network,cycle;
  uint32_t serverDecode,serverInvoke,serverPost;
};
void emit(const Sample& s) {
  printf("{\"event\":\"sample\",\"session\":%u,\"seq\":%u,\"frame\":%u,\"source\":%u,\"config\":%u,"
    "\"original_crc\":%u,\"state_crc\":%u,\"input_crc\":%u,\"activation_crc\":%u,\"wire_bytes\":%d,\"kind\":%d,"
    "\"acquisition_us\":%lld,\"preprocess_us\":%lld,\"prepare_us\":%lld,\"invoke_us\":%lld,"
    "\"quantize_reconstruct_us\":%lld,\"compression_us\":%lld,\"packing_us\":%lld,"
    "\"network_us\":%lld,\"cycle_us\":%lld,\"server_decode_us\":%u,\"server_invoke_us\":%u,\"server_post_us\":%u}\n",
    unsigned(s.session),unsigned(s.seq),unsigned(s.frame),unsigned(s.source),unsigned(s.config),unsigned(s.originalCRC),
    unsigned(s.stateCRC),unsigned(s.inputCRC),unsigned(s.activationCRC),s.wireBytes,s.kind,
    s.acquisition,s.preprocess,s.prepare,s.invoke,s.quantization,s.compression,s.packing,s.network,s.cycle,
    unsigned(s.serverDecode),unsigned(s.serverInvoke),unsigned(s.serverPost));
}
void header(int config,int kind,int frame,int source,float radius,size_t length,
            uint32_t originalCRC,uint32_t stateCRC,uint32_t inputCRC,uint32_t seq,int diagnosticSource=0) {
  const auto c=dz::Configs[config];
  uint32_t radiusBits;memcpy(&radiusBits,&radius,4);
  uint32_t h[20]={dz::Magic,1,deviceId,sessionId,uint32_t(config),seq,kind?seq-1:dz::None,
    uint32_t(kind),uint32_t(frame),uint32_t(source),uint32_t(source==2?0:c.bits),uint32_t(source==2?0:c.level),
    radiusBits,dz::N,uint32_t(length),originalCRC,stateCRC,inputCRC,uint32_t(diagnosticSource),0};
  h[19]=dz::crc(h,76);memcpy(message,h,80);
}
bool exchange(size_t bytes,int config,int frame,uint32_t seq,uint32_t stateCRC,uint32_t* reply) {
  esp_http_client_config_t cfg={};cfg.url=SERVER_URL;cfg.timeout_ms=60000;cfg.buffer_size=2048;cfg.buffer_size_tx=1024;
  auto http=esp_http_client_init(&cfg);if(!http)return false;
  esp_http_client_set_method(http,HTTP_METHOD_POST);
  esp_http_client_set_header(http,"Content-Type","application/octet-stream");
  esp_http_client_set_header(http,"X-Model-SHA256",kInt8Sha);
  esp_http_client_set_header(http,"Connection","close");
  auto result=esp_http_client_open(http,bytes);int sent=0,received=0;
  while(result==ESP_OK && sent<int(bytes)) {
    int n=esp_http_client_write(http,reinterpret_cast<char*>(message)+sent,bytes-sent);
    if(n<=0){result=ESP_FAIL;break;}sent+=n;
  }
  int64_t length=result==ESP_OK?esp_http_client_fetch_headers(http):-1;
  const int httpStatus=esp_http_client_get_status_code(http);
  if(result==ESP_OK && esp_http_client_get_status_code(http)==200 && length==dz::ReplyBytes) {
    while(received<dz::ReplyBytes) {
      int n=esp_http_client_read(http,reinterpret_cast<char*>(response)+received,dz::ReplyBytes-received);
      if(n<=0)break;
      received+=n;
    }
  }
  esp_http_client_cleanup(http);
  if(received!=dz::ReplyBytes) {
    printf("{\"event\":\"transport_error\",\"config\":%d,\"frame\":%d,\"seq\":%u,\"esp_error\":%d,\"http_status\":%d,\"sent\":%d,\"received\":%d,\"length\":%lld}\n",
      config,frame,unsigned(seq),int(result),httpStatus,sent,received,length);
    return false;
  }
  memcpy(reply,response,48);
  return reply[0]==dz::ReplyMagic && reply[1]==1 && reply[2]==deviceId && reply[3]==sessionId &&
    reply[4]==uint32_t(config) && reply[5]==seq && reply[6]==uint32_t(frame) && reply[10]==stateCRC;
}
bool sample(int config,int frame,int source,Sample& row,int64_t start,int64_t acquisition=0,int64_t preprocess=0) {
  const auto c=dz::Configs[config];
  const int64_t begin=esp_timer_get_time();
  for(int i=0;i<kPixels;++i)inputTensor->data.int8[i]=dz::requant(canonical[i],kInputScale,kInputZero);
  const uint32_t inputCRC=dz::crc(inputTensor->data.int8,kPixels);
  const int64_t prepared=esp_timer_get_time();
  if(runtime->Invoke()!=kTfLiteOk)return false;
  const int64_t invoked=esp_timer_get_time();
  const bool delta=c.mode>=3 && sequence%30;
  const float radius=dz::encode(outputTensor->data.int8,previous,state,symbols,work,config,delta,kBoundaryScale,kBoundaryZero);
  const int64_t quantized=esp_timer_get_time();
  size_t length=dz::N;
  const uint8_t* payload=reinterpret_cast<uint8_t*>(symbols);
  if(c.level) {
    if(mz_deflateReset(&compressor)!=MZ_OK)return false;
    compressor.next_in=payload;compressor.avail_in=dz::N;compressor.next_out=compressed;compressor.avail_out=dz::Capacity;
    if(mz_deflate(&compressor,MZ_FINISH)!=MZ_STREAM_END || compressor.avail_in)return false;
    length=compressor.total_out;payload=compressed;
  }
  const int64_t zipped=esp_timer_get_time();
  const uint32_t originalCRC=dz::crc(outputTensor->data.int8,dz::N),stateCRC=dz::crc(state,dz::N*4);
  memcpy(message+80,payload,length);
  header(config,delta,frame,source,radius,length,originalCRC,stateCRC,inputCRC,sequence);
  const int64_t packed=esp_timer_get_time();uint32_t reply[12];
  if(!exchange(80+length,config,frame,sequence,stateCRC,reply))return false;
  // State becomes committed only after the correlated server response.
  memcpy(previous,state,dz::N*4);
  const int64_t finished=esp_timer_get_time();
  row={sessionId,sequence,uint32_t(frame),uint32_t(source),uint32_t(config),originalCRC,stateCRC,inputCRC,reply[11],
    int(length),int(delta),acquisition,preprocess,prepared-begin,invoked-prepared,quantized-invoked,zipped-quantized,
    packed-zipped,finished-packed,finished-start,reply[7],reply[8],reply[9]};
  ++sequence;return true;
}
bool cameraInit() {
  camera_config_t c={};c.pin_pwdn=-1;c.pin_reset=-1;c.pin_xclk=15;c.pin_sccb_sda=4;c.pin_sccb_scl=5;
  c.pin_d0=11;c.pin_d1=9;c.pin_d2=8;c.pin_d3=10;c.pin_d4=12;c.pin_d5=18;c.pin_d6=17;c.pin_d7=16;
  c.pin_vsync=6;c.pin_href=7;c.pin_pclk=13;c.xclk_freq_hz=20000000;c.ledc_timer=LEDC_TIMER_0;c.ledc_channel=LEDC_CHANNEL_0;
  c.pixel_format=PIXFORMAT_RGB565;c.frame_size=FRAMESIZE_96X96;c.fb_count=1;
  c.fb_location=CAMERA_FB_IN_PSRAM;c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  return esp_camera_init(&c)==ESP_OK;
}
bool health(const char* phase) {
  esp_http_client_config_t cfg={};cfg.url=SERVER_URL;cfg.timeout_ms=15000;
  auto client=esp_http_client_init(&cfg);
  if(!client)return false;
  auto result=esp_http_client_perform(client);int status=esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);wifi_ap_record_t ap={};auto wifi=esp_wifi_sta_get_ap_info(&ap);
  printf("{\"event\":\"health\",\"phase\":\"%s\",\"esp_error\":%d,\"http_status\":%d,\"wifi_error\":%d,\"rssi\":%d,\"channel\":%d}\n",
    phase,int(result),status,int(wifi),int(ap.rssi),int(ap.primary));
  return result==ESP_OK && status==200;
}
bool capture(int config,int frame,Sample& row) {
  const int64_t start=esp_timer_get_time();auto fb=esp_camera_fb_get();const int64_t acquired=esp_timer_get_time();
  if(!fb || fb->len!=kPixels*2 || fb->format!=PIXFORMAT_RGB565){if(fb)esp_camera_fb_return(fb);return false;}
  for(int i=0;i<kPixels;++i) {
    uint16_t p=(uint16_t(fb->buf[2*i])<<8)|fb->buf[2*i+1];
    canonical[i]=float((p>>11)&31)/31.0f*.299f+float((p>>5)&63)/63.0f*.587f+float(p&31)/31.0f*.114f;
  }
  esp_camera_fb_return(fb);const int64_t processed=esp_timer_get_time();
  return sample(config,frame,1,row,start,acquired-start,processed-acquired);
}
bool diagnostic(const Sample& row,const int8_t* raw) {
  for(int i=0;i<dz::N;++i)state[i]=dz::dequant(raw[i],kBoundaryScale,kBoundaryZero);
  memcpy(message+80,raw,dz::N);
  uint32_t stateCRC=dz::crc(state,dz::N*4),reply[12];
  header(row.config,0,row.frame,2,0,dz::N,row.originalCRC,stateCRC,row.inputCRC,row.seq,1);
  return exchange(80+dz::N,row.config,row.frame,row.seq,stateCRC,reply) && reply[11]==row.originalCRC;
}
void startStream() {sessionId=esp_random();sequence=0;memset(previous,0,dz::N*4);}
bool run(int round,bool cameraOnly=false,bool videoOnly=false) {
  auto rows=static_cast<Sample*>(allocate(sizeof(Sample)*kVideoFrames));
  if(!rows){fail("sample_buffer");return false;}
  if(!cameraOnly)for(int position=0;position<dz::Count;++position) {
    const int config=round%2?dz::Count-1-position:position;const auto c=dz::Configs[config];
    if(c.level && !compressorInit(c.level)){fail("compressor_init");return false;}
    startStream();memory("video_start");
    printf("{\"event\":\"sequence_start\",\"round\":%d,\"config\":%d,\"session\":%u,\"source\":0,\"frames\":146}\n",round,config,unsigned(sessionId));
    int64_t start=esp_timer_get_time();
    for(int frame=0;frame<kVideoFrames;++frame) {
      int64_t begin=esp_timer_get_time();
      memcpy(canonical,videoInputs+frame*kPixels*4,kPixels*4);
      if(!sample(config,frame,0,rows[frame],begin)){heap_caps_free(rows);fail("video_sample_new_session_required");return false;}
    }
    int64_t elapsed=esp_timer_get_time()-start;
    for(int frame=0;frame<kVideoFrames;++frame)emit(rows[frame]);
    printf("{\"event\":\"throughput\",\"session\":%u,\"source\":0,\"config\":%d,\"frames\":146,\"elapsed_us\":%lld}\n",unsigned(sessionId),config,elapsed);
    memory("video_end");
  }
  if(videoOnly){heap_caps_free(rows);return true;}
  if(!health("before_camera")){heap_caps_free(rows);fail("network_before_camera");return false;}
  if(!cameraInit()){heap_caps_free(rows);fail("camera_init");return false;}
  if(!health("after_camera")){heap_caps_free(rows);fail("network_after_camera");return false;}
  for(int position=0;position<(cameraOnly?1:dz::Count);++position) {
    const int config=round%2?dz::Count-1-position:position;const auto c=dz::Configs[config];
    if(c.level && !compressorInit(c.level)){fail("compressor_init");return false;}
    startStream();memory("camera_start");
    printf("{\"event\":\"sequence_start\",\"round\":%d,\"config\":%d,\"session\":%u,\"source\":1,\"frames\":30}\n",round,config,unsigned(sessionId));
    int64_t start=esp_timer_get_time();
    for(int frame=0;frame<CameraFrames;++frame) {
      if(!capture(config,1000+frame,rows[frame])){heap_caps_free(rows);fail("camera_sample_new_session_required");return false;}
      memcpy(diagnostics+frame*dz::N,outputTensor->data.int8,dz::N);
    }
    int64_t elapsed=esp_timer_get_time()-start;
    for(int frame=0;frame<CameraFrames;++frame)emit(rows[frame]);
    printf("{\"event\":\"throughput\",\"session\":%u,\"source\":1,\"config\":%d,\"frames\":30,\"elapsed_us\":%lld}\n",unsigned(sessionId),config,elapsed);
    // Upload originals AFTER the throughput interval. They never feed the codec decoder.
    for(int frame=0;frame<CameraFrames;++frame)if(!diagnostic(rows[frame],diagnostics+frame*dz::N)){fail("diagnostic");return false;}
    memory("camera_end");
  }
  esp_camera_deinit();heap_caps_free(rows);return true;
}
void wifiEvent(void*,esp_event_base_t base,int32_t event,void*) {
  if(base==WIFI_EVENT && event==WIFI_EVENT_STA_DISCONNECTED) {
    xEventGroupClearBits(wifiEvents,1);
    printf("{\"event\":\"wifi_disconnected\"}\n");
  }
  if(base==WIFI_EVENT && (event==WIFI_EVENT_STA_START || event==WIFI_EVENT_STA_DISCONNECTED))esp_wifi_connect();
  if(base==IP_EVENT && event==IP_EVENT_STA_GOT_IP)xEventGroupSetBits(wifiEvents,1);
}
}
extern "C" void app_main() {
  setvbuf(stdout,nullptr,_IONBF,0);vTaskDelay(pdMS_TO_TICKS(1200));
  printf("{\"event\":\"boot\",\"experiment_sha256\":\"%s\",\"cpu_mhz\":240,\"reference_bytes_each\":18432,"
    "\"scratch_bytes\":18432,\"symbol_bytes\":4608,\"diagnostic_buffer_bytes\":138240,\"camera_xclk_hz\":20000000}\n",kExperimentSha);
  ESP_ERROR_CHECK(resolver.AddAdd());ESP_ERROR_CHECK(resolver.AddConv2D());ESP_ERROR_CHECK(resolver.AddDepthwiseConv2D());
  ESP_ERROR_CHECK(resolver.AddPad());ESP_ERROR_CHECK(resolver.AddSoftmax());
  canonical=static_cast<float*>(allocate(kPixels*4));previous=static_cast<float*>(allocate(dz::N*4));
  state=static_cast<float*>(allocate(dz::N*4));work=static_cast<float*>(allocate(dz::N*4));
  symbols=static_cast<int8_t*>(allocate(dz::N));diagnostics=static_cast<int8_t*>(allocate(CameraFrames*dz::N));
  message=static_cast<uint8_t*>(allocate(80+dz::Capacity));compressed=static_cast<uint8_t*>(allocate(dz::Capacity));
  auto arena=static_cast<uint8_t*>(heap_caps_aligned_alloc(16,ArenaBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(!canonical||!previous||!state||!work||!symbols||!diagnostics||!message||!compressed||!arena){fail("allocation");return;}
  runtime=new tflite::MicroInterpreter(tflite::GetModel(kInt8Model),resolver,arena,ArenaBytes);
  if(runtime->AllocateTensors()!=kTfLiteOk){fail("tensors");return;}
  inputTensor=runtime->input(0);outputTensor=runtime->output(0);
  if(inputTensor->bytes!=kPixels||outputTensor->bytes!=dz::N){fail("tensor_shape");return;}
  const float* first=reinterpret_cast<const float*>(videoInputs);
  for(int i=0;i<kPixels;++i)inputTensor->data.int8[i]=dz::requant(first[i],kInputScale,kInputZero);
  sciotConvCalls=sciotDepthwiseCalls=0;
  if(runtime->Invoke()!=kTfLiteOk||!sciotConvCalls||!sciotDepthwiseCalls){fail("esp_nn_probe");return;}
  printf("{\"event\":\"kernel_check\",\"conv\":%u,\"depthwise\":%u,\"arena_used\":%u,\"model_sha256\":\"%s\"}\n",
    unsigned(sciotConvCalls),unsigned(sciotDepthwiseCalls),unsigned(runtime->arena_used_bytes()),kInt8Sha);
  // No automatic NVS erase: initialization failures leave original persistent state intact.
  ESP_ERROR_CHECK(nvs_flash_init());ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();wifiEvents=xEventGroupCreate();
  wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifiEvent,nullptr));
  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifiEvent,nullptr));
  wifi_config_t wifi={};strncpy(reinterpret_cast<char*>(wifi.sta.ssid),WIFI_SSID,sizeof(wifi.sta.ssid));
  strncpy(reinterpret_cast<char*>(wifi.sta.password),WIFI_PASSWORD,sizeof(wifi.sta.password));
  ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));ESP_ERROR_CHECK(esp_wifi_start());ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
  if(!(xEventGroupWaitBits(wifiEvents,1,pdFALSE,pdFALSE,pdMS_TO_TICKS(30000))&1)){fail("wifi");return;}
  uint8_t mac[6];ESP_ERROR_CHECK(esp_read_mac(mac,ESP_MAC_WIFI_STA));deviceId=dz::crc(mac,6);
  printf("{\"event\":\"ready\",\"command\":\"g\",\"device\":%u}\n",unsigned(deviceId));
  fcntl(fileno(stdin),F_SETFL,O_NONBLOCK);
  bool cameraOnly=false,videoOnly=false;
  for(;;) {
    int c=getchar();if(c=='g'||c=='c'||c=='v'){cameraOnly=c=='c';videoOnly=c=='v';break;}clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(10));
  }
  if(cameraOnly) {
    if(!compressorInit(6)||!run(0,true))return;
    printf("{\"event\":\"done\",\"measured_requests\":30,\"diagnostic_requests\":30,\"camera_only\":true}\n");return;
  }
  for(int round=0;round<2;++round)if(!run(round,false,videoOnly))return;
  if(videoOnly){printf("{\"event\":\"done\",\"measured_requests\":3504,\"diagnostic_requests\":0,\"video_only\":true}\n");return;}
  printf("{\"event\":\"done\",\"measured_requests\":4224,\"diagnostic_requests\":720}\n");
}
