"""Conservative HTTP diagnostics and explicit HTML table extraction.

No site-specific parser is declared production-ready until captured pages verify it.
"""
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

SOURCES = {
    'bloodhorse': 'https://www.bloodhorse.com/horse-racing/breeders-cup',
    'breederscup': 'https://www.breederscup.com/horses/contenders',
    'horseracingnation': 'https://www.horseracingnation.com/',
    'equineline': 'https://www.equineline.com/Free-5X-Pedigree.cfm',
}
AGENT = 'BreedersCupAutomation/0.1'
_ROBOTS_CACHE = {}


def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise ValueError('Only HTTPS source URLs are supported')
    robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
    if robots_url not in _ROBOTS_CACHE:
        try:
            with urlopen(Request(robots_url, headers={'User-Agent': AGENT}), timeout=25) as response:
                policy = response.read(2_000_000).decode('utf-8', errors='replace')
            robots = RobotFileParser()
            robots.parse(policy.splitlines())
            _ROBOTS_CACHE[robots_url] = robots
        except HTTPError as exc:
            if exc.code != 404:
                raise ValueError(f'Cannot verify robots.txt: HTTP {exc.code}') from exc
            _ROBOTS_CACHE[robots_url] = None
    robots = _ROBOTS_CACHE[robots_url]
    if robots is not None and not robots.can_fetch(AGENT, url):
        raise ValueError(f'robots.txt disallows this URL: {url}')
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': AGENT}), timeout=25) as response:
                from bs4 import UnicodeDammit
                raw = response.read(10_000_000)
                text = UnicodeDammit(raw, is_html=True).unicode_markup
                if text is None:
                    raise ValueError('Cannot decode source HTML')
                return text
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def extract_table(html, selector, columns):
    """Map explicit table header labels to normalized fields; fail on site drift."""
    from bs4 import BeautifulSoup
    table = BeautifulSoup(html, 'html.parser').select_one(selector)
    if table is None:
        raise ValueError(f'No matching table: {selector}; page may require JavaScript')
    rows = table.select('tr')
    if not rows:
        raise ValueError('Table has no rows')
    headers = [c.get_text(' ', strip=True) for c in rows[0].find_all(['th', 'td'])]
    if len(headers) != len(set(headers)):
        raise ValueError('Duplicate table headers')
    missing = set(columns) - set(headers)
    if missing:
        raise ValueError(f'Missing source columns: {sorted(missing)}')
    records = []
    for row in rows[1:]:
        cells = row.find_all(['th', 'td'])
        if not cells:
            continue
        if len(cells) != len(headers):
            raise ValueError('Table row width changed; refusing shifted data')
        records.append({field: cells[headers.index(label)].get_text(' ', strip=True)
                        for label, field in columns.items()})
    if not records:
        raise ValueError('Table has no data records')
    return records
