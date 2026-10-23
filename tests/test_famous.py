import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from breeders_cup.famous import annotate_famous


class FamousGraphTests(unittest.TestCase):
    def page(self,root,bridge=False,target=False):
        fixture=Path(__file__).parent/'fixtures/pq-evanescence.html'
        soup=BeautifulSoup(fixture.read_text(encoding='utf8',errors='replace'),'html.parser')
        table=soup.select_one('table.pedigreetable')
        table['summary']=root
        table.find_previous('font',class_='normal').find('b').string=root
        for i,cell in enumerate(table.select('td[data-g]')):
            a=cell.select_one('a.horseName')
            if a:
                a.string='Ordinary Ancestor'
                a['href']=f'/{root}-ancestor-{i}'
        if bridge:
            leaf=table.select_one('td[data-g="5"] a.horseName')
            leaf.string='Bridge'
            leaf['href']='/bridge'
        if target:
            sire=table.select_one('td[data-g="1"] a.horseName')
            sire.string='MR PROSPECTOR'
            sire['href']='/mr+prospector'
        return str(soup)

    def test_deeper_paths_use_source_ids_and_have_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            folder=Path(tmp)/'pedigreequery';folder.mkdir()
            horses=[]
            for root,html in [('runner',self.page('runner',bridge=True)),('bridge',self.page('bridge',target=True))]:
                url='https://www.pedigreequery.com/'+root
                (folder/(hashlib.sha256(url.encode()).hexdigest()+'.html')).write_text(html,encoding='utf8')
                horses.append({'id':root,'name':root,'field_sources':{'grandfathers':url}})
            with patch('breeders_cup.famous.FAMOUS_HORSES',['Mr. Prospector']):
                data=annotate_famous({'horses':copy.deepcopy(horses)},tmp)
                proof=data['horses'][0]['famous_ancestor_evidence']['Mr. Prospector']
                self.assertEqual(proof['generations'],6)
                self.assertEqual(len(proof['sources']),2)
                self.assertEqual(data['horses'][0]['other_ancestors'],'Mr. Prospector')
                # Same displayed name with a different source ID cannot join.
                runner=folder/(hashlib.sha256(horses[0]['field_sources']['grandfathers'].encode()).hexdigest()+'.html')
                runner.write_text(self.page('runner',bridge=True).replace('href="/bridge"','href="/unrelated-bridge"'),encoding='utf8')
                data=annotate_famous({'horses':copy.deepcopy(horses)},tmp)
                self.assertEqual(data['horses'][0]['other_ancestors'],'')
