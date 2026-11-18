#include "xclk_probe.h"
#include <cstdio>
#include <cstring>
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_netif.h"
#include "esp_rom_gpio.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "lwip/ip_addr.h"
#include "ping/ping_sock.h"
#include "soc/gpio_sig_map.h"
#include "soc/gpio_struct.h"

#if !CONFIG_IDF_TARGET_ESP32S3
#error XCLK diagnostic is specific to ESP32-S3
#endif

namespace xclk_probe {
namespace {
constexpr gpio_num_t kPin=GPIO_NUM_15;
constexpr uint32_t kCaps=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT;
struct Probe {uint16_t sequence;uint32_t elapsed;int64_t timestamp;bool received;};
struct Target {
  const char* role;
  ip_addr_t address;
  esp_ping_handle_t handle=nullptr;
  Probe* probes=nullptr;
  unsigned used=0;
  bool invalid=false;
};
Target targets[2];
EventGroupHandle_t complete=nullptr;

void result(esp_ping_handle_t handle,void* args,bool received) {
  auto* t=static_cast<Target*>(args);
  uint16_t seq=0;uint32_t elapsed=0;
  if(esp_ping_get_profile(handle,ESP_PING_PROF_SEQNO,&seq,sizeof(seq))!=ESP_OK ||
     esp_ping_get_profile(handle,ESP_PING_PROF_TIMEGAP,&elapsed,sizeof(elapsed))!=ESP_OK ||
     t->used>=kCount){t->invalid=true;return;}
  t->probes[t->used++]={seq,elapsed,esp_timer_get_time(),received};
}
void success(esp_ping_handle_t h,void* args){result(h,args,true);}
void timeout(esp_ping_handle_t h,void* args){result(h,args,false);}
void ended(esp_ping_handle_t,void*){xEventGroupSetBits(complete,1);}
}

bool init(const char* serverBaseUrl) {
  if(complete || strncmp(serverBaseUrl,"http://",7))return false;
  char host[16];const char* begin=serverBaseUrl+7;
  const size_t length=strcspn(begin,":/");
  if(!length || length>=sizeof(host))return false;
  memcpy(host,begin,length);host[length]=0;
  targets[0].role="gateway";targets[1].role="laptop";
  if(!ipaddr_aton(host,&targets[1].address) || !IP_IS_V4(&targets[1].address))return false;
  esp_netif_ip_info_t info={};
  auto* netif=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
  if(!netif || esp_netif_get_ip_info(netif,&info)!=ESP_OK || !info.gw.addr)return false;
  IP_ADDR4(&targets[0].address,ip4_addr1(&info.gw),ip4_addr2(&info.gw),ip4_addr3(&info.gw),ip4_addr4(&info.gw));
  if(ip_addr_cmp(&targets[0].address,&targets[1].address))return false;
  complete=xEventGroupCreate();if(!complete)return false;
  for(auto& t:targets){
    t.probes=static_cast<Probe*>(heap_caps_calloc(kCount,sizeof(Probe),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!t.probes)return false;
    esp_ping_config_t config=ESP_PING_DEFAULT_CONFIG();
    config.count=kCount;config.interval_ms=200;config.timeout_ms=1000;
    config.data_size=64;config.target_addr=t.address;config.task_stack_size=3072;
    esp_ping_callbacks_t callbacks={};callbacks.cb_args=&t;
    callbacks.on_ping_success=success;callbacks.on_ping_timeout=timeout;callbacks.on_ping_end=ended;
    if(esp_ping_new_session(&config,&callbacks,&t.handle)!=ESP_OK)return false;
    char address[48];ipaddr_ntoa_r(&t.address,address,sizeof(address));
    printf("{\"event\":\"xclk_target\",\"target\":\"%s\",\"address\":\"%s\",\"count\":50,\"interval_ms\":200,\"timeout_ms\":1000}\n",t.role,address);
  }
  return true;
}

bool clock(bool enabled,unsigned index) {
  const size_t before=heap_caps_get_free_size(kCaps);
  // On S3 the clock is routed from LCD_CAM, not LEDC. Keep the peripheral's
  // divider untouched; only disconnect/reconnect its signal at the output pin.
  if(!enabled && gpio_set_level(kPin,0)!=ESP_OK)return false;
  esp_rom_gpio_connect_out_signal(kPin,enabled?CAM_CLK_IDX:SIG_GPIO_OUT_IDX,false,false);
  const unsigned selected=GPIO.func_out_sel_cfg[kPin].func_sel;
  const bool latchLow=(GPIO.out&(1u<<kPin))==0;
  const bool ok=selected==unsigned(enabled?CAM_CLK_IDX:SIG_GPIO_OUT_IDX) && (enabled || latchLow);
  printf("{\"event\":\"xclk_gate\",\"phase\":%u,\"enabled\":%s,\"gpio\":15,\"signal_index\":%u,\"output_latch_low\":%s,\"route_verified\":%s,\"internal_free_before\":%u,\"internal_free_after\":%u,\"buffers_retained\":true}\n",
    index,enabled?"true":"false",selected,latchLow?"true":"false",ok?"true":"false",unsigned(before),unsigned(heap_caps_get_free_size(kCaps)));
  vTaskDelay(pdMS_TO_TICKS(200));
  return ok;
}

bool phase(unsigned index,const char* name,bool cameraInitialized,bool clockEnabled) {
  printf("{\"event\":\"xclk_phase_begin\",\"phase\":%u,\"name\":\"%s\",\"camera_initialized\":%s,\"xclk_enabled\":%s,\"internal_free\":%u,\"internal_min_free\":%u,\"largest_block\":%u}\n",
    index,name,cameraInitialized?"true":"false",clockEnabled?"true":"false",unsigned(heap_caps_get_free_size(kCaps)),unsigned(heap_caps_get_minimum_free_size(kCaps)),unsigned(heap_caps_get_largest_free_block(kCaps)));
  for(auto& t:targets){
    t.used=0;t.invalid=false;xEventGroupClearBits(complete,1);
    if(esp_ping_start(t.handle)!=ESP_OK)return false;
    if(!(xEventGroupWaitBits(complete,1,pdTRUE,pdFALSE,pdMS_TO_TICKS(70000))&1)){
      esp_ping_stop(t.handle);return false;
    }
    uint32_t sent=0,received=0;
    if(esp_ping_get_profile(t.handle,ESP_PING_PROF_REQUEST,&sent,sizeof(sent))!=ESP_OK ||
       esp_ping_get_profile(t.handle,ESP_PING_PROF_REPLY,&received,sizeof(received))!=ESP_OK ||
       t.invalid || t.used!=kCount || sent>kCount || received>sent)return false;
    unsigned successes=0;
    for(unsigned i=0;i<t.used;++i){
      const auto& r=t.probes[i];
      if(r.sequence!=i+1)return false;
      successes+=r.received;
      printf("{\"event\":\"xclk_ping\",\"phase\":%u,\"target\":\"%s\",\"sequence\":%u,\"received\":%s,\"elapsed_ms\":%u,\"device_us\":%lld}\n",
        index,t.role,unsigned(r.sequence),r.received?"true":"false",unsigned(r.elapsed),r.timestamp);
    }
    if(successes!=received)return false;
    wifi_ap_record_t ap={};const bool associated=esp_wifi_sta_get_ap_info(&ap)==ESP_OK;
    printf("{\"event\":\"xclk_ping_summary\",\"phase\":%u,\"target\":\"%s\",\"attempted\":50,\"sent\":%u,\"received\":%u,\"associated\":%s,\"rssi_dbm\":%d,\"internal_free\":%u,\"internal_min_free\":%u}\n",
      index,t.role,unsigned(sent),unsigned(received),associated?"true":"false",associated?int(ap.rssi):0,unsigned(heap_caps_get_free_size(kCaps)),unsigned(heap_caps_get_minimum_free_size(kCaps)));
  }
  return true;
}

void close(){
  for(auto& t:targets)if(t.handle){esp_ping_stop(t.handle);esp_ping_delete_session(t.handle);t.handle=nullptr;}
  // Callback contexts, event group and PSRAM records live until this diagnostic
  // boot is reset, including on a timeout while a ping task is winding down.
}
}
