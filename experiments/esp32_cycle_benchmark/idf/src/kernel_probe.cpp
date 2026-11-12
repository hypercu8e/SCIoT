// Linker wrappers verify that Invoke reaches the ESP32-S3 optimized entrypoints.
#include <cstdint>
#include "esp_nn.h"

uint32_t sciotConvCalls=0,sciotDepthwiseCalls=0;

extern "C" void __real_esp_nn_conv_s8_esp32s3(const data_dims_t*,const int8_t*,
    const data_dims_t*,const int8_t*,const int32_t*,const data_dims_t*,int8_t*,
    const conv_params_t*,const quant_data_t*);
extern "C" void __wrap_esp_nn_conv_s8_esp32s3(const data_dims_t* i,const int8_t* input,
    const data_dims_t* f,const int8_t* filter,const int32_t* bias,const data_dims_t* o,
    int8_t* output,const conv_params_t* params,const quant_data_t* quant) {
  ++sciotConvCalls;
  __real_esp_nn_conv_s8_esp32s3(i,input,f,filter,bias,o,output,params,quant);
}
extern "C" void __real_esp_nn_depthwise_conv_s8_esp32s3(const data_dims_t*,const int8_t*,
    const data_dims_t*,const int8_t*,const int32_t*,const data_dims_t*,int8_t*,
    const dw_conv_params_t*,const quant_data_t*);
extern "C" void __wrap_esp_nn_depthwise_conv_s8_esp32s3(const data_dims_t* i,const int8_t* input,
    const data_dims_t* f,const int8_t* filter,const int32_t* bias,const data_dims_t* o,
    int8_t* output,const dw_conv_params_t* params,const quant_data_t* quant) {
  ++sciotDepthwiseCalls;
  __real_esp_nn_depthwise_conv_s8_esp32s3(i,input,f,filter,bias,o,output,params,quant);
}
