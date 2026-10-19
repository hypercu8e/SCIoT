/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* DEPENDENCIES LIBS
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
#include <WiFi.h>
#include <sys/time.h>
#include <UUID.h>
#include <ArduinoJson.h>
#include "esp_task_wdt.h"
#include "esp_camera.h"
#include <ArduinoWebsockets.h>

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* LIBS for TFLITE
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/system_setup.h"

#define MODEL_NAME "test_model"
#include "model_layers/layers.h"
#include "../../common/inference_message.h"
#include "../../common/float_layer.h"
#if __has_include("conf.h")
#include "conf.h"
#else
#include "conf.template.h"
#endif
static_assert(OUTPUT_MSG_SIZE >= sciot::inferenceMessageCapacity(MAX_ELEMENTS_PER_MODEL_LAYER, MAX_NUM_LAYER),
              "OUTPUT_MSG_SIZE is too small for this model");

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*  ARDUINO JSON CONFIGURATION
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
struct SpiRamAllocator : ArduinoJson::Allocator {
  void* allocate(size_t size) override {
    return heap_caps_malloc(size, MALLOC_CAP_SPIRAM);
  }

  void deallocate(void* pointer) override {
    heap_caps_free(pointer);
  }

  void* reallocate(void* ptr, size_t new_size) override {
    return heap_caps_realloc(ptr, new_size, MALLOC_CAP_SPIRAM);
  }
};

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*  CONFIGURATIONS & GLOBAL VARIABLES
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
// Communication & Offloading Variables
websockets::WebsocketsClient websocketClient;
// TimerHandle_t               websocketPollTimer;
TimerHandle_t               wifiReconnectTimer;
TimerHandle_t               deviceRegistrationTimer;
bool                        deviceRegistered = false;
UUID                        uuid;
String                      MessageUUID = "";
String                      DeviceUUID = "";
SpiRamAllocator             allocator;

float*                      inputBuffer = nullptr;
char*                       output_message = nullptr;

// Neural Network Variables
tflite::MicroErrorReporter  micro_error_reporter;
tflite::ErrorReporter*      error_reporter = &micro_error_reporter;
const tflite::Model*        model = nullptr;
tflite::AllOpsResolver      layerResolver;
uint8_t*                    tensor_arena = nullptr;
bool                        modelDataLoaded = false;
bool                        firmwareReady = false;
int                         best_offloading_layer_index = MAX_NUM_LAYER-1;
#ifdef FOMO
float*                      lastMultiOutputLayerData = nullptr;
#endif // FOMO

