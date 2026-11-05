import unittest
from tools.multiclient.benchmark import check_power, check_profile


class PowerPreflightTests(unittest.TestCase):
    def test_desktop_and_external_power_allowed(self):
        for snapshot in ({'power':{}}, {'power':{'BAT0':{'status':'Charging'}}},
                         {'power':{'BAT0':{'status':'Full'}}}):
            check_power(snapshot)

    def test_discharging_requires_explicit_battery_scope(self):
        snapshot={'power':{'BAT0':{'status':'Discharging','capacity':'17'}}}
        with self.assertRaisesRegex(RuntimeError, 'external power'):
            check_power(snapshot)
        check_power(snapshot, allow_battery=True)

    def test_frequency_variation_allowed_but_energy_profile_change_rejected(self):
        before={'cpu':{'cpu0':{'scaling_governor':'powersave','energy_performance_preference':'power','scaling_cur_freq':'1100000'}}}
        after={'cpu':{'cpu0':{**before['cpu']['cpu0'],'scaling_cur_freq':'4000000'}}}
        check_profile(before,after)
        after['cpu']['cpu0']['energy_performance_preference']='performance'
        with self.assertRaisesRegex(RuntimeError, 'profile changed'):
            check_profile(before,after)

    def test_energy_groups_distinguish_power_and_profile_transitions(self):
        from tools.multiclient.benchmark import energy_scope
        ac={'power':{'BAT0':{'status':'Charging'}},'cpu':{'cpu0':{'scaling_governor':'powersave','energy_performance_preference':'balance_performance'}}}
        battery={'power':{'BAT0':{'status':'Discharging'}},'cpu':{'cpu0':{'scaling_governor':'powersave','energy_performance_preference':'power'}}}
        self.assertTrue(energy_scope(ac,ac).startswith('ac:'))
        self.assertTrue(energy_scope(battery,battery).startswith('battery:'))
        self.assertEqual(energy_scope(ac,battery),'transition')

    def test_scheduler_handles_deadline_crossing_without_negative_sleep(self):
        from tools.multiclient.load import wait_until
        from unittest.mock import Mock
        clock=Mock(side_effect=[.999,1.001])
        sleeper=Mock()
        wait_until(1.,clock,sleeper)
        clock.assert_called_once_with()
        self.assertGreater(sleeper.call_args.args[0],0)
        sleeper.reset_mock()
        wait_until(1.,lambda:1.001,sleeper)
        sleeper.assert_not_called()
