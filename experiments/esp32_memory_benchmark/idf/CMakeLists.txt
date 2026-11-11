cmake_minimum_required(VERSION 3.16)
get_filename_component(SCIOT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(sciot_memory_benchmark)
# Explicit local dependency replaces the registry manifest when building offline.
idf_component_get_property(profile_tflm_lib esp-tflite-micro COMPONENT_LIB)
idf_component_get_property(profile_espnn_lib esp-nn COMPONENT_LIB)
target_link_libraries(${profile_tflm_lib} PUBLIC ${profile_espnn_lib})
