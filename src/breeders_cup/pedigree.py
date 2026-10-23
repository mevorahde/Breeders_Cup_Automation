"""Cached, identity-checked pedigree-table enrichment from racedb.com.

The two grandfathers are SS/DS. The four great-grandfathers are SSS/SDS/DSS/DDS,
in the same paternal-to-maternal order as the user's research template.
"""
import hashlib
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .sources import fetch

HOME = 'https://racedb.com'
INDEX = HOME + '/name/index.html'


def normalized(name):
    name = re.sub(r'\s*\(\s*[A-Z]{2,3}\s*\)\s*$', '', name or '')
    return ''.join(c for c in unicodedata.normalize('NFKD', name).casefold()
                   if c.isascii() and c.isalnum())


def pedigree_table(html):
    soup = BeautifulSoup(html, 'html.parser')
    tables = [t for t in soup.find_all('table') if t.find('td', rowspan='16')]
    if len(tables) != 1:
        raise ValueError('Expected one five-generation pedigree table')
    rows = tables[0].find_all('tr', recursive=False)
    if not rows:
        rows = tables[0].find_all('tr')
    if len(rows) != 32:
        raise ValueError('Pedigree must have 32 leaf rows')
    grid = [[None] * 5 for _ in rows]
    for r, row in enumerate(rows):
        col = 0
        for cell in row.find_all(['td', 'th'], recursive=False):
            while col < 5 and grid[r][col] is not None:
                col += 1
            if col >= 5 or int(cell.get('colspan', 1)) != 1:
                raise ValueError('Unexpected pedigree column structure')
            span = int(cell.get('rowspan', 1))
            if span != 2 ** (4-col) or r % span or r+span > 32:
                raise ValueError('Unexpected pedigree generation span')
            link = cell.find('a', href=True)
            name = link.get_text(' ', strip=True) if link else cell.get_text('|', strip=True).split('|')[0].strip()
            name = re.sub(r'\s+', ' ', name).strip()
            name = re.sub(r'\s*\(\s*[A-Z]{2,3}\s*\)\s*$', '', name)
            node = {'name': name, 'url': urljoin(HOME, link['href']) if link else None}
            for at in range(r, r+span):
                if grid[at][col] is not None:
                    raise ValueError('Overlapping pedigree cells')
                grid[at][col] = node
            col += 1
    if any(n is None for row in grid for n in row):
        raise ValueError('Incomplete pedigree grid')
    title = next((h for h in soup.find_all('h1') if h.get_text(strip=True)), None)
    title = title.get_text(' ', strip=True) if title else ''
    # Parent pages sometimes display a Japanese name followed by its English name.
    english = re.findall(r"[A-Za-z][A-Za-z0-9 '\-.,]*", title)
    root = max(english, key=len).strip() if english else title
    heading = next((h.get_text(' ', strip=True) for h in soup.find_all(['h2','h3'])
                    if re.search(r'(?:18|19|20)\d{2}', h.get_text())), '')
    year = re.search(r'(?:18|19|20)\d{2}', heading)
    nodes = {}
    for depth in range(1, 6):
        for i in range(2 ** depth):
            path = ''.join('D' if bit == '1' else 'S' for bit in f'{i:0{depth}b}')
            nodes[path] = grid[i * (32 // 2**depth)][depth-1]
    return {'name': root, 'year': int(year.group()) if year else None, 'nodes': nodes}


class PedigreeClient:
    def __init__(self, cache):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pages = {}

    def get(self, url):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'racedb.com':
            raise ValueError('Unexpected pedigree source host')
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')
        if path.exists():
            return path.read_text(encoding='utf-8')
        time.sleep(0.2)
        html = fetch(url)
        path.write_text(html, encoding='utf-8')
        return html

    def page(self, url):
        if url not in self.pages:
            self.pages[url] = pedigree_table(self.get(url))
        return self.pages[url]

    def english_name(self, node):
        if node['name'].isascii():
            return node['name']
        if node['url']:
            name = self.page(node['url'])['name']
            if name.isascii():
                return name
        return None

    def index(self):
        hub = BeautifulSoup(self.get(INDEX), 'html.parser')
        links = sorted({urljoin(HOME, a['href']) for a in hub.find_all('a', href=True)
                        if re.fullmatch(r'/name/[a-z]{1,2}\.html', a['href'])})
        if len(links) < 26:
            raise ValueError('Horse index structure changed')
        index = {}
        for i, url in enumerate(links):
            s = BeautifulSoup(self.get(url), 'html.parser')
            for a in s.find_all('a', href=True):
                if re.fullmatch(r'/(a|p)/\d+\.html', a['href']):
                    label = a.get_text(' ', strip=True)
                    year = re.search(r'(?:18|19|20)\d{2}', label)
                    name = re.split(r'[\u3000\uff08(]', label)[0].strip()
                    if normalized(name):
                        index.setdefault(normalized(name), set()).add((urljoin(HOME, a['href']), int(year.group()) if year else None))
                    elif year:
                        # Japanese horses are indexed under their Japanese names.
                        # Restrict candidates by foaling year, then verify the
                        # English identity on each candidate's own pedigree page.
                        index.setdefault('@'+year.group(), set()).add((urljoin(HOME, a['href']), int(year.group())))
            if (i+1) % 15 == 0:
                print(f'Pedigree index: {i+1}/{len(links)} pages', flush=True)
        return index


def enrich(data, cache):
    client = PedigreeClient(cache)
    report = {'source': HOME, 'matched': 0, 'complete_grandfathers': 0,
              'complete_great_grandfathers': 0, 'unresolved': []}
    try:
        index = client.index()
    except Exception as exc:
        report['error'] = str(exc)
        data.setdefault('collection_report', {})['pedigree'] = report
        return data
    for i, horse in enumerate(data['horses']):
        try:
            if not horse.get('date_of_birth'):
                raise ValueError('Missing birth date for identity check')
            year = int(horse['date_of_birth'][:4])
            candidates = index.get(normalized(horse['name']), set())
            if not candidates:
                candidates = index.get('@'+str(year), set())
            matches = []
            for url, indexed_year in sorted(candidates):
                if indexed_year is not None and indexed_year != year:
                    continue
                tree = client.page(url)
                if normalized(tree['name']) != normalized(horse['name']) or tree['year'] != year:
                    continue
                sire = client.english_name(tree['nodes']['S'])
                dam = client.english_name(tree['nodes']['D'])
                if (normalized(tree['name']) == normalized(horse['name']) and tree['year'] == year
                        and sire and normalized(sire) == normalized(horse['father'])):
                    if horse.get('dam') and dam and normalized(dam) != normalized(horse['dam']):
                        continue
                    matches.append((url, tree))
            if len(matches) != 1:
                raise ValueError(f'{len(matches)} verified pedigree matches')
            url, tree = matches[0]
            branches = {}
            for branch in ('SS','DS','SSS','SDS','DSS','DDS'):
                branches[branch] = client.english_name(tree['nodes'][branch])
            horse['pedigree_branches'] = branches
            horse['pedigree_ancestors'] = sorted(set(
                [v for v in branches.values() if v] +
                [n['name'] for n in tree['nodes'].values() if n['name'] and n['name'].isascii()]))
            for field, paths in [('grandfathers', ('SS','DS')), ('great_grandfathers', ('SSS','SDS','DSS','DDS'))]:
                if all(branches[p] for p in paths):
                    horse[field] = '; '.join(branches[p] for p in paths)
                    horse.setdefault('field_sources', {})[field] = url
                    report['complete_'+field] += 1
            report['matched'] += 1
            if not all(branches.values()):
                report['unresolved'].append({'name': horse['name'], 'reason': 'Some ancestors lack verified English names'})
        except Exception as exc:
            report['unresolved'].append({'name': horse['name'], 'reason': str(exc)})
        if (i+1) % 20 == 0:
            print(f'Pedigrees: {i+1}/{len(data["horses"])}; {report["matched"]} verified', flush=True)
    data.setdefault('collection_report', {})['pedigree'] = report
    data['collection_report']['missing_field_counts'] = {
        f: sum(not h.get(f) for h in data['horses']) for f in
        ('jockey','trainer','color','date_of_birth','father','last_previous_race','grandfathers','great_grandfathers')}
    return data
