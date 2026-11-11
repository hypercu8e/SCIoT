#include "fast_pad.h"
#include "probe.h"
#include "tensorflow/lite/kernels/internal/reference/pad.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/kernels/pad.h"

bool sciotPadCheck=false;
int8_t* sciotPadScratch=nullptr;
size_t sciotPadScratchBytes=0;
uint32_t sciotFastPadCalls=0,sciotPadChecks=0,sciotPadMismatchBytes=0,sciotPadComparedBytes=0;

namespace {
// Prepare, OpData and the pad value are TFLM's own; only Eval differs.
TfLiteStatus FastPadEval(TfLiteContext* context,TfLiteNode* node) {
  const auto* data=static_cast<const tflite::OpData*>(node->user_data);
  const TfLiteEvalTensor* input=tflite::micro::GetEvalInput(context,node,0);
  const TfLiteEvalTensor* constant=tflite::NumInputs(node)==3?tflite::micro::GetEvalInput(context,node,2):nullptr;
  TfLiteEvalTensor* output=tflite::micro::GetEvalOutput(context,node,0);
  const auto& p=data->params;
  const bool fast=input->type==kTfLiteInt8 && input->dims->size==4 && output->dims->size==4 &&
      p.left_padding_count==4 && p.right_padding_count==4 &&
      p.left_padding[0]==0 && p.right_padding[0]==0 && p.left_padding[3]==0 && p.right_padding[3]==0;
  if(!fast) {
    static const TFLMRegistration reference=tflite::Register_PAD();
    return reference.invoke(context,node);
  }
  // Same expression as the TFLM int8 path.
  const int8_t value=constant?*tflite::micro::GetTensorData<int8_t>(constant)
                             :int8_t(static_cast<uint8_t>(data->output_zero_point));
  const int* d=input->dims->data;
  int8_t* out=tflite::micro::GetTensorData<int8_t>(output);
  const int8_t* in=tflite::micro::GetTensorData<int8_t>(input);
  fastPadHW(in,d[0],d[1],d[2],d[3],p.left_padding[1],p.right_padding[1],
            p.left_padding[2],p.right_padding[2],value,out);
  ++sciotFastPadCalls;
  if(sciotPadCheck) {
    const auto inShape=tflite::micro::GetTensorShape(input);
    const auto outShape=tflite::micro::GetTensorShape(output);
    const size_t bytes=size_t(outShape.FlatSize());
    if(!sciotPadScratch || bytes>sciotPadScratchBytes) return kTfLiteError;
    tflite::reference_ops::PadImageStyle(p,inShape,in,&value,outShape,sciotPadScratch);
    for(size_t i=0;i<bytes;++i) sciotPadMismatchBytes+=out[i]!=sciotPadScratch[i];
    sciotPadComparedBytes+=bytes;++sciotPadChecks;
  }
  return kTfLiteOk;
}
}

TFLMRegistration RegisterFastPad() {
  return tflite::micro::RegisterOp(tflite::PadInit,tflite::PadPrepare,FastPadEval);
}
