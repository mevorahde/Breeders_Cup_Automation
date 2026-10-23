"""Public Pedigree Query fallback; accept only identity-verified pedigrees."""
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from bs4 import BeautifulSoup
from .sources import fetch
from .pedigree import normalized
from .netkeiba import NetkeibaClient, search_candidates
from datetime import datetime

HOST = 'https://www.pedigreequery.com'
BRANCHES = ('SS', 'DS', 'SSS', 'SDS', 'DSS', 'DDS')


def parse_pedigree(html):
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.select('table.pedigreetable')
    if len(tables) != 1:
        raise ValueError('Expected one pedigree table')
    table = tables[0]
    header = table.find_previous('font', class_='normal')
    root = header.find('b') if header else None
    identity = re.search(r'\b([HMCFGR]),\s*((?:18|19|20)\d{2})\b', header.get_text(' ', strip=True) if header else '')
    if root is None or identity is None:
        raise ValueError('Pedigree lacks root name, sex or foaling year')
    rows = table.find_all('tr', recursive=False)
    if len(rows) != 32:
        raise ValueError('Expected 32 pedigree leaf rows')
    nodes = {}
    occupied = set()
    for rownum, row in enumerate(rows):
        for cell in row.find_all('td', recursive=False):
            if not cell.has_attr('data-g'):
                continue  # decorative inbreeding/date cells have no generation
            depth = int(cell['data-g'])
            if depth not in range(1, 6):
                raise ValueError('Unexpected pedigree generation')
            span = 2 ** (5-depth)
            if int(cell.get('rowspan', 1)) != span or rownum % span:
                raise ValueError('Pedigree generation alignment changed')
            for i in range(rownum, rownum+span):
                if (i,depth) in occupied:
                    raise ValueError('Overlapping pedigree cells')
                occupied.add((i,depth))
            path = ''.join('D' if b == '1' else 'S' for b in f'{rownum//span:0{depth}b}')
            a = cell.select_one('a.horseName')
            name = a.get_text(' ', strip=True) if a else None
            nodes[path] = {'name':name, 'sex':'M' if 'm' in cell.get('class',[]) else 'F',
                           'url':urljoin(HOST,a['href']) if a else None}
    date = None
    info = soup.select_one('#subjectinfo')
    birth = re.search(r'\bFoaled\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\b',info.get_text(' ',strip=True) if info else '',re.I)
    if birth:
        date = datetime.strptime(birth.group(1),'%d %b %Y').date().isoformat()
        if int(date[:4]) != int(identity.group(2)):
            raise ValueError('Foaling date conflicts with pedigree birth year')
    return {'name':root.get_text(' ',strip=True), 'year':int(identity.group(2)),
            'date_of_birth':date, 'sex':identity.group(1), 'nodes':nodes}