/*
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* TIMER CONFIGURATION & FLOATING-POINT TIMESTAMP
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
String getCurrTimeStr(){
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  time_t currentTime = tv.tv_sec;
  int milliseconds = tv.tv_usec / 1000;
  int microseconds = tv.tv_usec % 1000000;
  char currentTimeStr[30];
  snprintf(currentTimeStr, sizeof(currentTimeStr), "%ld.%03d%03d", currentTime, milliseconds, microseconds);
  String currentTimeString = String(currentTimeStr);
  return currentTimeString;
}

double getCurrTime(){
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  time_t currentTime = tv.tv_sec;
  int microseconds = tv.tv_usec;
  double timestamp = currentTime + (microseconds / 1000000.0);
  return timestamp;
}

void timeConfiguration(){
  // Configure NTP time synchronization
  configTime(NTP_GMT_OFFSET, NTP_DAYLIGHT_OFFSET, NTP_SRV);
  Serial.println("Connecting to NTP Server...");
  // Try obtaining the time until successful
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    delay(500);
  }

  // Print current time
  Serial.println("NTP Time Configured - Current Time: ");
  Serial.println(getCurrTime(), 6);
  return;
}

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* LOAD NN LAYER
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
const tflite::Model* loadNeuralNetworkLayer(const String& layer_name) {
  model = nullptr;
  LOAD_LAYER();
  return model;
}

void postDeviceInferenceResult(char* output_message, int size);

extern "C" void runNeuralNetworkLayer(int offloading_layer_index, float inputBuffer[]) {
  // Capture/validate this inference's split before accessing any model or buffer.
  if (!sciot::validSplit(offloading_layer_index, MAX_NUM_LAYER) || !inputBuffer || !tensor_arena) {
    Serial.println("Invalid split or unallocated inference buffers");
    return;
  }
  esp_task_wdt_add(NULL);
  constexpr size_t capacity = MAX_ELEMENTS_PER_MODEL_LAYER * sizeof(float);
  size_t inputBytes = BATCH_SIZE * IMAGE_HEIGHT * IMAGE_WIDTH * CHANNELS * sizeof(float);
  float inference_times[MAX_NUM_LAYER] = {};
  size_t residualBytes = 0;
#ifdef FOMO
  if (!lastMultiOutputLayerData) { Serial.println("Missing FOMO buffer"); return; }
  const int residualLayers[] = {16, 34, 43};
#endif
  for (int i = 0; i <= offloading_layer_index; ++i) {
    const uint32_t start = micros();
    const tflite::Model* layer = loadNeuralNetworkLayer("layer_" + String(i));
    size_t outputBytes = 0;
#ifdef FOMO
    const float* residual = lastMultiOutputLayerData;
#else
    const float* residual = nullptr;
#endif
    const sciot::LayerError error = sciot::runFloatLayer(
        layer, layerResolver, tensor_arena, K_TENSOR_ARENA_SIZE, error_reporter,
        inputBuffer, inputBytes, capacity, residual, residualBytes, outputBytes,
        []() { esp_task_wdt_reset(); });
    if (error != sciot::LayerError::Ok) {
      Serial.printf("Layer %d failed: %s\n", i, sciot::layerErrorText(error));
      return;  // A failed layer must never produce a valid-looking result packet.
    }
    inputBytes = outputBytes;
#ifdef FOMO
    for (int saved : residualLayers) {
      if (i == saved) {
        memcpy(lastMultiOutputLayerData, inputBuffer, outputBytes);
        residualBytes = outputBytes;
        break;
      }
    }
#endif
    // Keep the per-layer preparation/copy/compute cost used by the server.
    // Unsigned subtraction handles micros() wraparound for short intervals.
    inference_times[i] = static_cast<uint32_t>(micros() - start) / 1000000.0f;
    Serial.printf("Computed layer: %d Inf Time: %.6f s\n", i, inference_times[i]);
  }
  Serial.println("Model inference successful!");
  if (deviceRegistered) {
    size_t written = 0;
    if (!sciot::serializeInferenceResult(
            reinterpret_cast<uint8_t*>(output_message), OUTPUT_MSG_SIZE, getCurrTime(),
            DeviceUUID.c_str(), DeviceUUID.length(), MessageUUID.c_str(), MessageUUID.length(),
            offloading_layer_index, MAX_NUM_LAYER, inputBuffer, inputBytes / sizeof(float),
            inference_times, static_cast<size_t>(offloading_layer_index) + 1, written)) {
      Serial.println("Invalid inference result or insufficient message buffer");
      return;
    }
    postDeviceInferenceResult(output_message, static_cast<int>(written));
  }
}

/* Generate identifiers for registration and inference messages. */
void generateMessageUUID(){
  // Generate a UUID
  unsigned long seed = esp_random();
  uuid.seed(seed);
  uuid.setRandomMode();
  uuid.generate();
  String uuidStr = (String)uuid.toCharArray();
  MessageUUID = uuidStr.substring(0, 4);
  DeviceUUID = "device_01"; // + MessageUUID;
}

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* GET MODEL DATA FOR PREDICTION
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
void getModelDataForPrediction(const camera_fb_t* fb) {
  modelDataLoaded = false;
  if (!inputBuffer || !fb || !fb->buf || fb->format != PIXFORMAT_RGB565 ||
      fb->width != IMAGE_WIDTH || fb->height != IMAGE_HEIGHT || CHANNELS != 3 ||
      fb->len != static_cast<size_t>(IMAGE_WIDTH) * IMAGE_HEIGHT * 2 ||
      static_cast<size_t>(IMAGE_WIDTH) * IMAGE_HEIGHT * CHANNELS > MAX_ELEMENTS_PER_MODEL_LAYER) {
    Serial.println("Invalid RGB565 frame or input buffer");
    return;
  }
  uint16_t* pixels = (uint16_t*)fb->buf;
  int n = fb->height*fb->width;
  try {
    for (int i = 0; i < n; i++) {
      uint16_t p = pixels[i];
      // Convert big endian to little endian
      p = (p << 0x8) | (p >> 0x8);
      // Convert rgb565 image to normalized array of pixels rgb
      inputBuffer[i*3] = (p >> 11) / 31.0;
      inputBuffer[i*3+1] = ((p >> 5) & 0x3f) / 63.0;
      inputBuffer[i*3+2] = (p & 0x1f) / 31.0;
    }
    Serial.println("Model input data received");
  } catch (const std::exception& e) {
    Serial.print("Error receiving model input data: ");
    Serial.println(e.what());
    return;
  }
  modelDataLoaded = true;
}

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* WEBSOCKET CONFIGURATION
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
void postRegistration(){
  deviceRegistered = false;
  best_offloading_layer_index = MAX_NUM_LAYER-1;
  generateMessageUUID();        // Generate an Identifier for the message

  JsonDocument jsonDoc(&allocator);
  jsonDoc["device_id"] = DeviceUUID;
  String jsonMessage;
  serializeJson(jsonDoc, jsonMessage);

  if (!websocketClient.available()) {
    String url = "ws://" + String(WEBSOCKET_SRV) + ":" + String(WEBSOCKET_PORT) + "/ws";
    websocketClient.connect(url);
  }
  Serial.println("Sending registration request...");
  websocketClient.send(jsonMessage);
  Serial.println("Registration request sent");
}

