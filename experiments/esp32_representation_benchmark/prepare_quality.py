"""Freeze all 84 public annotated test inputs independently of model outputs."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
COMPRESSION=HERE.parent/'activation_compression'
sys.path.insert(0,str(COMPRESSION))
from check_public_images import prepare_image

def main():
    dataset=COMPRESSION/'results/public_test_data'
    manifest=json.loads((dataset/'manifest.json').read_text())
    frames=[];records=[]
    for index,item in enumerate(manifest['edgeimpulse_test_images']):
        path=dataset/item['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Dataset image hash mismatch')
        with Image.open(path) as image:
            width,height=image.size
            _,gray=prepare_image(image)
        side=min(width,height);left=(width-side)//2;top=(height-side)//2
        boxes=[];excluded=[]
        for box in item['bounding_boxes']:
            x=box['x'];y=box['y'];w=box['width'];h=box['height']
            # Evaluate only annotated objects whose original center survives crop.
            if not (left<=x+w/2<left+side and top<=y+h/2<top+side):
                excluded.append(box);continue
            x0=max(x,left);y0=max(y,top);x1=min(x+w,left+side);y1=min(y+h,top+side)
            boxes.append({'label':box['label'],'x':(x0-left)*96/side,'y':(y0-top)*96/side,
                          'width':(x1-x0)*96/side,'height':(y1-y0)*96/side})
        frames.append(gray)
        records.append({'frame':3000+index,'source_id':item['id'],'source_sha256':item['sha256'],
                        'boxes':boxes,'excluded_outside_crop':excluded})
    frames=np.asarray(frames,dtype='<f4')
    binary=frames.tobytes()
    out=HERE/'artifacts';out.mkdir(exist_ok=True)
    (out/'quality-inputs.bin').write_bytes(binary)
    np.save(out/'quality-inputs.npy',frames,allow_pickle=False)
    info={'count':len(frames),'input_sha256':hashlib.sha256(binary).hexdigest(),
          'preprocessing':'center square crop, Lanczos 96x96, BT.601 grayscale float32 [0,1]',
          'class_channels':'unconfirmed; use class-agnostic matching and report class-order ambiguity',
          'records':records}
    (out/'quality-inputs.json').write_text(json.dumps(info,indent=2)+'\n')
    (HERE/'include/generated/quality.h').write_text(
        '#pragma once\nstatic const int kQualityCount = '+str(len(frames))+';\n'
        'static const char kQualitySha[] = "'+info['input_sha256']+'";\n')
    print(f'Prepared {len(frames)} annotated images, {len(binary)} embedded bytes, sha256 {info["input_sha256"]}')

if __name__=='__main__':main()
