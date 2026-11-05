#pragma once
#include <cstddef>
#include <cstdint>
// Server-side decoder only. The independent Python decoder audits every packet.
inline int decodeRice(const uint8_t* data,size_t length,const int16_t* previous,
                      int zero,int8_t* out) {
  constexpr size_t Count=4608;
  if(length<8 || length>=Count)return 1;
  for(int c=0;c<8;++c)if(data[c]>8)return 2;
  size_t pos=64;
  auto bit=[&]()->int {
    if(pos>=length*8)return -1;
    int result=(data[pos/8]>>(7-pos%8))&1;++pos;return result;
  };
  for(size_t i=0;i<Count;++i) {
    unsigned k=data[i%8],q=0;int b;
    while((b=bit())==0)if(++q>510)return 3;
    if(b<0)return 4;
    unsigned u=q<<k;
    for(int j=int(k)-1;j>=0;--j){b=bit();if(b<0)return 4;u|=unsigned(b)<<j;}
    if(u>510)return 3;
    int residual=(u&1)?-int(u/2)-1:int(u/2);
    int value=residual+(previous?int(previous[i]):zero);
    if(value<-128 || value>127)return 5;
    out[i]=int8_t(value);
  }
  if(length!=(pos+7)/8)return 6;
  while(pos<length*8)if(bit()!=0)return 7;
  return 0;
}
