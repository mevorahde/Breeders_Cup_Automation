from pathlib import Path
import unittest
from unittest.mock import patch
from breeders_cup.pedigreequery import parse_pedigree, candidate_urls, verified, enrich_query

FIXTURES = Path(__file__).parent/'fixtures'


class PedigreeQueryTests(unittest.TestCase):
    def setUp(self):
        self.html = (FIXTURES/'pq-evanescence.html').read_text(encoding='utf8',errors='replace')
        self.search = (FIXTURES/'pq-search.html').read_text(encoding='utf8',errors='replace')
        self.horse = {'name':'Evanescence','date_of_birth':'2022-03-31',
                      'father':'Munnings','dam':'Lovely Carina'}

    def test_all_six_ancestors_from_actual_page(self):
        tree = parse_pedigree(self.html)
        self.assertEqual(len(tree['nodes']),62)
        expected = {'SS':'SPEIGHTSTOWN','DS':'PIONEEROF THE NILE','SSS':'GONE WEST',
                    'SDS':'HOLY BULL','DSS':'EMPIRE MAKER','DDS':'KNOW HEIGHTS'}
        self.assertEqual({p:tree['nodes'][p]['name'] for p in expected},expected)
        self.assertTrue(verified(tree,self.horse))

    def test_search_disambiguates_name_and_year_before_pedigree_verification(self):
        urls = candidate_urls(self.search,self.horse)
        self.assertEqual(len(urls),1)
        self.assertIn('h=EVANESCENCE8',next(iter(urls)))
        self.assertFalse(candidate_urls(self.search,{**self.horse,'date_of_birth':'2024-01-01'}))

    def test_identity_requires_both_parents_and_year(self):
        tree = parse_pedigree(self.html)
        for field,value in [('father','Wrong'),('dam','Wrong'),('date_of_birth','2023-03-31'),('name','Wrong')]:
            with self.subTest(field=field):
                self.assertFalse(verified(tree,{**self.horse,field:value}))

    def test_layout_drift_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_pedigree(self.html.replace('rowspan=16','rowspan=15'))

    def test_rig_code_does_not_hide_valid_pedigree(self):
        tree=parse_pedigree(self.html.replace('F, 2022','R, 2022'))
        self.assertEqual(tree['sex'],'R')
        self.assertTrue(verified(tree,self.horse))

    def test_missing_official_birth_requires_independent_identity(self):
        horse={**self.horse,'date_of_birth':None,'identity_source':'https://www.breederscup.com/horse'}
        tree=parse_pedigree(self.html)
        tree['date_of_birth']='2022-03-31'
        with patch('breeders_cup.pedigreequery.PedigreeQueryClient') as client:
            client.return_value.lookup.return_value=tree,'pedigree-url'
            client.return_value.verify_missing_birth.side_effect=ValueError('Independent mismatch')
            data=enrich_query({'year':2026,'horses':[horse]},'unused')
            self.assertFalse(data['collection_report']['pedigree_complete'])
            self.assertIsNone(horse['date_of_birth'])
            self.assertNotIn('grandfathers',horse)

    def test_enrich_and_conflict_do_not_overwrite_verified_data(self):
        tree = parse_pedigree(self.html)
        with patch('breeders_cup.pedigreequery.PedigreeQueryClient') as client:
            client.return_value.lookup.return_value = tree,'https://www.pedigreequery.com/evanescence8'
            horse = dict(self.horse)
            data = enrich_query({'horses':[horse]},'unused')
            self.assertTrue(data['collection_report']['pedigree_complete'])
            self.assertEqual(horse['great_grandfathers'],'GONE WEST; HOLY BULL; EMPIRE MAKER; KNOW HEIGHTS')
            horse = {**self.horse,'grandfathers':'Wrong; Wrong'}
            data = enrich_query({'horses':[horse]},'unused')
            self.assertFalse(data['collection_report']['pedigree_complete'])
            self.assertNotIn('great_grandfathers',horse)

    def test_placeholder_is_not_looked_up(self):
        with patch('breeders_cup.pedigreequery.PedigreeQueryClient') as client:
            data = enrich_query({'horses':[{'name':'Placeholder','father':'--','dam':'--'}]},'unused')
            client.return_value.lookup.assert_not_called()
            self.assertFalse(data['collection_report']['pedigree_complete'])
