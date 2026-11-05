idf_component_register(SRCS "main.cpp" "../../../esp32_representation_benchmark/idf/src/kernel_probe.cpp"
    INCLUDE_DIRS "../../include"
    EMBED_FILES "../../artifacts/video-inputs.bin"
    REQUIRES esp-tflite-micro esp-nn esp32-camera esp_wifi esp_http_client nvs_flash esp_timer esp_psram driver miniz_idf)
target_compile_features(${COMPONENT_LIB} PRIVATE cxx_std_17)
target_compile_options(${COMPONENT_LIB} PRIVATE -ffp-contract=off)
target_link_libraries(${COMPONENT_LIB} INTERFACE "-Wl,--wrap=esp_nn_conv_s8_esp32s3" "-Wl,--wrap=esp_nn_depthwise_conv_s8_esp32s3")
