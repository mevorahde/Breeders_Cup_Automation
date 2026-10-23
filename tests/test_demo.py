import copy
import unittest
from breeders_cup.demo import prepare_demo,DEMO_ODDS


class DemoTests(unittest.TestCase):
    def test_repeatable_posts_odds_caps_and_original_preservation(self):
        data={'year':2026,'races':[{'id':'classic','name':'Classic','number':1,'date':'2026-10-31','source_url':'example'}],
              'horses':[{'id':str(i),'name':f'Horse {i:02}','source_url':'example'} for i in range(18)],
              'entries':[{'horse_id':str(i),'race_id':'classic'} for i in range(18)]}
        original=copy.deepcopy(data)
        demo=prepare_demo(data,2026)
        self.assertEqual(data,original)
        self.assertEqual(demo,prepare_demo(data,2026))
        self.assertEqual(len(demo['horses']),18)
        self.assertEqual(len(demo['entries']),13)
        self.assertEqual([e['post'] for e in demo['entries']],list(range(1,14)))
        self.assertTrue(all(e['odds'] in DEMO_ODDS and e['result'] is None for e in demo['entries']))
        self.assertNotEqual(demo['entries'],prepare_demo(data,2027)['entries'])
        self.assertIn('not official',demo['demo']['notice'])