void postDeviceInput(camera_fb_t *fb)
{
  if (!websocketClient.available()) {
    String url = "ws://" + String(WEBSOCKET_SRV) + ":" + String(WEBSOCKET_PORT) + "/ws";
    websocketClient.connect(url);
  }
  Serial.println("Sending device input...");
  websocketClient.sendBinary((char*)fb->buf, fb->len);
  Serial.println("Device input sent");
}

void postDeviceInferenceResult(char* output_message, int size)
{
  if (!websocketClient.available()) {
    String url = "ws://" + String(WEBSOCKET_SRV) + ":" + String(WEBSOCKET_PORT) + "/ws";
    websocketClient.connect(url);
  }
  Serial.println("Sending device inference result...");
  websocketClient.sendBinary(output_message, size);
  Serial.println("Device inference result sent");
}

void onEventsCallback(websockets::WebsocketsEvent event, String data) {
    if(event == websockets::WebsocketsEvent::ConnectionOpened) {
        Serial.println("Websocket connection opened");
    } else if(event == websockets::WebsocketsEvent::ConnectionClosed) {
        Serial.println("Websocket connection closed");
    } else if(event == websockets::WebsocketsEvent::GotPing) {
        Serial.println("Got a Ping!");
    } else if(event == websockets::WebsocketsEvent::GotPong) {
        Serial.println("Got a Pong!");
    }
}

void onMessageCallback(websockets::WebsocketsMessage message) {
  Serial.println("Server response received");
  JsonDocument doc(&allocator);
  DeserializationError error = deserializeJson(doc, message.c_str());
  
  if (!error)
  {
    if (doc["channel"] == "registration") {
      deviceRegistered = true;
      Serial.println("Registration successful!");
    } else if (doc["channel"] == "offloading_layer") {
      xTimerReset(deviceRegistrationTimer, 0);
      if (!doc["offloading_layer_index"].is<int>()) {
        Serial.println("Invalid offloading layer");
        return;
      }
      int tmp = doc["offloading_layer_index"].as<int>();

      if (tmp < 0 || tmp >= MAX_NUM_LAYER) {
        Serial.println("Invalid offloading layer");
        return;
      }
      best_offloading_layer_index = tmp;

      Serial.print("Best Offloading Layer Index: ");
      Serial.println(best_offloading_layer_index);
    }
  }
  else
  {
    Serial.print("JSON Parsing Failed: ");
    Serial.println(error.c_str());
  }
}

void websocketConfiguration() {
  websocketClient.onMessage(onMessageCallback);
  websocketClient.onEvent(onEventsCallback);
}

// void websocketPoll() {
//   websocketClient.poll();
// }

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* WIFI CONFIGURATION
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
void connectToWifi() {
  Serial.println("Connecting to WiFi...");
  WiFi.begin(SSID, PWD);
}

void WiFiEvent(WiFiEvent_t event) {
  switch(event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.println("WiFi connected");
      Serial.println("IP address: ");
      Serial.println(WiFi.localIP());
      timeConfiguration();          // Synchronize Timer - NTP server
      // xTimerStart(websocketPollTimer, 0);
      postRegistration();
      xTimerStart(deviceRegistrationTimer, 0);
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.println("WiFi lost connection");
      xTimerStop(deviceRegistrationTimer, 0);
      xTimerStart(wifiReconnectTimer, 0);
      break;
  }
}

void wifiConfiguration(){
  WiFi.onEvent(WiFiEvent);
}

