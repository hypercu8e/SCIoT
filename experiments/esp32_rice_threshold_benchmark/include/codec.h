#pragma once
#include "legacy_codec.h"
namespace dz {
constexpr int N=4608,Count=6,HeaderBytes=80,ReplyBytes=48+432*4,Capacity=8192;
constexpr uint32_t None=0xffffffffu,Magic=0x32434c53,ReplyMagic=0x32524c53;
struct Config {int mode,bits,level;};
constexpr Config Configs[Count]={{0,0,0},{1,0,1},{2,0,0},{3,0,0},{4,4,6},{5,4,0}};
using legacy::crc;using legacy::requant;using legacy::dequant;
inline unsigned zig(int x){return x<0?unsigned(-2*x-1):unsigned(2*x);}
// Exact Rice lengths are accumulated per channel in a single pass. No allocation.
// Zero return means raw fallback; no partial or expanded Rice stream is emitted.
inline size_t rice(const int8_t* x,const int8_t* previous,bool delta,int zero,uint8_t* out) {
  uint32_t costs[8][9]={};
  for(int i=0;i<N;++i){unsigned u=zig(int(x[i])-(delta?int(previous[i]):zero));
    for(int k=0;k<=8;++k)costs[i%8][k]+=(u>>k)+1+k;}
  unsigned bits=64,kvals[8];
  for(int c=0;c<8;++c){unsigned best=0;for(unsigned k=1;k<=8;++k)if(costs[c][k]<costs[c][best])best=k;
    kvals[c]=best;bits+=costs[c][best];}
  size_t bytes=(bits+7)/8;if(bytes>=N)return 0;
  memset(out,0,bytes);for(int c=0;c<8;++c)out[c]=uint8_t(kvals[c]);
  unsigned pos=64;
  auto bit=[&](unsigned v){out[pos/8]|=uint8_t(v<<(7-pos%8));++pos;};
  for(int i=0;i<N;++i){unsigned u=zig(int(x[i])-(delta?int(previous[i]):zero)),k=kvals[i%8];
    for(unsigned q=u>>k;q;--q){bit(0);}
    bit(1);
    for(int b=int(k)-1;b>=0;--b)bit((u>>b)&1);}
  return bytes;
}
inline void pack4(const int8_t* q,uint8_t* out){for(int i=0;i<N;i+=2)out[i/2]=uint8_t(((unsigned(q[i])&15)<<4)|(unsigned(q[i+1])&15));}
}
