import unittest

from hardware.frogdash.state import State


class Clock:
    def __init__(self): self.now = 10.0
    def __call__(self): return self.now


class BoostHoldTests(unittest.TestCase):
    def test_slow_ecu_groups_and_held_baro_keep_boost_live(self):
        clock = Clock()
        state = State(clock=clock)
        state.connected = True
        state.ingest(0x5F2, bytes.fromhex('03F503F504D80488'))  # group 2: baro 101.3, MAP 101.3
        self.assertEqual(state.snapshot()['values']['engine.boost_kpa']['quality'], 'live')
        clock.now += .8  # A 2 Hz group is still live.
        self.assertEqual(state.snapshot()['values']['engine.boost_kpa']['quality'], 'live')
        clock.now += 30
        state.ingest(0x5E8, bytes.fromhex('05DC0BB8030C0190'))  # dash broadcast: MAP 150.0, no baro
        boost = state.snapshot()['values']['engine.boost_kpa']
        self.assertEqual(boost['quality'], 'live')
        self.assertAlmostEqual(boost['value'], 48.7, places=1)


if __name__ == '__main__':
    unittest.main()
