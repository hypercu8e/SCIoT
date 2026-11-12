#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

// NHWC int8 padding on height and width only. Each output row is one border
// fill, one contiguous copy of the input row and one more border fill, instead
// of a per-element bounds check. Byte-for-byte equivalent to TFLM PadImpl for
// this layout (verified on the host and on the device).
inline void fastPadHW(const int8_t* in,int batch,int inH,int inW,int depth,
                      int top,int bottom,int left,int right,int8_t value,int8_t* out) {
  const size_t rowIn=size_t(inW)*depth;
  const size_t leftBytes=size_t(left)*depth,rightBytes=size_t(right)*depth;
  const size_t rowOut=leftBytes+rowIn+rightBytes;
  for(int b=0;b<batch;++b) {
    if(top) {memset(out,value,size_t(top)*rowOut);out+=size_t(top)*rowOut;}
    for(int h=0;h<inH;++h) {
      if(leftBytes) memset(out,value,leftBytes);
      memcpy(out+leftBytes,in,rowIn);
      if(rightBytes) memset(out+leftBytes+rowIn,value,rightBytes);
      out+=rowOut;in+=rowIn;
    }
    if(bottom) {memset(out,value,size_t(bottom)*rowOut);out+=size_t(bottom)*rowOut;}
  }
}
