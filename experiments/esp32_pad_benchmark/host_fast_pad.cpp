// Host check: fastPadHW against the unmodified TFLM reference kernel.
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>
#include "tensorflow/lite/kernels/internal/reference/pad.h"
#include "fast_pad.h"

static bool check(std::mt19937& rng,int batch,int h,int w,int d,int top,int bottom,int left,int right,int8_t value) {
  std::vector<int8_t> in(size_t(batch)*h*w*d);
  for(auto& v:in) v=int8_t(int(rng()%256)-128);
  const int oh=h+top+bottom,ow=w+left+right;
  std::vector<int8_t> ref(size_t(batch)*oh*ow*d,0x55),fast(ref.size(),0x2a);
  tflite::PadParams p{};
  p.left_padding_count=p.right_padding_count=4;
  const int l[4]={0,top,left,0},r[4]={0,bottom,right,0};
  for(int i=0;i<4;++i) {p.left_padding[i]=l[i];p.right_padding[i]=r[i];}
  p.resizing_category=tflite::ResizingCategory::kImageStyle;
  const int32_t inDims[4]={batch,h,w,d},outDims[4]={batch,oh,ow,d};
  tflite::reference_ops::PadImageStyle(p,tflite::RuntimeShape(4,inDims),in.data(),&value,
                                       tflite::RuntimeShape(4,outDims),ref.data());
  fastPadHW(in.data(),batch,h,w,d,top,bottom,left,right,value,fast.data());
  if(ref!=fast) {
    std::printf("MISMATCH b=%d h=%d w=%d d=%d pads=%d,%d,%d,%d value=%d\n",batch,h,w,d,top,bottom,left,right,value);
    return false;
  }
  return true;
}

int main() {
  std::mt19937 rng(20261111);
  int cases=0;
  // The frozen model: 1x48x48x48, one row bottom, one column right, zero point -128.
  if(!check(rng,1,48,48,48,0,1,0,1,-128)) return 1;
  ++cases;
  for(int i=0;i<2000;++i) {
    const int batch=1+rng()%2,h=1+rng()%9,w=1+rng()%9,d=1+rng()%17;
    const int top=rng()%3,bottom=rng()%3,left=rng()%3,right=rng()%3;
    if(!check(rng,batch,h,w,d,top,bottom,left,right,int8_t(int(rng()%256)-128))) return 1;
    ++cases;
  }
  std::printf("OK %d cases\n",cases);
  return 0;
}
