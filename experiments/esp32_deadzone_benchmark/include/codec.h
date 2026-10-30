#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace dz {
constexpr int N=4608, Count=12, HeaderBytes=80, ReplyBytes=48+432*4, Capacity=8192;
constexpr uint32_t None=0xffffffffu, Magic=0x315a4453u, ReplyMagic=0x31524453u;
struct Config { int mode,bits,level; };
constexpr Config Configs[Count]={{0,0,0},{1,0,1},{1,0,6},
  {2,4,6},{2,6,6},{2,8,6},{3,4,6},{3,6,6},{3,8,6},{4,4,6},{4,6,6},{4,8,6}};
inline uint32_t crc(const void* data,size_t size) {
  auto p=static_cast<const uint8_t*>(data);uint32_t v=0xffffffffu;
  while(size--) {v^=*p++;for(int b=0;b<8;++b)v=(v>>1)^(0xedb88320u&(0u-(v&1u)));}
  return ~v;
}
inline float dequant(int8_t x,double scale,int zero) {return float((double(x)-zero)*scale);}
inline int8_t requant(float x,double scale,int zero) {
  return int8_t(std::max(-128.0,std::min(127.0,std::nearbyint(double(x)/scale+zero))));
}
// Caller owns all workspace. No allocation, compression or networking here.
inline float encode(const int8_t* input,const float* previous,float* state,
                    int8_t* symbols,float* work,int config,bool delta,double scale,int zero) {
  const auto c=Configs[config];
  if(c.mode<2) {
    memcpy(symbols,input,N);
    for(int i=0;i<N;++i)state[i]=dequant(input[i],scale,zero);
    return 0;
  }
  for(int i=0;i<N;++i) {
    float x=dequant(input[i],scale,zero);
    if(delta)x=float(double(x)-double(previous[i]));
    state[i]=x;work[i]=std::abs(x);
  }
  constexpr int rank=(99*N+99)/100-1;
  std::nth_element(work,work+rank,work+N);
  const float radius=work[rank];
  const double step=2.0*double(radius)/double(1<<c.bits);
  const int limit=1<<(c.bits-1);
  for(int i=0;i<N;++i) {
    double index=radius?std::nearbyint(double(state[i])/step):0;
    if(delta && c.mode==4 && std::abs(double(state[i]))<.75*step)index=0;
    index=std::max(double(-limit),std::min(double(limit-1),index));
    symbols[i]=int8_t(index);
    const float residual=float(double(symbols[i])*step);
    state[i]=delta?float(double(previous[i])+double(residual)):residual;
  }
  return radius;
}
}