/* 
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
* CAMERA CONFIGURATION
* ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
*/
bool cameraConfiguration(){
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = CAMERA_PIN_D0;
  config.pin_d1 = CAMERA_PIN_D1;
  config.pin_d2 = CAMERA_PIN_D2;
  config.pin_d3 = CAMERA_PIN_D3;
  config.pin_d4 = CAMERA_PIN_D4;
  config.pin_d5 = CAMERA_PIN_D5;
  config.pin_d6 = CAMERA_PIN_D6;
  config.pin_d7 = CAMERA_PIN_D7;
  config.pin_xclk = CAMERA_PIN_XCLK;
  config.pin_pclk = CAMERA_PIN_PCLK;
  config.pin_vsync = CAMERA_PIN_VSYNC;
  config.pin_href = CAMERA_PIN_HREF;
  config.pin_sccb_sda = CAMERA_PIN_SIOD;
  config.pin_sccb_scl = CAMERA_PIN_SIOC;
  config.pin_pwdn = CAMERA_PIN_PWDN;
  config.pin_reset = CAMERA_PIN_RESET;
  config.xclk_freq_hz = XCLK_FREQ_HZ;
  config.pixel_format = PIXFORMAT_RGB565;
  config.frame_size = FRAMESIZE_CUSTOM;
  config.jpeg_quality = 10;
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
      Serial.printf("Camera init failed with error 0x%x\n", err);
      return false;
  }
  Serial.println("Camera initialized successfully.");
  return true;
}

/*
 * ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 * SETUP 
 * ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 */
void setup() {
  Serial.begin(115200);
  
  esp_task_wdt_init(WDT_TIMEOUT, true); // Watchdog Timer

  if (psramInit()) {
    Serial.println("The PSRAM is correctly initialized");
  } else {
    Serial.println("PSRAM does not work");
    return;
  }

  inputBuffer = (float*)ps_malloc(MAX_ELEMENTS_PER_MODEL_LAYER*sizeof(float)); 
  tensor_arena = (uint8_t*)heap_caps_aligned_alloc(16, K_TENSOR_ARENA_SIZE, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  output_message = (char*)ps_malloc(OUTPUT_MSG_SIZE);
#ifdef FOMO
  lastMultiOutputLayerData = (float*)ps_malloc(MAX_ELEMENTS_PER_MODEL_LAYER*sizeof(float)); 
#endif // FOMO

  if (!inputBuffer || !tensor_arena || !output_message
#ifdef FOMO
      || !lastMultiOutputLayerData
#endif
  ) {
    Serial.println("Inference buffer allocation failed");
    free(inputBuffer); inputBuffer = nullptr;
    free(tensor_arena); tensor_arena = nullptr;
    free(output_message); output_message = nullptr;
#ifdef FOMO
    free(lastMultiOutputLayerData); lastMultiOutputLayerData = nullptr;
#endif
    return;
  }
  if (!cameraConfiguration()) return;  // Stop before networking/capture on failure.
  firmwareReady = true;

  wifiReconnectTimer = xTimerCreate("wifiTimer", pdMS_TO_TICKS(2000), pdFALSE, (void*)0, reinterpret_cast<TimerCallbackFunction_t>(connectToWifi));
  deviceRegistrationTimer = xTimerCreate("registrationTimer", pdMS_TO_TICKS(30000), pdTRUE, (void*)0, reinterpret_cast<TimerCallbackFunction_t>(postRegistration));
  // websocketPollTimer = xTimerCreate("websocketPollTimer", pdMS_TO_TICKS(500), pdTRUE, (void*)0, reinterpret_cast<TimerCallbackFunction_t>(websocketPoll));
  wifiConfiguration();          // Wi-Fi Connection
  websocketConfiguration();
  connectToWifi();
  delay(5000);
}

/* 
 * ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 * LOOP 
 * ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 */
void loop() {
  if (!firmwareReady) { delay(1000); return; }
  websocketClient.poll();
  // Capture a frame
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
      Serial.println("Failed to capture image");
      return;
  }
  Serial.printf("Captured image with size: %u bytes\n", fb->len);

  websocketClient.poll();
  // Send captured image
  if (deviceRegistered) {
    // getOffloadingLayer();
    postDeviceInput(fb);
    Serial.println("Captured image sent");
  }

  websocketClient.poll();
  // Parse input for model
  getModelDataForPrediction(fb);

  websocketClient.poll();
  // Run inference and send results
  if (modelDataLoaded) {
    runNeuralNetworkLayer(best_offloading_layer_index, inputBuffer);
    modelDataLoaded = false;
  }

  websocketClient.poll();
  // Free the frame buffer
  esp_camera_fb_return(fb);
}
