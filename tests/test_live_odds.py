from copy import deepcopy
from datetime import datetime,timezone,timedelta
import unittest
from unittest.mock import patch
from breeders_cup.live_odds import refresh_odds,LIVE_URL


class LiveOddsTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,30,18,0,tzinfo=timezone.utc)
        self.data={'year':2026,'retrieved_at':self.now.isoformat(),'official_source':'official',
            'races':[{'id':'r','name':'Juvenile Turf Sprint','number':6,'track_name':'Keeneland',
                      'date':'2026-10-30','scheduled_at':'2026-10-30T18:55:00+00:00'}],
            'horses':[{'id':'a','name':'Alpha (IRE)'},{'id':'b','name':'Beta'}],
            'entries':[{'horse_id':'a','race_id':'r','post':'1','odds':'5-2'},
                       {'horse_id':'b','race_id':'r','post':'2','odds':'3-1'}]}
        self.feed={'isActive':True,'_stale':False,'_cached_at':self.now.timestamp()*1000,
            'details':{'raceCount':6,'postTimes':['2026-10-30T18:55:00']*6},
            'odds':{'live':{'source':'UTote','odds_type':'odds','error':False,
                'races':{'6':[{'horse_name':'Alpha','program_number':1,'race_number':6,'odds':'7/2'},
                              {'horse_name':'Beta','program_number':2,'race_number':6,'odds':'EVEN'}]}},
                'drfProjected':{'races':{'6':[{'horse_name':'Alpha','odds':'99-1'}]}}}}

    def run_feed(self,**kwargs):
        return refresh_odds(self.data,now=self.now,payload=self.feed,**kwargs)

    def test_verified_live_prices_and_timestamp_preserve_morning_line(self):
        self.run_feed()
        a,b=self.data['entries']
        self.assertEqual((a['odds'],b['odds']),('7-2','1-1'))
        self.assertEqual(a['morning_line_odds'],'5-2')
        self.assertEqual((a['odds_type'],a['odds_source_url']),('live',LIVE_URL))
        self.assertEqual(a['odds_as_of'],self.now.isoformat())

    def test_wrong_day_rejected_even_when_cache_is_fresh(self):
        self.feed['details']['postTimes']=['2026-10-24T18:55:00']*6
        self.run_feed()
        self.assertEqual(self.data['entries'][0]['odds'],'5-2')
        self.assertEqual(self.data['collection_report']['odds_refresh']['live_entries'],0)

    def test_stale_inactive_missing_timestamp_and_source_errors_fall_back(self):
        original=deepcopy(self.data)
        for key,value in [('_stale',True),('isActive',False),('_cached_at',0),('_cached_at',None)]:
            with self.subTest(key=key,value=value):
                self.data=deepcopy(original);feed=deepcopy(self.feed);feed[key]=value
                refresh_odds(self.data,now=self.now,payload=feed)
                self.assertEqual(self.data['entries'][0]['odds_type'],'morning-line')
        self.data=deepcopy(original)
        with patch('breeders_cup.live_odds.fetch',side_effect=ValueError('offline')):
            refresh_odds(self.data,now=self.now)
        self.assertEqual(self.data['entries'][0]['odds'],'5-2')

    def test_identity_program_and_race_number_conflicts_reject_entire_race(self):
        original=deepcopy(self.data)
        for key,value in [('horse_name','Another Horse'),('program_number',9),('race_number',7)]:
            with self.subTest(key=key):
                self.data=deepcopy(original);feed=deepcopy(self.feed)
                feed['odds']['live']['races']['6'][1][key]=value
                refresh_odds(self.data,now=self.now,payload=feed)
                self.assertEqual([e['odds_type'] for e in self.data['entries']],['morning-line']*2)

    def test_scratch_wins_and_absent_tote_runner_does_not_imply_scratch(self):
        self.data['entries'][0].update(scratched=True,odds='SCR')
        self.run_feed()
        self.assertEqual(self.data['entries'][0]['odds'],'SCR')
        self.assertEqual(self.data['entries'][1]['odds'],'1-1')
        self.data['entries'][1]['odds']='3-1'
        self.feed['odds']['live']['races']['6']=[]
        self.run_feed()
        self.assertEqual(self.data['entries'][1]['odds'],'3-1')
        self.assertFalse(self.data['entries'][1].get('scratched',False))

    def test_past_post_retains_previous_live_snapshot_with_original_time(self):
        self.run_feed();previous=deepcopy(self.data)
        now=self.now+timedelta(hours=2)
        fresh=deepcopy(self.data)
        for e in fresh['entries']:
            e['odds']=e['morning_line_odds']
        refresh_odds(fresh,previous,now=now,payload=self.feed)
        self.assertEqual(fresh['entries'][0]['odds'],'7-2')
        self.assertEqual(fresh['entries'][0]['odds_type'],'live-snapshot')
        self.assertEqual(fresh['entries'][0]['odds_as_of'],self.now.isoformat())

    def test_projected_values_wrong_track_and_missing_dates_never_used(self):
        original=deepcopy(self.data)
        self.feed['odds']['live']['races']['6'][0]['odds']='unavailable'
        self.run_feed()
        self.assertEqual(self.data['entries'][0]['odds'],'5-2')
        self.data=deepcopy(original);self.data['races'][0]['track_name']='Belmont Park'
        self.run_feed()
        self.assertEqual(self.data['entries'][0]['odds'],'5-2')
        self.data=deepcopy(original);self.feed['details']['postTimes']=[]
        self.run_feed()
        self.assertEqual(self.data['entries'][0]['odds'],'5-2')
