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

