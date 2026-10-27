import unittest

from breeders_cup.workbook import display_last_race


class RaceDisplayTests(unittest.TestCase):
    def test_name_after_presented_by_is_kept_with_finish(self):
        for raw, expected in (
            ('Indian Summer S. Presented By Keeneland Select: 5 (2026-10-04)', 'Keeneland Select: 5'),
            ('Oak Leaf S. presented by Oak Tree Racing Association: 1', 'Oak Tree Racing Association: 1'),
            ('Woodford S. PRESENTED BY FanDuel: 12', 'FanDuel: 12'),
        ):
            self.assertEqual(display_last_race(raw), expected)

    def test_firth_of_clyde_advertising_is_removed_without_changing_finish(self):
        for finish in (1, 3):
            raw = ("Ladbrokes New Customers Get 50/1 Old Firm Offer "
                   f"Firth Of Clyde Challenge Cup: {finish} (2026-09-19)")
            self.assertEqual(display_last_race(raw), f'Firth Of Clyde: {finish}')

    def test_other_race_names_are_preserved(self):
        self.assertEqual(display_last_race('Ladbrokes Ayr Gold Cup: 2 (2026-09-19)'),
                         'Ladbrokes Ayr Gold Cup: 2')
        self.assertEqual(display_last_race('Clement L. Hirsch S.: 1 (2026-08-01)'),
                         'Clement L Hirsch S: 1')
        self.assertIsNone(display_last_race(None))
