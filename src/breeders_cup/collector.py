"""Collect official public page data without driving a browser."""
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .sources import fetch, SOURCES
from .core import last_race_before, prepare

OFFICIAL = 'https://www.breederscup.com/horses/pre-entries/classic'
OFFICIAL_ENTRIES = 'https://www.breederscup.com/horses/entries/classic'


def official_identity(raw, url):
    """Keep the horse name separate from a CMS page title containing a year."""
    name = raw['horseName'].strip()
    title = raw.get('pageTitle') or name
    if re.fullmatch(re.escape(name)+r'(?:\s*\([A-Z]{2,3}\))?',title,re.I):
        name = title
    fields = {'name':name}
    if any(not raw.get(f) or raw[f]=='--' for f in ('sireName','damName')):
        text = BeautifulSoup(raw.get('bio') or '', 'html.parser').get_text(' ',strip=True)
        # Only an explicit, unambiguous pedigree sentence is accepted.
        matches = re.findall(r"\bby ([A-Za-z][A-Za-z .’'\-]+?\s*\([A-Z]{2,3}\)) out of the "
                             r"([A-Za-z][A-Za-z .’'\-]+?) mare ([A-Za-z][A-Za-z .’'\-]+?\s*\([A-Z]{2,3}\))",text)
        if len(set(matches)) == 1:
            sire,damsire,dam = matches[0]
            from .pedigree import normalized
            if any(raw.get(f) not in (None,'','--') and normalized(raw[f])!=normalized(value)
                   for f,value in [('sireName',sire),('damName',dam)]):
                return fields
            fields.update(father=sire.strip(),dam=dam.strip(),maternal_grandsire=damsire.strip(),
                          identity_source=url,identity_method='Explicit pedigree sentence in official biography')
    return fields


def repair_incomplete_identities(data):
    """Refresh incomplete saved identities from their own official profile."""
    for horse in data['horses']:
        if horse.get('date_of_birth') and all(horse.get(f) and horse[f]!='--' for f in ('father','dam')):
            continue
        url = horse.get('source_url','')
        if not url.startswith('https://www.breederscup.com/'):
            continue
        try:
            soup = BeautifulSoup(fetch(url),'html.parser')
            props = json.loads(soup.select_one('#__NEXT_DATA__').get_text())['props']['pageProps']
            profiles = [b['horseHeroBanner']['horse'] for b in props['blocks'] if 'horseHeroBanner' in b]
            if len(profiles)!=1 or profiles[0]['uid']!=horse['id']:
                raise ValueError('Official detail identity differs from saved horse ID')
            fields = official_identity(profiles[0],url)
            horse['name'] = fields.pop('name')
            for field,value in fields.items():
                if field in ('father','dam') and horse.get(field) not in (None,'','--',value):
                    raise ValueError('Biography conflicts with structured parents')
            horse.update(fields)
            for field in ('father','dam','maternal_grandsire'):
                if field in fields:
                    horse.setdefault('field_sources',{})[field] = url
        except Exception as exc:
            data.setdefault('collection_report',{}).setdefault('identity_refresh_errors',[]).append(
                {'name':horse['name'],'reason':str(exc)})
    return data


def source_date(value):
    if not value:
        return None
    return datetime.strptime(value, '%B, %d %Y %H:%M:%S').date().isoformat()


