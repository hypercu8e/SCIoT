import unittest
from sweep_policy import choose_next

class SweepPolicyTests(unittest.TestCase):
    def test_initial_grid_then_refinement(self):
        observations={}
        for rate,passed in [(600,True),(800,False),(1000,False)]:
            self.assertEqual(choose_next(observations)[0],rate)
            observations[rate]=passed
        self.assertEqual(choose_next(observations)[0],700)
        observations[700]=True
        self.assertIsNone(choose_next(observations)[0])
        self.assertIn('700–800',choose_next(observations)[1])
    def test_unbracketed_search_is_bounded(self):
        all_pass={600:True,800:True,1000:True}
        for rate in (1500,2000,4000):
            self.assertEqual(choose_next(all_pass)[0],rate);all_pass[rate]=True
        self.assertIsNone(choose_next(all_pass)[0])
        all_fail={600:False,800:False,1000:False}
        for rate in (512,400,256,128):
            self.assertEqual(choose_next(all_fail)[0],rate);all_fail[rate]=False
        self.assertIsNone(choose_next(all_fail)[0])
    def test_nonmonotonic_results_are_not_forced_into_threshold(self):
        rate,reason=choose_next({600:False,800:True,1000:False})
        self.assertIsNone(rate);self.assertIn('nonmonotonic',reason)
