from datetime import date
from pathlib import Path
import unittest
from breeders_cup.jockeys import announcement,clean_rider


class JockeyTests(unittest.TestCase):
    def setUp(self):
        self.html=(Path(__file__).parent/'fixtures/jockey-booking.html').read_text(encoding='utf8')
        self.horses=[{'id':'bay','name':'Bay City Roller (IRE)'}]

    def test_explicit_current_year_booking(self):
        booking=announcement(self.html,self.horses,2026,date(2026,10,22))
        self.assertEqual(booking[:2],('bay','Oisin Murphy'))

    def test_historical_future_and_wrong_horse_not_confirmations(self):
        self.assertIsNone(announcement(self.html,self.horses,2025,date(2025,10,22)))
        self.assertIsNone(announcement(self.html,self.horses,2026,date(2026,10,20)))
        self.assertIsNone(announcement(self.html,[{'id':'wrong','name':'Different Horse'}],2026,date(2026,10,22)))
        self.assertIsNone(announcement(self.html.replace('confirmed will ride','previously rode'),self.horses,2026,date(2026,10,22)))

    def test_placeholders_are_not_rider_names(self):
        for value in [None,'-- --','TBA','N/A','']:
            self.assertIsNone(clean_rider(value))
        self.assertEqual(clean_rider('  Oisin   Murphy '),'Oisin Murphy')
