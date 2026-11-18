idf_component_register(SRCS "main.cpp" "kernel_probe.cpp" "fast_pad.cpp" "xclk_probe.cpp" "gated_camera.cpp"
  INCLUDE_DIRS "${SCIOT_ROOT}/experiments/esp32_representation_benchmark/include" "${SCIOT_ROOT}/experiments/esp32_websocket_benchmark/include"
  REQUIRES esp_websocket_client esp-tflite-micro esp-nn esp32-camera esp_wifi esp_http_client nvs_flash esp_timer esp_psram driver json lwip)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_17)
target_link_libraries(${COMPONENT_LIB} INTERFACE
  "-Wl,--wrap=esp_nn_conv_s8_esp32s3"
  "-Wl,--wrap=esp_nn_depthwise_conv_s8_esp32s3")
