"""Secondary public five-generation pedigree adapter, with identity checks."""
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from bs4 import BeautifulSoup
from .sources import fetch
from .pedigree import normalized, pedigree_table, PedigreeClient

HOST = 'https://en.netkeiba.com'


def search_candidates(html, horse):
    soup = BeautifulSoup(html, 'html.parser')
    candidates = set()
    for a in soup.find_all('a', href=True):
        match = re.fullmatch(r'https://en\.netkeiba\.com/db/horse/([a-zA-Z0-9]+)/', a['href'])
        title = a.find('h2')
        if not match or title is None or normalized(title.get_text(' ', strip=True)) != normalized(horse['name']):
            continue
        lines = [p.get_text(' ', strip=True) for p in a.find_all('p')]
        year = next((re.search(r'\b(?:19|20)\d{2}\b', s) for s in lines
                     if re.search(r'\b(?:19|20)\d{2}\b', s)), None)
        sire = next((s.split(':',1)[1].strip() for s in lines if s.startswith('Sire:')), None)
        dam = next((s.split(':',1)[1].strip() for s in lines if s.startswith('Dam:')), None)
        if (year and int(year.group()) == int(horse['date_of_birth'][:4]) and
                normalized(sire) == normalized(horse['father']) and
                normalized(dam) == normalized(horse['dam'])):
            candidates.add(HOST + '/db/horse/ped/' + match.group(1) + '/')
    return candidates


class NetkeibaClient:
    def __init__(self, cache):
        self.primary = PedigreeClient(cache)
        self.primary_index = None
        self.cache = Path(cache) / 'netkeiba'
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, url):
        if urlparse(url).netloc != 'en.netkeiba.com':
            raise ValueError('Unexpected secondary pedigree host')
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')
        if path.exists():
            return path.read_text(encoding='utf8')
        time.sleep(0.5)
        page = fetch(url)
        path.write_text(page, encoding='utf8')
        return page

    def parent_tree(self, name, role, child_year):
        try:
            return self.netkeiba_parent_tree(name, role, child_year)
        except ValueError as error:
            # A second independent index can resolve missing or ambiguous parents.
            if not hasattr(self, 'primary'):
                raise
            try:
                return self.racedb_parent_tree(name, role, child_year)
            except ValueError as fallback:
                raise ValueError(f'{error}; alternate parent index: {fallback}') from fallback

    def racedb_parent_tree(self, name, role, child_year):
        if self.primary_index is None:
            self.primary_index = self.primary.index()
        matches = []
        for url, year in sorted(self.primary_index.get(normalized(name), set())):
            if year is None or year > child_year - 2:
                continue
            html = self.primary.get(url)
            soup = BeautifulSoup(html, 'html.parser')
            heading = soup.find('h1')
            description = heading.find_next('p').get_text(' ', strip=True) if heading else ''
            birth = re.search(r'(\d{4})年生まれ', description)
            sex = '牡馬' if role == 'sire' else '牝馬'
            if not birth or int(birth.group(1)) != year or sex not in description:
                continue
            tree = pedigree_table(html)
            if normalized(tree['name']) != normalized(name):
                continue
            # Resolve Japanese labels through the source's linked English pages.
            for node in tree['nodes'].values():
                node['name'] = self.primary.english_name(node)
            matches.append((tree, url))
        if len(matches) != 1:
            raise ValueError(f'{len(matches)} sex/year-verified alternate {role} identities for {name}')
        return matches[0]

    def netkeiba_parent_tree(self, name, role, child_year):
        name = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', name)
        url = HOST + '/db/search.html?' + urlencode({'pid':'search','type':'horse','word':name})
        soup = BeautifulSoup(self.get(url), 'html.parser')
        matches = []
        for a in soup.find_all('a', href=True):
            match = re.fullmatch(r'https://en\.netkeiba\.com/db/horse/([a-zA-Z0-9]+)/', a['href'])
            title = a.find('h2')
            if not match or title is None or normalized(title.get_text(' ',strip=True)) != normalized(name):
                continue
            lines = [p.get_text(' ',strip=True) for p in a.find_all('p')]
            sex_year = next((re.match(r'^([HMCFG])\s+(\d{4})\b', s) for s in lines
                             if re.match(r'^([HMCFG])\s+(\d{4})\b', s)), None)
            if not sex_year or int(sex_year.group(2)) > child_year - 2:
                continue
            if sex_year.group(1) not in (('H','C') if role == 'sire' else ('M','F')):
                continue
            sire = next((s.split(':',1)[1].strip() for s in lines if s.startswith('Sire:')), None)
            dam = next((s.split(':',1)[1].strip() for s in lines if s.startswith('Dam:')), None)
            matches.append((HOST+'/db/horse/ped/'+match.group(1)+'/', sire, dam))
        if len(set(matches)) != 1:
            raise ValueError(f'{len(set(matches))} unique {role} identities for {name}')
        url, sire, dam = matches[0]
        tree = pedigree_table(self.get(url))
        if (normalized(tree['name']) != normalized(name) or
                normalized(tree['nodes']['S']['name']) != normalized(sire) or
                normalized(tree['nodes']['D']['name']) != normalized(dam)):
            raise ValueError('Parent pedigree conflicts with its search identity')
        return tree, url

    def through_parents(self, horse):
        year = int(horse['date_of_birth'][:4])
        sire, sire_url = self.parent_tree(horse['father'], 'sire', year)
        dam, dam_url = self.parent_tree(horse['dam'], 'dam', year)
        branches = {'SS':sire['nodes']['S']['name'], 'DS':dam['nodes']['S']['name'],
                    'SSS':sire['nodes']['SS']['name'], 'SDS':sire['nodes']['DS']['name'],
                    'DSS':dam['nodes']['SS']['name'], 'DDS':dam['nodes']['DS']['name']}
        ancestors = [n['name'] for t in (sire,dam) for p,n in t['nodes'].items() if len(p)<=4]
        return branches, [sire_url,dam_url], ancestors


