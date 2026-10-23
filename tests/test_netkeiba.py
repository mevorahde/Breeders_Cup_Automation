from pathlib import Path
import unittest
from unittest.mock import patch
from breeders_cup.netkeiba import search_candidates, enrich_remaining, NetkeibaClient
from breeders_cup.pedigree import pedigree_table

FIXTURES = Path(__file__).parent / 'fixtures'


class NetkeibaTests(unittest.TestCase):
    def setUp(self):
        self.search = (FIXTURES/'netkeiba-search.html').read_text(encoding='utf8')
        self.pedigree = (FIXTURES/'netkeiba-forged.html').read_text(encoding='utf8')
        self.horse = {'name':'Forged Steel', 'date_of_birth':'2022-03-12',
                      'father':'Vekoma', 'dam':'Scorecard'}

    def test_search_rejects_homonyms(self):
        self.assertEqual(search_candidates(self.search, self.horse),
                         {'https://en.netkeiba.com/db/horse/ped/000a02d738/'})

    def test_search_requires_year_and_both_parents(self):
        for field, value in [('date_of_birth','2021-03-12'), ('father','Wrong sire'),('dam','Wrong dam')]:
            with self.subTest(field=field):
                self.assertEqual(search_candidates(self.search, {**self.horse,field:value}), set())

    def test_actual_table_extracts_all_six_ancestors(self):
        p = pedigree_table(self.pedigree)
        expected = {'SS':'Candy Ride','DS':'Tale of the Cat','SSS':'Ride the Rails',
                    'SDS':'Speightstown','DSS':'Storm Cat','DDS':"Unbridled's Song"}
        self.assertEqual({k:p['nodes'][k]['name'] for k in expected}, expected)

    def enrich(self, horse, pedigree=None):
        with patch('breeders_cup.netkeiba.NetkeibaClient') as client:
            client.return_value.get.side_effect = lambda url: self.search if 'search.html' in url else (pedigree or self.pedigree)
            return enrich_remaining({'horses':[horse]}, 'unused')

    def test_enrichment_preserves_existing_complete_field(self):
        horse = {**self.horse,'grandfathers':'Candy Ride (ARG); Tale Of The Cat'}
        data = self.enrich(horse)
        self.assertEqual(horse['grandfathers'],'Candy Ride (ARG); Tale Of The Cat')
        self.assertEqual(horse['great_grandfathers'],"Ride the Rails; Speightstown; Storm Cat; Unbridled's Song")
        self.assertTrue(data['collection_report']['pedigree_complete'])

    def test_conflicting_existing_generation_is_flagged(self):
        horse = {**self.horse,'grandfathers':'Different Horse; Another Horse'}
        data = self.enrich(horse)
        self.assertEqual(data['collection_report']['secondary_pedigree']['matched'],0)
        self.assertNotIn('great_grandfathers', horse)

    def test_placeholder_identity_is_not_guessed(self):
        with patch('breeders_cup.netkeiba.NetkeibaClient') as client:
            data = enrich_remaining({'horses':[{'name':'Unidentified','father':'--','dam':'--'}]}, 'unused')
            client.return_value.get.assert_not_called()
            self.assertFalse(data['collection_report']['pedigree_complete'])

    def test_conflicting_pedigree_page_is_rejected(self):
        data = self.enrich(dict(self.horse), self.pedigree.replace('Vekoma', 'Wrong Sire'))
        self.assertEqual(data['collection_report']['secondary_pedigree']['matched'],0)
        self.assertNotIn('grandfathers',data['horses'][0])

    def test_parent_lookup_rejects_multiple_same_name_identities(self):
        client = object.__new__(NetkeibaClient)
        with patch.object(client,'get',return_value=self.search):
            with self.assertRaisesRegex(ValueError,'unique sire identities'):
                client.parent_tree('Forged Steel','sire',2026)

    def test_parent_lookup_checks_sex_and_birth_chronology(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(self.search,'html.parser')
        one = str(soup.find('a',href='https://en.netkeiba.com/db/horse/000a02d738/'))
        client = object.__new__(NetkeibaClient)
        with patch.object(client,'get',side_effect=lambda u:one if 'search.html' in u else self.pedigree):
            tree, url = client.parent_tree('Forged Steel','sire',2026)
            self.assertEqual(tree['name'],'Forged Steel')
            with self.assertRaises(ValueError):
                client.parent_tree('Forged Steel','dam',2026)
            with self.assertRaises(ValueError):
                client.parent_tree('Forged Steel','sire',2023)

    def test_parent_trees_map_to_correct_child_generations(self):
        client = object.__new__(NetkeibaClient)
        sire = {'nodes':{p:{'name':n} for p,n in [('S','Paternal Grandfather'),('SS','Paternal Great A'),('DS','Paternal Great B')]}}
        dam = {'nodes':{p:{'name':n} for p,n in [('S','Maternal Grandfather'),('SS','Maternal Great A'),('DS','Maternal Great B')]}}
        with patch.object(client,'parent_tree',side_effect=[(sire,'sire-url'),(dam,'dam-url')]):
            branches, urls, ancestors = client.through_parents(self.horse)
        self.assertEqual(branches,{'SS':'Paternal Grandfather','DS':'Maternal Grandfather',
            'SSS':'Paternal Great A','SDS':'Paternal Great B','DSS':'Maternal Great A','DDS':'Maternal Great B'})

    def test_alternate_parent_requires_unique_sex_year_and_name(self):
        from unittest.mock import Mock
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(self.pedigree, 'html.parser')
        title = next(h for h in soup.find_all('h1') if h.get_text(strip=True))
        p = soup.new_tag('p')
        p.string = '2022年生まれ 栗毛の牡馬'
        title.insert_after(p)
        client = object.__new__(NetkeibaClient)
        client.primary_index = {'forgedsteel': {('https://racedb.com/p/1.html', 2022)}}
        client.primary = Mock()
        client.primary.get.return_value = str(soup)
        client.primary.english_name.side_effect = lambda n: n['name']
        tree, url = client.racedb_parent_tree('Forged Steel', 'sire', 2026)
        self.assertEqual(tree['nodes']['S']['name'], 'Vekoma')
        for role, year in [('dam',2026), ('sire',2023)]:
            with self.subTest(role=role, year=year), self.assertRaises(ValueError):
                client.racedb_parent_tree('Forged Steel',role,year)
        client.primary_index['forgedsteel'].add(('https://racedb.com/p/2.html',2022))
        with self.assertRaises(ValueError):
            client.racedb_parent_tree('Forged Steel','sire',2026)
