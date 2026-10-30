"""Compare Python decoding with actual functions extracted from the pinned SDK.

Provide the original downloaded ei_fill_result_struct.h; no source approximation
is used for the C++ side. Generated harness and binary live in a temporary folder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import numpy as np
from fomo_quality import decode

SDK_REVISION='c90298a297f6361a07f179173bbcd22790bb013f'
SDK_HEADER_SHA256='b49bcdb2345d6efdb9d3d78b2fb5c2bf1dc7fe9d11d9853e38b68ce094db0f29'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdk-header',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    original=args.sdk_header.read_bytes();text=original.decode()
    if hashlib.sha256(original).hexdigest()!=SDK_HEADER_SHA256:
        raise ValueError('Not the verified original SDK header')
    section=text[text.index('typedef struct cube {'):text.index('__attribute__((unused)) static EI_IMPULSE_ERROR fill_result_struct_i8_fomo')]
    prefix=r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#define EI_HAS_FOMO 1
#define EI_IMPULSE_OK 0
#define EI_IMPULSE_LAST_LAYER_NOT_AVAILABLE 1
typedef int EI_IMPULSE_ERROR;
struct ei_impulse_t {int input_width,label_count,object_detection_count;const char** categories;};
struct ei_learning_block_config_tflite_graph_t {float threshold;};
struct ei_impulse_result_bounding_box_t {const char* label;uint32_t x,y,width,height;float value;};
struct ei_impulse_result_t {ei_impulse_result_bounding_box_t* bounding_boxes;int bounding_boxes_count;};
#if 1
'''
    suffix=r'''
int main() {
  float a[432];const char* labels[]={"1","2"};ei_impulse_t impulse={96,2,0,labels};
  ei_learning_block_config_tflite_graph_t config={.5f};ei_impulse_result_t result;
  while(scanf("%f",&a[0])==1) {
    for(int i=1;i<432;++i) if(scanf("%f",&a[i])!=1) return 2;
    if(fill_result_struct_f32_fomo(&impulse,&config,&result,a,12,12)) return 3;
    printf("%d",result.bounding_boxes_count);
    for(int i=0;i<result.bounding_boxes_count;++i) {
      const auto& b=result.bounding_boxes[i];
      printf(" %s %u %u %u %u %.9g",b.label,b.x,b.y,b.width,b.height,b.value);
    }
    printf("\n");
  }
}
'''
    rng=np.random.default_rng(20261027)
    frames=[]
    for density in (.005,.02,.1,.5,1):
        for _ in range(50):
            a=np.zeros((12,12,3),dtype=np.float32)
            mask=rng.random((12,12,2))<density
            a[...,1:]=np.where(mask,rng.uniform(.5,1,mask.shape),0)
            frames.append(a)
    with tempfile.TemporaryDirectory(prefix='sciot-sdk-decoder-') as folder:
        source=Path(folder)/'verify.cpp';binary=Path(folder)/'verify'
        source.write_text(prefix+section+suffix)
        subprocess.run(['g++','-std=c++17','-O2',str(source),'-o',str(binary)],check=True)
        values='\n'.join(' '.join(format(float(x),'.9g') for x in a.flat) for a in frames)+'\n'
        process=subprocess.run([str(binary)],input=values,text=True,capture_output=True,check=True)
    lines=process.stdout.splitlines()
    if len(lines)!=len(frames):raise ValueError('Incomplete SDK output')
    for frame,line in zip(frames,lines):
        parts=line.split();count=int(parts[0]);actual=decode(frame)
        if len(actual)!=count:raise ValueError('Detection count mismatch')
        for i,box in enumerate(actual):
            fields=parts[1+6*i:1+6*(i+1)]
            if [box[k] for k in ('channel','x','y','width','height')]!=list(map(int,fields[:5])):
                raise ValueError('SDK box mismatch')
            np.testing.assert_allclose(box['score'],float(fields[5]),atol=1e-7,rtol=0)
    result={'sdk_revision':SDK_REVISION,'source_sha256':hashlib.sha256(original).hexdigest(),
            'random_seed':20261027,'maps_compared':len(frames),'matching':'exact counts/boxes/channels; scores atol 1e-7',
            'passed':True}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
