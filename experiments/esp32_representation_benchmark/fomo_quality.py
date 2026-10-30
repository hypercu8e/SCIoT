"""FOMO box decoding following the pinned Edge Impulse SDK two-pass algorithm.

Source: classifier/ei_fill_result_struct.h, SDK c90298a297f6361a07f179173bbcd22790bb013f.
Class IDs remain anonymous. Matching is class-agnostic: a predicted center must
fall inside an annotated box; maximum bipartite matching prevents double credit.
"""
import numpy as np


def overlap_update(c, box):
    x,y,w,h,score,channel=box
    if c[5]!=channel or c[0]+c[2]<x or c[1]+c[3]<y or c[0]>x+w or c[1]>y+h:
        return False
    # Preserve the SDK's update order, including its lower-coordinate behavior.
    if x<c[0]:c[0]=x;c[2]+=c[0]-x
    if y<c[1]:c[1]=y;c[3]+=c[1]-y
    if x+w>c[0]+c[2]:c[2]+=(x+w)-(c[0]+c[2])
    if y+h>c[1]+c[3]:c[3]+=(y+h)-(c[1]+c[3])
    c[4]=max(c[4],score)
    return True


def decode(scores,threshold=.5):
    a=np.asarray(scores).reshape(12,12,3)
    cubes=[]
    for y in range(12):
        for x in range(12):
            for channel in (1,2):
                confidence=float(a[y,x,channel])
                if confidence<threshold:continue
                box=[x,y,1,1,confidence,channel]
                if not any(overlap_update(c,box) for c in cubes):cubes.append(box)
    merged=[];results=[]
    for cube in cubes:
        if any(overlap_update(c,cube) for c in merged):continue
        merged.append(cube)
        # The official SDK stores the result at insertion, before later merges.
        results.append({'channel':cube[5],'score':cube[4],'x':cube[0]*8,'y':cube[1]*8,
                        'width':cube[2]*8,'height':cube[3]*8})
    return results


def match(detections,truth):
    edges=[]
    for detection in detections:
        x=detection['x']+detection['width']/2;y=detection['y']+detection['height']/2
        edges.append([i for i,b in enumerate(truth)
                      if b['x']<=x<=b['x']+b['width'] and b['y']<=y<=b['y']+b['height']])
    assigned={}
    def augment(pred,seen):
        for target in edges[pred]:
            if target in seen:continue
            seen.add(target)
            if target not in assigned or augment(assigned[target],seen):
                assigned[target]=pred;return True
        return False
    for pred in range(len(detections)):augment(pred,set())
    return {'tp':len(assigned),'fp':len(detections)-len(assigned),'fn':len(truth)-len(assigned),
            'matched_annotation_indices':sorted(assigned)}


def totals(rows):
    out={k:sum(row[k] for row in rows) for k in ('tp','fp','fn')}
    tp,fp,fn=out['tp'],out['fp'],out['fn']
    out.update(precision=tp/(tp+fp) if tp+fp else 0,
               recall=tp/(tp+fn) if tp+fn else 0,
               f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
    return out