def parse_official(html, year, retrieved_at, source_url=OFFICIAL):
    soup = BeautifulSoup(html, 'html.parser')
    script = soup.find('script', id='__NEXT_DATA__')
    if script is None:
        raise ValueError('Official page missing __NEXT_DATA__; source layout changed or access blocked')
    props = json.loads(script.string or script.get_text())['props']['pageProps']
    cards = [b['horseCards'] for b in props['blocks'] if 'horseCards' in b]
    if len(cards) != 1 or not cards[0].get('races'):
        raise ValueError('Official horseCards races missing')
    withdrawals = []
    for block in props['blocks']:
        rich = block.get('richTextEditor', {}).get('html', '')
        if 'withdrawn from' in rich:
            withdrawals.extend(p.get_text(' ', strip=True) for p in BeautifulSoup(rich, 'html.parser').find_all('p') if 'withdrawn from' in p.get_text())
    excluded = set()
    for line in withdrawals:
        name, race = line.split(' has withdrawn from the ', 1)
        excluded.add((name.casefold().strip(), re.sub(r'\s*\(AE.*', '', race).casefold().strip()))
    horses, entries, races, skipped = {}, [], [], []
    for race in cards[0]['races']:
        details = race['raceDetails']
        stamp = datetime.fromisoformat(details['date'].replace('Z', '+00:00'))
        offset = race['trackDetails'][0]['details']['timeZone']
        day = stamp.astimezone(timezone(timedelta(hours=offset))).date()
        if day.year != year:
            raise ValueError(f'Source schedule is for {day.year}, not requested {year}')
        rid = race['uid']
        name = details['bcType']
        races.append({'id': rid, 'name': name, 'date': day.isoformat(), 'number': None,
                      'scheduled_at': stamp.isoformat(), 'source_url': source_url,
                      'retrieved_at': retrieved_at})
        for raw in race['horses']:
            if raw.get('year') != year:
                skipped.append({'name': raw.get('horseName'), 'year': raw.get('year'), 'race': name})
                continue
            withdrawn=(raw['horseName'].casefold().strip(), name.casefold()) in excluded
            hid = raw['uid']
            url = urljoin(source_url, raw['url'])
            record = {'id': hid, 'name': raw.get('pageTitle') or raw['horseName'],
                      'source_url': url, 'retrieved_at': retrieved_at,
                      'trainer': raw.get('trainer') or None, 'jockey': raw.get('jockeyName') or None,
                      'color': raw.get('color') or None, 'father': raw.get('sireName') or None,
                      'dam': raw.get('damName') or None,
                      'date_of_birth': source_date(raw.get('foalingDate')),
                      'possible_races': [], 'field_sources': {}}
            record.update(official_identity(raw,url))
            if (record.get('jockey') or '').strip().casefold() in ('','-','--','-- --','tba','tbd','n/a','unknown'):
                record['jockey']=None
            elif record.get('jockey'):
                record['jockey_status']='confirmed'
            for field in ('trainer', 'jockey', 'color', 'father', 'dam', 'maternal_grandsire', 'date_of_birth'):
                if record.get(field) is not None:
                    record['field_sources'][field] = url
            history = []
            for start in raw.get('pastPerformances', []):
                if start.get('raceDate') and start.get('positionAtFinish', 0) and start['positionAtFinish'] > 0:
                    history.append({'date': source_date(start['raceDate']),
                                    'name': start.get('raceName', '').strip() or start.get('trackName', 'Unnamed race'),
                                    'finish': start['positionAtFinish']})
            last = last_race_before(history, day.isoformat())
            if last:
                record['last_previous_race'] = f"{last['name']}: {last['finish']} ({last['date']})"
                record['field_sources']['last_previous_race'] = url
            if hid not in horses:
                horses[hid] = record
            elif any(horses[hid].get(f) != record.get(f) for f in ('name', 'father', 'date_of_birth')):
                raise ValueError(f'Conflicting horse identity: {hid}')
            horses[hid]['possible_races'].append(name)
            engagement = next((r for r in raw.get('races', []) if r['uid'] == rid), {})
            entry = {'horse_id': hid, 'race_id': rid}
            if record.get('jockey'):
                entry['jockey']=record['jockey']
            if engagement.get('scratched') or withdrawn:
                entry['post'] = engagement.get('postPosition') if cards[0].get('horseType')=='entries' and engagement.get('postPosition') else 'SCR'
                entry['scratched']=True
                entry['odds']='SCR'
            elif cards[0].get('horseType') == 'entries' and engagement.get('postPosition'):
                entry['post'] = engagement['postPosition']
            if not entry.get('scratched'):
                odds=engagement.get('morningLineOdds') or engagement.get('odds') or raw.get('morningLineOdds')
                if isinstance(odds,str) and re.fullmatch(r'\d+(?:[-/]\d+|\.\d+)?',odds.strip()):
                    entry['odds']=odds.strip()
            entries.append(entry)
    if len(races) != 14 or not horses:
        raise ValueError(f'Incomplete championship source: {len(races)} races, {len(horses)} horses')
    data = {'year': year, 'races': races, 'horses': list(horses.values()),
            'entries': entries, 'assignments': {}, 'retrieved_at': retrieved_at,
            'withdrawals': withdrawals, 'excluded_wrong_year_records': skipped,
            'official_source': source_url, 'source_stage':cards[0].get('horseType','pre-entries')}
    prepare(data)
    return data


