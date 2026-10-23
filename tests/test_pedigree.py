from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from breeders_cup.pedigree import pedigree_table, enrich, normalized

FIXTURE = Path(__file__).parent / 'fixtures/racedb-adonius.html'


class PedigreeTests(unittest.TestCase):
    def test_generation_paths_follow_both_sides(self):
        p = pedigree_table(FIXTURE.read_text(encoding='utf8'))
        self.assertEqual((p['name'], p['year']), ('Adonius', 2024))
        expected = {'SS': 'Showcasing', 'DS': 'Exceed and Excel',
                    'SSS': 'Oasis Dream', 'SDS': 'Iceman', 'DDS': 'Street Cry'}
        self.assertEqual({k:p['nodes'][k]['name'] for k in expected}, expected)
        self.assertEqual(len(p['nodes']), 62)

    def test_name_normalization_preserves_identity(self):
        self.assertEqual(normalized("Soldier's Call (GB)"), normalized('Soldiers Call'))
        self.assertNotEqual(normalized('Adonius'), normalized('Adonius Junior'))

    def test_bad_pedigree_structure_is_rejected(self):
        with self.assertRaises(ValueError):
            pedigree_table(FIXTURE.read_text(encoding='utf8').replace('rowspan="16"','rowspan="15"').replace('rowspan=16','rowspan=15'))

    def test_wrong_sire_does_not_enrich(self):
        tree = pedigree_table(FIXTURE.read_text(encoding='utf8'))
        data = {'horses': [{'name': 'Adonius (IRE)', 'date_of_birth': '2024-04-11',
                            'father': 'Wrong sire'}]}
        with patch('breeders_cup.pedigree.PedigreeClient') as client:
            client.return_value.index.return_value = {'adonius': {('https://racedb.com/a/069430.html', 2024)}}
            client.return_value.page.return_value = tree
            client.return_value.english_name.side_effect = lambda n:n['name']
            result = enrich(data, 'unused')
        self.assertNotIn('grandfathers', result['horses'][0])
        self.assertEqual(result['collection_report']['pedigree']['matched'], 0)

    def test_wrong_dam_and_ambiguous_identity_are_rejected(self):
        tree = pedigree_table(FIXTURE.read_text(encoding='utf8'))
        for dam, urls in [('Wrong dam', {('https://racedb.com/a/069430.html', 2024)}),
                          ('Dubai Paradise', {('https://racedb.com/a/1.html', 2024),
                                              ('https://racedb.com/a/2.html', 2024)})]:
            with self.subTest(dam=dam):
                data = {'horses': [{'name':'Adonius (IRE)', 'date_of_birth':'2024-04-11',
                                    'father':"Soldier's Call (GB)", 'dam':dam}]}
                with patch('breeders_cup.pedigree.PedigreeClient') as client:
                    client.return_value.index.return_value = {'adonius':urls}
                    client.return_value.page.return_value = tree
                    client.return_value.english_name.side_effect = lambda n:n['name']
                    result = enrich(data, 'unused')
                self.assertEqual(result['collection_report']['pedigree']['matched'], 0)
                self.assertNotIn('grandfathers', result['horses'][0])
