"""Dash values filled from the ECU when the car's own modules give none (state.FROM_ECU)."""
import unittest

from hardware.frogdash.state import AFR_FROM_LAMBDA, FROM_ECU, KPA_PER_PSI, STOICH_AFR, fill_from_ecu

AFR = [(afr, lam, lambda v: v * STOICH_AFR) for afr, lam in AFR_FROM_LAMBDA]


def sample(value, quality='live', source_id=0x360):
    return {'value': value, 'quality': quality, 'source_id': source_id, 'timestamp_ms': 1}


class FillFromEcuTests(unittest.TestCase):
    def test_lambda_becomes_afr_on_the_petrol_scale(self):
        values = {'ecu.lambda1': sample(1.0), 'ecu.lambda_target': sample(0.8)}
        fill_from_ecu(values, AFR)
        self.assertAlmostEqual(values['ecu.afr']['value'], 14.7)
        self.assertAlmostEqual(values['ecu.afr_target']['value'], 11.76)
        self.assertEqual(values['ecu.afr']['from'], 'ecu.lambda1')
        self.assertNotIn('ecu.afr2', values)

    def test_an_ecu_that_sends_afr_keeps_its_own(self):
        values = {'ecu.afr': sample(13.2, source_id=0x5EC), 'ecu.lambda1': sample(1.0)}
        fill_from_ecu(values, AFR)
        self.assertEqual(values['ecu.afr']['value'], 13.2)

    def test_a_live_module_reading_wins_over_the_ecu(self):
        values = {'engine.oil_pressure_psi': sample(42.0, source_id=0x303), 'ecu.oil_pressure_kpa': sample(300.0)}
        fill_from_ecu(values, FROM_ECU)
        self.assertEqual(values['engine.oil_pressure_psi']['value'], 42.0)

    def test_ecu_pressure_in_kpa_shows_in_psi(self):
        values = {'ecu.oil_pressure_kpa': sample(KPA_PER_PSI * 40), 'ecu.fuel_pressure_kpa': sample(KPA_PER_PSI * 43.5)}
        fill_from_ecu(values, FROM_ECU)
        self.assertAlmostEqual(values['engine.oil_pressure_psi']['value'], 40)
        self.assertAlmostEqual(values['engine.fuel_pressure_psi']['value'], 43.5)

    def test_a_stale_module_reading_gives_way_only_to_a_live_ecu_one(self):
        stale = sample(41.0, 'stale', 0x303)
        values = {'engine.oil_pressure_psi': dict(stale), 'ecu.oil_pressure_kpa': sample(100.0, 'stale')}
        fill_from_ecu(values, FROM_ECU)
        self.assertEqual(values['engine.oil_pressure_psi'], stale)
        values['ecu.oil_pressure_kpa'] = sample(100.0)
        fill_from_ecu(values, FROM_ECU)
        self.assertAlmostEqual(values['engine.oil_pressure_psi']['value'], 100 / KPA_PER_PSI)

    def test_no_reading_at_all_gets_the_ecus_even_when_stale(self):
        values = {'ecu.oil_temp_c': sample(95.0, 'stale'), 'ecu.fuel_level_pct': sample(None, 'unavailable')}
        fill_from_ecu(values, FROM_ECU)
        self.assertEqual(values['engine.oil_temp_c']['quality'], 'stale')
        self.assertIsNone(values['vehicle.fuel_pct']['value'])

    def test_the_megasquirt_profile_has_none_of_these_so_the_car_is_unchanged(self):
        from hardware.frogdash import ecu
        keys = set(ecu.load('megasquirt').keys())
        self.assertTrue({lam for _, lam in AFR_FROM_LAMBDA}.isdisjoint(keys))
        self.assertTrue({src for _, src, _ in FROM_ECU}.isdisjoint(keys))


if __name__ == '__main__':
    unittest.main()
