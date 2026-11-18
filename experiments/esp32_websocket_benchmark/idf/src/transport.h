// Shared synchronous application interface; callbacks only assemble bounded replies.
#include "esp_websocket_client.h"
#include "esp_random.h"
#include "esp_rom_crc.h"
#include "generated/expected_scores.h"
#ifndef SERVER_BASE_URL
#error Configure SERVER_BASE_URL in the ignored local network header
#endif
namespace transport {
constexpr size_t requestBytes=4640,replyBytes=1760;
char mode='w',cid[32],session[33],httpUrl[256],wsUrl[256];
uint64_t sequence=0;
int lastStatus=0;
unsigned httpConnections=0;
enum class State {Disconnected,Connecting,Registering,Ready,Waiting};
State state=State::Disconnected;
uint8_t *tx=nullptr,*rx=nullptr;
size_t received=0,frameReceived=0;
uint8_t fragmentOpcode=0;
EventGroupHandle_t events=nullptr;
esp_websocket_client_handle_t ws=nullptr;
esp_http_client_handle_t http=nullptr;
char gotClient[65],gotSession[65],gotSequence[32];
constexpr EventBits_t OPEN=1,DATA=2,BROKEN=4;
void header(uint8_t* p,uint8_t kind,uint64_t id){memcpy(p,"SCW1",4);p[4]=1;p[5]=kind;p[6]=p[7]=0;memcpy(p+8,&id,8);}
void wsEvent(void*,esp_event_base_t,int32_t id,void* value){
  if(id==WEBSOCKET_EVENT_CONNECTED){xEventGroupSetBits(events,OPEN);return;}
  if(id==WEBSOCKET_EVENT_DISCONNECTED||id==WEBSOCKET_EVENT_CLOSED){xEventGroupSetBits(events,BROKEN);return;}
  if(id==WEBSOCKET_EVENT_ERROR){auto* e=static_cast<esp_websocket_event_data_t*>(value);printf("{\"event\":\"transport_error\",\"errno\":%d}\n",e?e->error_handle.esp_transport_sock_errno:0);xEventGroupSetBits(events,BROKEN);return;}
  if(id!=WEBSOCKET_EVENT_DATA)return;
  auto* e=static_cast<esp_websocket_event_data_t*>(value);
  if(e->op_code>=8)return; // control frames do not affect application assembly
  if(e->payload_offset==0){
    frameReceived=0;
    if(e->op_code==1||e->op_code==2){
      if(fragmentOpcode){xEventGroupSetBits(events,BROKEN);return;}
      fragmentOpcode=e->op_code;received=0;
    }else if(e->op_code!=0||!fragmentOpcode){xEventGroupSetBits(events,BROKEN);return;}
  }
  if(e->payload_offset!=int(frameReceived)||e->data_len<0||e->payload_len<0||received+e->data_len>1776||e->payload_offset+e->data_len>e->payload_len){xEventGroupSetBits(events,BROKEN);return;}
  memcpy(rx+received,e->data_ptr,e->data_len);received+=e->data_len;frameReceived+=e->data_len;
  if(e->fin&&frameReceived==size_t(e->payload_len)){fragmentOpcode=0;rx[received]=0;xEventGroupSetBits(events,DATA);}
}
esp_err_t httpEvent(esp_http_client_event_t* e){
  if(e->event_id==HTTP_EVENT_ON_CONNECTED)++httpConnections;
  if(e->event_id==HTTP_EVENT_ON_DATA){
    if(e->data_len<0||received+e->data_len>replyBytes){return ESP_FAIL;}
    memcpy(rx+received,e->data,e->data_len);received+=e->data_len;rx[received]=0;
  }
  if(e->event_id==HTTP_EVENT_ON_HEADER){
    char* target=nullptr;size_t cap=65;
    if(!strcasecmp(e->header_key,"x-client-id"))target=gotClient;
    if(!strcasecmp(e->header_key,"x-session-id"))target=gotSession;
    if(!strcasecmp(e->header_key,"x-request-id")){target=gotSequence;cap=32;}
    if(target)snprintf(target,cap,"%s",e->header_value);
  }
  return ESP_OK;
}
void disconnect(){
  session[0]=0;state=State::Disconnected;
  if(ws){esp_websocket_client_stop(ws);esp_websocket_client_destroy(ws);ws=nullptr;}
  if(http){esp_http_client_cleanup(http);http=nullptr;}
  received=frameReceived=fragmentOpcode=0;
}
bool jsonRegistration(){
  auto* json=cJSON_Parse(reinterpret_cast<char*>(rx));
  auto* sid=json?cJSON_GetObjectItemCaseSensitive(json,"session_id"):nullptr;
  auto* identity=json?cJSON_GetObjectItemCaseSensitive(json,"client_id"):nullptr;
  auto* model=json?cJSON_GetObjectItemCaseSensitive(json,"model_sha256"):nullptr;
  auto* bytes=json?cJSON_GetObjectItemCaseSensitive(json,"activation_bytes"):nullptr;
  bool ok=cJSON_IsString(sid)&&strlen(sid->valuestring)==32&&strspn(sid->valuestring,"0123456789abcdef")==32&&cJSON_IsString(identity)&&!strcmp(identity->valuestring,cid)&&cJSON_IsString(model)&&!strcmp(model->valuestring,kNoPadSha)&&cJSON_IsNumber(bytes)&&bytes->valueint==4608;
  if(ok){strcpy(session,sid->valuestring);sequence=0;}
  if(!ok){auto* status=json?cJSON_GetObjectItemCaseSensitive(json,"status"):nullptr;lastStatus=cJSON_IsNumber(status)?status->valueint:400;}
  cJSON_Delete(json);return ok;
}
bool waitData(int64_t deadline=0){if(!deadline)deadline=esp_timer_get_time()+15000000;const auto remaining=std::max<int64_t>(0,deadline-esp_timer_get_time());const auto bits=xEventGroupWaitBits(events,DATA|BROKEN,pdFALSE,pdFALSE,pdMS_TO_TICKS((remaining+999)/1000));return (bits&DATA)&&!(bits&BROKEN);}
bool connect(int64_t deadline=0){
  if(!deadline)deadline=esp_timer_get_time()+15000000;
  auto remaining=[&](){return std::max<int64_t>(1,(deadline-esp_timer_get_time()+999)/1000);};
  disconnect();state=State::Connecting;lastStatus=0;
  char registration[256];snprintf(registration,sizeof(registration),"{\"version\":1,\"client_id\":\"%s\",\"model_sha256\":\"%s\"}",cid,kNoPadSha);
  if(mode=='w'){
    xEventGroupClearBits(events,OPEN|DATA|BROKEN);
    esp_websocket_client_config_t c={};c.uri=wsUrl;c.disable_auto_reconnect=true;c.buffer_size=4656;c.task_stack=4096;c.network_timeout_ms=int(remaining());c.ping_interval_sec=20;c.pingpong_timeout_sec=10;
    ws=esp_websocket_client_init(&c);if(!ws)return false;
    esp_websocket_register_events(ws,WEBSOCKET_EVENT_ANY,wsEvent,nullptr);
    if(esp_websocket_client_start(ws)!=ESP_OK)return false;
    auto bits=xEventGroupWaitBits(events,OPEN|BROKEN,pdFALSE,pdFALSE,pdMS_TO_TICKS(remaining()));
    if(!(bits&OPEN)||(bits&BROKEN))return false;
    state=State::Registering;
    if(esp_websocket_client_send_text(ws,registration,strlen(registration),pdMS_TO_TICKS(remaining()))!=int(strlen(registration))||!waitData(deadline))return false;
  }else{
    char url[256];snprintf(url,sizeof(url),"%s/api/v2/registration",SERVER_BASE_URL);
    esp_http_client_config_t c={};c.url=url;c.timeout_ms=int(remaining());c.event_handler=httpEvent;c.buffer_size=2048;c.buffer_size_tx=1024;
    http=esp_http_client_init(&c);if(!http)return false;
    esp_http_client_set_method(http,HTTP_METHOD_POST);esp_http_client_set_header(http,"Content-Type","application/json");esp_http_client_set_post_field(http,registration,strlen(registration));
    const esp_err_t result=esp_http_client_perform(http);
    lastStatus=esp_http_client_get_status_code(http);
    printf("{\"event\":\"http_registration_result\",\"esp_err\":%d,\"http_status\":%d,\"received_bytes\":%u,\"socket_errno\":%d}\n",int(result),lastStatus,unsigned(received),esp_http_client_get_errno(http));
    if(result!=ESP_OK||lastStatus!=200)return false;
  }
  bool ok=jsonRegistration();
  if(ok)state=State::Ready;
  if(http){esp_http_client_cleanup(http);http=nullptr;}
  printf("{\"event\":\"transport_registration\",\"mode\":\"%c\",\"ok\":%s}\n",mode,ok?"true":"false");
  return ok;
}
bool connectWithBackoff(){
  const int64_t deadline=esp_timer_get_time()+30000000;unsigned delay=500;
  while(esp_timer_get_time()<deadline){
    if(connect(deadline))return true;
    disconnect();
    if(lastStatus==400||lastStatus==422)return false;
    vTaskDelay(pdMS_TO_TICKS(std::max<int64_t>(0,std::min<int64_t>(delay+esp_random()%251,(deadline-esp_timer_get_time())/1000))));delay=std::min(8000u,delay*2);
  }
  return false;
}
bool init(){
  tx=static_cast<uint8_t*>(heap_caps_malloc(4656,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  rx=static_cast<uint8_t*>(heap_caps_malloc(1777,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));events=xEventGroupCreate();
  uint8_t mac[6];esp_efuse_mac_get_default(mac);
  snprintf(cid,sizeof(cid),"eye-%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
  snprintf(httpUrl,sizeof(httpUrl),"%s/api/v2/infer",SERVER_BASE_URL);
  const char* base=SERVER_BASE_URL;if(strncmp(base,"http://",7))return false;
  snprintf(wsUrl,sizeof(wsUrl),"ws://%s/api/v2/ws",base+7);
  return tx&&rx&&events;
}
bool exchange(const uint8_t* activation,uint32_t frame,uint32_t iteration){
  if(!session[0]&&!connectWithBackoff())return false;
  state=State::Waiting;
  uint64_t id=sequence++;header(tx,1,id);
  uint32_t h[8]={0x31424353,1,1,frame,iteration,0,4608,esp_rom_crc32_le(0,activation,4608)};
  memcpy(tx+16,h,32);memcpy(tx+48,activation,4608);
  received=0;gotClient[0]=gotSession[0]=gotSequence[0]=0;int64_t start=esp_timer_get_time();bool ok=false;
  if(mode=='w'){
    xEventGroupClearBits(events,DATA);
    ok=esp_websocket_client_send_bin(ws,reinterpret_cast<char*>(tx),4656,pdMS_TO_TICKS(15000))==4656&&waitData(start+15000000);
    uint64_t got=0;memcpy(&got,rx+8,8);
    ok=ok&&received==1776&&!memcmp(rx,"SCW1\1\2\0\0",8)&&got==id;
    if(ok)memmove(rx,rx+16,1760);
  }else{
    if(!http){esp_http_client_config_t c={};c.url=httpUrl;c.timeout_ms=15000;c.buffer_size=2048;c.buffer_size_tx=1024;c.event_handler=httpEvent;http=esp_http_client_init(&c);}
    if(!http)return false;
    char seq[32];snprintf(seq,sizeof(seq),"%llu",(unsigned long long)id);
    esp_http_client_set_method(http,HTTP_METHOD_POST);
    esp_http_client_set_header(http,"Content-Type","application/octet-stream");esp_http_client_set_header(http,"X-Client-ID",cid);esp_http_client_set_header(http,"X-Session-ID",session);esp_http_client_set_header(http,"X-Request-ID",seq);esp_http_client_set_header(http,"X-Model-SHA256",kNoPadSha);esp_http_client_set_header(http,"Connection",mode=='c'?"close":"keep-alive");
    esp_http_client_set_post_field(http,reinterpret_cast<char*>(tx+16),4640);
    ok=esp_http_client_perform(http)==ESP_OK&&esp_http_client_get_status_code(http)==200&&received==1760&&!strcmp(gotClient,cid)&&!strcmp(gotSession,session)&&!strcmp(gotSequence,seq);
    if(mode=='c'){esp_http_client_cleanup(http);http=nullptr;}
  }
  if(ok&&frame<3){ok=!memcmp(rx+32,kExpectedScores[frame],1728);}
  uint32_t reply[8];memcpy(reply,rx,32);
  ok=ok&&reply[0]==0x31524353&&reply[1]==1&&reply[2]==frame&&reply[3]==iteration&&reply[4]==432;
  for(int i=0;ok&&i<432;++i){float value;memcpy(&value,rx+32+4*i,4);ok=std::isfinite(value);}
  printf("{\"event\":\"exchange\",\"mode\":\"%c\",\"request_id\":%llu,\"frame\":%u,\"iteration\":%u,\"ok\":%s,\"request_response_us\":%lld,\"activation_crc\":%u,\"scores_crc\":%u,\"internal_min_free\":%u,\"stack_free\":%u}\n",mode,(unsigned long long)id,unsigned(frame),unsigned(iteration),ok?"true":"false",esp_timer_get_time()-start,unsigned(h[7]),unsigned(esp_rom_crc32_le(0,rx+32,1728)),unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)),unsigned(uxTaskGetStackHighWaterMark(nullptr)));
  if(!ok){disconnect();}
  if(ok)state=State::Ready;
  return ok;
}
}