def read_official(year,retrieved_at):
    """Prefer declared entries; never infer final status from a URL alone."""
    candidates=[]
    attempts=[]
    for url in (OFFICIAL_ENTRIES,OFFICIAL):
        try:
            html=fetch(url)
            data=parse_official(html,year,retrieved_at,source_url=url)
            attempts.append({'url':url,'stage':data['source_stage'],
                             'post_positions':sum(bool(e.get('post')) and e.get('post')!='SCR' for e in data['entries'])})
            if data['source_stage']=='entries':
                data['source_checks']=attempts
                return data,html
            candidates.append((data,html))
        except Exception as exc:
            attempts.append({'url':url,'error':str(exc)})
    if candidates:
        data,html=candidates[-1]
        data['source_checks']=attempts
        return data,html
    raise ValueError('No valid current-year official entry feed: '+json.dumps(attempts))


def collect(year):
    retrieved = datetime.now(timezone.utc).isoformat()
    data,html = read_official(year,retrieved)
    diagnostics = {}
    for name in ('bloodhorse', 'horseracingnation', 'equineline'):
        try:
            page = fetch(SOURCES[name])
            if any(marker in page.lower() for marker in ('incapsula incident', 'captcha', 'request unsuccessful')):
                diagnostics[name] = 'Access blocked by source; no fields imported'
            else:
                diagnostics[name] = 'HTTP accessible; enrichment parser not yet implemented; no fields imported'
        except Exception as exc:
            diagnostics[name] = f'Unavailable: {type(exc).__name__}: {exc}'
    data['collection_report'] = {
        'sources': diagnostics, 'official_source': data['official_source'],
        'source_stage':data['source_stage'],'source_checks':data['source_checks'],
        'declared_post_positions':sum(bool(e.get('post')) and e.get('post')!='SCR' for e in data['entries']),
        'horse_count': len(data['horses']), 'race_entry_count': len(data['entries']),
        'excluded_wrong_year_records': data['excluded_wrong_year_records'],
        'missing_field_counts': {f: sum(not h.get(f) for h in data['horses']) for f in
                                 ('jockey', 'trainer', 'color', 'date_of_birth', 'father',
                                  'last_previous_race', 'grandfathers', 'great_grandfathers')},
        'limitations': ['Pre-entries are possible races, not final assignments.',
                       'Track race numbers are unavailable; order uses official scheduled times.',
                       'Pre-entry payload position values are not treated as confirmed draw positions.',
                       'Last race means latest completed start in the official supplied history, before the Cup date.',
                       'Deeper pedigree enrichment is pending; no inferred ancestors.']}
    from .schedule import enrich_schedule
    if data['source_stage']=='entries':
        data['collection_report']['limitations']=[s for s in data['collection_report']['limitations']
            if not s.startswith(('Pre-entries are possible','Pre-entry payload position'))]
    return enrich_schedule(data,html)
