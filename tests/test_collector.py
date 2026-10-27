import json
from pathlib import Path
import unittest
from unittest.mock import patch
from breeders_cup.collector import parse_official, official_identity, official_odds, read_official, OFFICIAL, OFFICIAL_ENTRIES


class CollectorTests(unittest.TestCase):
    def test_cms_year_is_not_part_of_horse_name(self):
        raw={'horseName':'Facteur Cheval','pageTitle':'Facteur Cheval 2026',
             'sireName':'--','damName':'--','bio':
             '<p>Facteur Cheval is by Ribchester (IRE) out of the Shamardal mare Jawlaat (IRE).</p>'}
        identity=official_identity(raw,'https://www.breederscup.com/horse')
        self.assertEqual(identity['name'],'Facteur Cheval')
        self.assertEqual(identity['father'],'Ribchester (IRE)')
        self.assertEqual(identity['dam'],'Jawlaat (IRE)')
        self.assertEqual(identity['maternal_grandsire'],'Shamardal')
        # A narrative age without its historical reference date cannot set DOB.
        self.assertNotIn('date_of_birth',identity)

    def test_conflicting_biography_sentences_are_not_accepted(self):
        raw={'horseName':'Example','bio':
             'by Sire A (IRE) out of the Grandpa A mare Dam A (IRE). '
             'by Sire B (IRE) out of the Grandpa B mare Dam B (IRE).'}
        self.assertNotIn('father',official_identity(raw,'https://www.breederscup.com/horse'))

    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / 'fixtures/official.json').read_text())

    def parse(self):
        return parse_official('<script id="__NEXT_DATA__" type="application/json">' +
                              json.dumps(self.fixture) + '</script>', 2026, '2026-10-22')

    def test_real_source_fields_and_chronological_races(self):
        data = self.parse()
        horse = data['horses'][0]
        self.assertEqual(horse['name'], 'Forever Young (JPN)')
        self.assertEqual(horse['date_of_birth'], '2021-02-24')
        self.assertEqual(horse['father'], 'Real Steel (JPN)')
        self.assertIn('2026-09-18', horse['last_previous_race'])
        self.assertEqual(len(data['races']), 14)
        self.assertTrue(all(r['number'] is None for r in data['races']))

    def test_wrong_event_year_is_rejected(self):
        self.fixture['props']['pageProps']['blocks'][0]['horseCards']['races'][0]['raceDetails']['date'] = '2025-11-01T22:00:00Z'
        with self.assertRaisesRegex(ValueError, 'not requested'):
            self.parse()

    def test_preentry_positions_are_not_confirmed_draw_positions(self):
        cards = self.fixture['props']['pageProps']['blocks'][0]['horseCards']
        cards['horseType'] = 'pre-entries'
        cards['races'][0]['horses'][0]['races'][0]['postPosition'] = '7'
        self.assertTrue(all('post' not in e for e in self.parse()['entries']))

    def test_final_entries_import_actual_posts_and_riders(self):
        cards=self.fixture['props']['pageProps']['blocks'][0]['horseCards']
        cards['horseType']='entries'
        raw=cards['races'][0]['horses'][0]
        raw['races'][0]['postPosition']='7'
        raw['jockeyName']='Declared Rider'
        raw['morningLineOdds']=[{'number':5},{'number':2}]
        data=self.parse()
        entry=next(e for e in data['entries'] if e['horse_id']==raw['uid'])
        self.assertEqual(entry['post'],'7')
        self.assertEqual(entry['jockey'],'Declared Rider')
        self.assertEqual(entry['odds'],'5-2')
        self.assertEqual(data['source_stage'],'entries')

    def test_structured_odds_require_declarations_and_valid_fraction(self):
        pair=[{'number':30},{'number':1}]
        self.assertEqual(official_odds(pair,declared=True),'30-1')
        self.assertIsNone(official_odds(pair))
        self.assertEqual(official_odds(' 5/2 '),'5-2')
        for invalid in ([],[{'number':5}], [{'number':5},{'number':0}],
                        [{'number':True},{'number':1}], [{'other':5},{'number':2}], 'TBA'):
            self.assertIsNone(official_odds(invalid,declared=True))

    def test_scratch_odds_win_over_published_morning_line(self):
        cards=self.fixture['props']['pageProps']['blocks'][0]['horseCards']
        cards['horseType']='entries'
        raw=cards['races'][0]['horses'][0]
        raw['morningLineOdds']=[{'number':5},{'number':2}]
        raw['races'][0]['scratched']=True
        entry=next(e for e in self.parse()['entries'] if e['horse_id']==raw['uid'])
        self.assertEqual(entry['odds'],'SCR')

    def test_final_url_serving_preentries_is_not_treated_as_draw(self):
        html='<script id="__NEXT_DATA__">'+json.dumps(self.fixture)+'</script>'
        with patch('breeders_cup.collector.fetch',return_value=html) as fetch:
            data,_=read_official(2026,'2026-10-26')
        self.assertEqual(data['source_stage'],'pre-entries')
        self.assertEqual(data['official_source'],OFFICIAL)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(data['source_checks'][0]['url'],OFFICIAL_ENTRIES)

    def test_final_feed_is_preferred_and_wrong_year_falls_back(self):
        cards=self.fixture['props']['pageProps']['blocks'][0]['horseCards']
        cards['horseType']='entries'
        html='<script id="__NEXT_DATA__">'+json.dumps(self.fixture)+'</script>'
        with patch('breeders_cup.collector.fetch',return_value=html) as fetch:
            data,_=read_official(2026,'2026-10-26')
        self.assertEqual(data['official_source'],OFFICIAL_ENTRIES)
        self.assertEqual(fetch.call_count,1)
        cards['races'][0]['raceDetails']['date']='2025-11-01T22:00:00Z'
        wrong='<script id="__NEXT_DATA__">'+json.dumps(self.fixture)+'</script>'
        with patch('breeders_cup.collector.fetch',side_effect=[wrong,html]):
            data,_=read_official(2026,'2026-10-26')
        self.assertEqual(data['official_source'],OFFICIAL)
        self.assertIn('error',data['source_checks'][0])

    def test_stale_horse_record_is_reported_and_excluded(self):
        self.fixture['props']['pageProps']['blocks'][0]['horseCards']['races'][0]['horses'][0]['year'] = 2025
        data = self.parse()
        self.assertEqual(len(data['excluded_wrong_year_records']), 1)
        self.assertFalse(any(h['name'] == 'Forever Young (JPN)' for h in data['horses']))

    def test_withdrawals_and_missing_source_are_not_silent(self):
        self.fixture['props']['pageProps']['blocks'].append({'richTextEditor': {
            'html': '<p>Forever Young has withdrawn from the Classic</p>'}})
        data=self.parse()
        horse=next(h for h in data['horses'] if h['name']=='Forever Young (JPN)')
        withdrawn=next(e for e in data['entries'] if e['horse_id']==horse['id'])
        self.assertTrue(withdrawn['scratched'])
        self.assertEqual(withdrawn['odds'],'SCR')
        with self.assertRaisesRegex(ValueError, 'layout changed'):
            parse_official('<html>Request unsuccessful</html>', 2026, '2026-10-22')