def candidate_urls(html, horse):
    soup = BeautifulSoup(html, 'html.parser')
    matches = set()
    for row in soup.select('table.tablesorter tbody tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) != 7:
            raise ValueError('Pedigree search columns changed')
        a = cells[0].find('a', href=True)
        if (a and normalized(a.get_text()) == normalized(horse['name']) and
                (not horse.get('date_of_birth') or cells[1].get_text(strip=True) == horse['date_of_birth'][:4])):
            matches.add(urljoin(HOST+'/',a['href']))
    return matches


def verified(tree, horse):
    return (normalized(tree['name']) == normalized(horse['name']) and
            (not horse.get('date_of_birth') or tree['year'] == int(horse['date_of_birth'][:4])) and
            all(normalized(tree['nodes'].get(p,{}).get('name')) == normalized(horse[field])
                for p,field in [('S','father'),('D','dam')]))


class PedigreeQueryClient:
    def __init__(self, cache):
        self.cache = Path(cache)/'pedigreequery'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.last_request = 0
        self.independent = NetkeibaClient(cache)

    def get(self, url):
        if urlparse(url).netloc != urlparse(HOST).netloc:
            raise ValueError('Unexpected pedigree query host')
        path = self.cache/(hashlib.sha256(url.encode()).hexdigest()+'.html')
        if path.exists():
            return path.read_text(encoding='utf8')
        time.sleep(max(0,1.1-(time.monotonic()-self.last_request)))
        try:
            page = fetch(url)
        finally:
            self.last_request = time.monotonic()
        path.write_text(page,encoding='utf8')
        return page

    def lookup(self, horse):
        name = re.sub(r'\s*\([A-Z]{2,3}\)\s*$','',horse['name'])
        url = HOST+'/index.php?'+urlencode({'query_type':'check','search_bar':'horse','h':name,'g':'5'})
        html = self.get(url)
        if BeautifulSoup(html,'html.parser').select_one('table.pedigreetable'):
            pages = [(url,html)]
        else:
            pages = [(u,self.get(u)) for u in sorted(candidate_urls(html,horse))]
        matches = []
        for source,page in pages:
            tree = parse_pedigree(page)
            if verified(tree,horse):
                matches.append((tree,source))
        if len(matches) != 1:
            raise ValueError(f'{len(matches)} pedigrees match name, foaling year and both official parents')
        return matches[0]

    def verify_missing_birth(self, horse, tree):
        if not tree.get('date_of_birth'):
            raise ValueError('Missing official birth date and no full foaling date in fallback')
        identity = {**horse,'date_of_birth':tree['date_of_birth']}
        url = 'https://en.netkeiba.com/db/search.html?'+urlencode({'pid':'search','type':'horse','word':horse['name']})
        if len(search_candidates(self.independent.get(url),identity)) != 1:
            raise ValueError('Independent database cannot verify missing official birth year and both parents')
        return url


def enrich_query(data, cache):
    client = PedigreeQueryClient(cache)
    report = {'source':HOST,'matched':0,'unresolved':[]}
    pending = [h for h in data['horses'] if not h.get('grandfathers') or not h.get('great_grandfathers')]
    for i,horse in enumerate(pending):
        try:
            if any(not horse.get(f) or horse[f]=='--' for f in ('father','dam')):
                raise ValueError('Official record lacks identity information')
            tree,url = client.lookup(horse)
            birth_source = None
            if not horse.get('date_of_birth'):
                if not horse.get('identity_source') or tree['year']>int(data['year'])-2:
                    raise ValueError('Missing official birth date requires an independently verified identity')
                birth_source = client.verify_missing_birth(horse,tree)
            nodes = tree['nodes']
            if any(not nodes.get(p,{}).get('name') or nodes[p]['sex']!='M' or
                   normalized(nodes[p]['name']) in ('unknown','unnamed') for p in BRANCHES):
                raise ValueError('Required male ancestor names are incomplete')
            if horse.get('maternal_grandsire') and normalized(horse['maternal_grandsire'])!=normalized(nodes['DS']['name']):
                raise ValueError('Pedigree conflicts with official biography damsire')
            fields = [('grandfathers',('SS','DS')),('great_grandfathers',('SSS','SDS','DSS','DDS'))]
            for field,paths in fields:
                names = [nodes[p]['name'] for p in paths]
                if horse.get(field) and [normalized(n) for n in horse[field].split(';')] != [normalized(n) for n in names]:
                    raise ValueError(f'{field} conflicts with existing verified data')
            for field,paths in fields:
                if not horse.get(field):
                    horse[field] = '; '.join(nodes[p]['name'] for p in paths)
                    horse.setdefault('field_sources',{})[field] = url
            horse.setdefault('pedigree_branches',{}).update({p:nodes[p]['name'] for p in BRANCHES})
            horse['pedigree_ancestors'] = sorted(set(horse.get('pedigree_ancestors',[]) +
                [n['name'] for n in nodes.values() if n['name']]))
            horse['pedigree_identity_method'] = 'Pedigree Query: name, foaling year, sire and dam matched'
            if birth_source:
                horse['date_of_birth'] = tree['date_of_birth']
                horse.setdefault('field_sources',{})['date_of_birth'] = [url,birth_source]
                horse['pedigree_identity_method'] = 'Official biography parents and damsire; Pedigree Query birth date; independent netkeiba name/year/parents match'
            report['matched'] += 1
        except Exception as exc:
            report['unresolved'].append({'name':horse['name'],'reason':str(exc)})
        print(f'Additional pedigrees: {i+1}/{len(pending)}; {report["matched"]} enriched',flush=True)
    summary = data.setdefault('collection_report',{})
    summary['pedigreequery'] = report
    summary['missing_field_counts'] = {f:sum(not h.get(f) for h in data['horses']) for f in
        ('jockey','trainer','color','date_of_birth','father','last_previous_race','grandfathers','great_grandfathers')}
    summary['remaining_pedigree_horses'] = [{'name':h['name'],'missing':[f for f in ('grandfathers','great_grandfathers') if not h.get(f)]}
        for h in data['horses'] if not h.get('grandfathers') or not h.get('great_grandfathers')]
    summary['pedigree_complete'] = not summary['remaining_pedigree_horses']
    return data
