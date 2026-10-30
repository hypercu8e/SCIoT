cmake_minimum_required(VERSION 3.16)
get_filename_component(SCIOT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(sciot_multiclient)