def enrich_remaining(data, cache):
    client = NetkeibaClient(cache)
    report = {'source': HOST, 'additional_parent_source': 'https://racedb.com',
              'matched': 0, 'unresolved': []}
    pending = [h for h in data['horses'] if not h.get('grandfathers') or not h.get('great_grandfathers')]
    for i, horse in enumerate(pending):
        try:
            if not horse.get('date_of_birth') or any(not horse.get(f) or horse[f] == '--' for f in ('father','dam')):
                raise ValueError('Official record lacks birth date or parents; identity cannot be verified')
            name = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', horse['name'])
            query = HOST + '/db/search.html?' + urlencode({'pid':'search','type':'horse','word':name})
            candidates = search_candidates(client.get(query), horse)
            try:
                if len(candidates) != 1:
                    raise ValueError(f'{len(candidates)} identity-verified search results')
                url = next(iter(candidates))
                tree = pedigree_table(client.get(url))
                if (normalized(tree['name']) != normalized(horse['name']) or
                        normalized(tree['nodes']['S']['name']) != normalized(horse['father']) or
                        normalized(tree['nodes']['D']['name']) != normalized(horse['dam'])):
                    raise ValueError('Pedigree identity conflicts with search result or official parents')
                branches = {p:tree['nodes'][p]['name'] for p in ('SS','DS','SSS','SDS','DSS','DDS')}
                ancestors = [n['name'] for n in tree['nodes'].values()]
                method = 'Direct pedigree: name, foaling year, sire and dam matched'
            except ValueError as direct_error:
                try:
                    branches, url, ancestors = client.through_parents(horse)
                    method = 'Official parents linked to unique sex/age-filtered pedigree identities'
                except Exception as parent_error:
                    raise ValueError(f'{direct_error}; parent lookup: {parent_error}') from parent_error
            changed = False
            for field, paths in [('grandfathers', ('SS','DS')), ('great_grandfathers', ('SSS','SDS','DSS','DDS'))]:
                if horse.get(field) and all(branches[p] for p in paths):
                    existing = [normalized(n.strip()) for n in horse[field].split(';')]
                    if existing != [normalized(branches[p]) for p in paths]:
                        raise ValueError(f'Existing {field} conflicts with fallback pedigree')
            for field, paths in [('grandfathers', ('SS','DS')), ('great_grandfathers', ('SSS','SDS','DSS','DDS'))]:
                if horse.get(field):
                    continue
                names = [branches[p] for p in paths]
                if all(n and n.isascii() and n not in ('-', '--', 'Unknown') for n in names):
                    horse[field] = '; '.join(names)
                    horse.setdefault('field_sources', {})[field] = url
                    changed = True
            if not changed:
                raise ValueError('Required pedigree generations incomplete in source')
            horse.setdefault('pedigree_branches', {}).update(branches)
            horse['pedigree_identity_method'] = method
            horse['pedigree_ancestors'] = sorted(set(horse.get('pedigree_ancestors', []) +
                    [n for n in ancestors if n and n.isascii()]))
            report['matched'] += 1
            if not horse.get('grandfathers') or not horse.get('great_grandfathers'):
                raise ValueError('Some pedigree fields remain incomplete')
        except Exception as exc:
            report['unresolved'].append({'name':horse['name'],'reason':str(exc)})
        if (i+1) % 10 == 0:
            print(f'Secondary pedigrees: {i+1}/{len(pending)}; {report["matched"]} enriched', flush=True)
    summary = data.setdefault('collection_report', {})
    summary['secondary_pedigree'] = report
    summary['missing_field_counts'] = {f:sum(not h.get(f) for h in data['horses']) for f in
            ('jockey','trainer','color','date_of_birth','father','last_previous_race','grandfathers','great_grandfathers')}
    summary['pedigree_complete'] = all(h.get('grandfathers') and h.get('great_grandfathers') for h in data['horses'])
    summary['remaining_pedigree_horses'] = [
        {'name':h['name'], 'missing':[f for f in ('grandfathers','great_grandfathers') if not h.get(f)]}
        for h in data['horses'] if not h.get('grandfathers') or not h.get('great_grandfathers')]
    return data
