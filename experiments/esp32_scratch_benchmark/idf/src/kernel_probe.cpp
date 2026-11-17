#include "probe.h"
#include "esp_nn.h"
#include "esp_timer.h"

bool sciotKernelTiming=false;
uint32_t sciotConvCalls=0,sciotDepthwiseCalls=0;
int64_t sciotConvUs=0,sciotDepthwiseUs=0;

extern "C" void __real_esp_nn_conv_s8_esp32s3(const data_dims_t*,const int8_t*,
    const data_dims_t*,const int8_t*,const int32_t*,const data_dims_t*,int8_t*,
    const conv_params_t*,const quant_data_t*);
extern "C" void __wrap_esp_nn_conv_s8_esp32s3(const data_dims_t* i,const int8_t* input,
    const data_dims_t* f,const int8_t* filter,const int32_t* bias,const data_dims_t* o,
    int8_t* output,const conv_params_t* params,const quant_data_t* quant) {
  ++sciotConvCalls;
  const int64_t start=sciotKernelTiming?esp_timer_get_time():0;
  __real_esp_nn_conv_s8_esp32s3(i,input,f,filter,bias,o,output,params,quant);
  if(sciotKernelTiming) sciotConvUs+=esp_timer_get_time()-start;
}
extern "C" void __real_esp_nn_depthwise_conv_s8_esp32s3(const data_dims_t*,const int8_t*,
    const data_dims_t*,const int8_t*,const int32_t*,const data_dims_t*,int8_t*,
    const dw_conv_params_t*,const quant_data_t*);
extern "C" void __wrap_esp_nn_depthwise_conv_s8_esp32s3(const data_dims_t* i,const int8_t* input,
    const data_dims_t* f,const int8_t* filter,const int32_t* bias,const data_dims_t* o,
    int8_t* output,const dw_conv_params_t* params,const quant_data_t* quant) {
  ++sciotDepthwiseCalls;
  const int64_t start=sciotKernelTiming?esp_timer_get_time():0;
  __real_esp_nn_depthwise_conv_s8_esp32s3(i,input,f,filter,bias,o,output,params,quant);
  if(sciotKernelTiming) sciotDepthwiseUs+=esp_timer_get_time()-start;
}
