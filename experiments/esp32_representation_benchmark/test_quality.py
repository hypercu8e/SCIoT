import unittest
import numpy as np
from fomo_quality import decode,match


class QualityTests(unittest.TestCase):
    def test_adjacent_cells_and_classes(self):
        a=np.zeros((12,12,3),dtype=np.float32)
        a[2,2,1]=.8;a[3,3,1]=.9;a[2,2,2]=.7
        result=decode(a)
        self.assertEqual(len(result),2)
        self.assertEqual((result[0]['width'],result[0]['height']),(16,16))
        self.assertEqual(result[1]['channel'],2)

    def test_matching_uses_maximum_assignment(self):
        # First prediction fits both boxes, second fits only the first.
        detections=[{'x':5,'y':0,'width':0,'height':0},{'x':1,'y':0,'width':0,'height':0}]
        truth=[{'x':0,'y':0,'width':6,'height':2},{'x':4,'y':0,'width':6,'height':2}]
        self.assertEqual(match(detections,truth)['tp'],2)

    def test_duplicates_get_no_extra_credit(self):
        box={'x':0,'y':0,'width':8,'height':8}
        result=match([box,box],[box])
        self.assertEqual((result['tp'],result['fp'],result['fn']),(1,1,0))

if __name__=='__main__':unittest.main()
