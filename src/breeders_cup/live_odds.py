"""Identity-checked snapshots of Keeneland's public live tote dashboard."""
from datetime import datetime, timezone, date, timedelta
import json
import re
from .sources import fetch
from .pedigree import normalized
from .schedule import eastern_zone

LIVE_URL='https://rt-worker.keeneland.com/api/odds'
DASHBOARD='https://www.keeneland.com/odds'


def utc_stamp(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    # Keeneland's dashboard explicitly interprets bare postTimes as UTC.
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def live_fraction(value):
    if not isinstance(value,str):return None
    value=value.strip()
    if value.upper() in ('EVEN','EVENS','EVS'):return '1-1'
    match=re.fullmatch(r'(\d+)\s*[-/]\s*(\d+)',value)
    if match and int(match[2])>0:
        return f'{int(match[1])}-{int(match[2])}'
    return None


def refresh_odds(data,previous=None,*,now=None,payload=None):
    """Use verified live rows before post; otherwise keep official morning lines.

    Past-post snapshots are retained with their original time, never presented
    as a fresh live quote. Missing rows never imply a scratch.
    """
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Odds check needs a timezone-aware time')
    now=now.astimezone(timezone.utc)
    checked=now.isoformat()
    races={r['id']:r for r in data['races']}
    horses={h['id']:h for h in data['horses']}
    prior_entries={(e['horse_id'],e['race_id']):e for e in (previous or {}).get('entries',[])}
    prior_horses={h['id']:h for h in (previous or {}).get('horses',[])}
    prior_races={r['id']:r for r in (previous or {}).get('races',[])}
    report={'checked_at':checked,'source_url':LIVE_URL,'dashboard_url':DASHBOARD,
            'live_entries':0,'morning_line_entries':0,'retained_snapshots':0,
            'scratched_entries':0,'errors':[],'races':[]}
    eligible={}
    for entry in data['entries']:
        race=races[entry['race_id']]
        if entry.get('scratched') or str(entry.get('odds','')).upper()=='SCR':
            entry.update(odds='SCR',odds_type='scratch',odds_as_of=data.get('retrieved_at',checked))
            continue
        if entry.get('odds'):
            entry.setdefault('morning_line_odds',entry['odds'])
            entry['odds']=entry['morning_line_odds']
            entry.update(odds_type='morning-line',odds_as_of=data.get('retrieved_at',checked),
                         odds_source_url=entry.get('field_sources',{}).get('odds',data.get('official_source','')))
        start=utc_stamp(race['scheduled_at']) if race.get('scheduled_at') else None
        if start and now>=start:
            prior=prior_entries.get((entry['horse_id'],entry['race_id']))
            old_horse=prior_horses.get(entry['horse_id'],{})
            old_race=prior_races.get(entry['race_id'],{})
            if (prior and prior.get('odds_type') in ('live','live-snapshot') and prior.get('odds_as_of')
                and normalized(old_horse.get('name'))==normalized(horses[entry['horse_id']]['name'])
                and old_race.get('date')==race['date'] and old_race.get('number')==race['number']):
                for key in ('odds','odds_as_of','odds_source_url'):
                    entry[key]=prior.get(key)
                entry['odds_type']='live-snapshot'
            continue
        if normalized(race.get('track_name'))=='keeneland' and race.get('number'):
            eligible.setdefault(entry['race_id'],[]).append(entry)
    try:
        feed=payload if payload is not None else json.loads(fetch(LIVE_URL))
        if feed.get('_stale') is not False or feed.get('isActive') is not True:
            raise ValueError('Tote feed is stale or inactive; morning lines retained')
        cached=feed.get('_cached_at')
        if type(cached) not in (int,float):raise ValueError('Tote feed lacks a valid timestamp')
        as_of=datetime.fromtimestamp(cached/1000,timezone.utc)
        if not -timedelta(minutes=2)<=now-as_of<=timedelta(minutes=5):
            raise ValueError('Tote feed timestamp is outside the freshness window')
        report['source_as_of']=as_of.isoformat()
        live=feed.get('odds',{}).get('live',{})
        if live.get('error') is not False or live.get('source')!='UTote' or live.get('odds_type')!='odds':
            raise ValueError('Live tote section is unavailable or unrecognized')
        times=feed.get('details',{}).get('postTimes',[])
        if not times or feed.get('details',{}).get('raceCount')!=len(times):
            raise ValueError('Tote race dates cannot be verified')
        for rid,entries in eligible.items():
            race=races[rid];number=race['number']
            if number>len(times):continue
            post=utc_stamp(times[number-1])
            day=date.fromisoformat(race['date'])
            if post.astimezone(eastern_zone(day)).date()!=day:
                report['races'].append({'race':race['name'],'status':'different race date; morning lines retained'})
                continue
            if now>=post:continue
            rows=live.get('races',{}).get(str(number),[])
            lookup={}
            for entry in (e for e in data['entries'] if e['race_id']==rid):
                key=(normalized(horses[entry['horse_id']]['name']),str(entry.get('post','')).upper())
                if key in lookup:raise ValueError('Duplicate horse/program identity in official entries')
                lookup[key]=entry
            matches=[];seen=set()
            for row in rows:
                key=(normalized(row.get('horse_name')),str(row.get('program_number','')).upper())
                if row.get('race_number')!=number or key not in lookup or key in seen:
                    matches=[]
                    report['errors'].append({'race':race['name'],'reason':'Tote horse/program identities differ from official entries'})
                    break
                seen.add(key)
                fraction=live_fraction(row.get('odds'))
                # Do not use projections, arbitrary numeric prices, or infer
                # withdrawals from missing tote rows or non-price markers.
                if fraction is not None and not lookup[key].get('scratched') and lookup[key].get('odds')!='SCR':
                    matches.append((lookup[key],fraction))
            for entry,odds in matches:
                entry.update(odds=odds,odds_type='live',odds_as_of=as_of.isoformat(),odds_source_url=LIVE_URL)
                entry.setdefault('field_sources',{})['odds']=LIVE_URL
            report['races'].append({'race':race['name'],'status':'verified live snapshot' if matches else 'no usable live prices',
                                    'matched':len(matches)})
    except Exception as error:
        report['errors'].append({'reason':str(error)})
    for entry in data['entries']:
        kind=entry.get('odds_type')
        key={'live':'live_entries','live-snapshot':'retained_snapshots','scratch':'scratched_entries',
             'morning-line':'morning_line_entries'}.get(kind)
        if key:report[key]+=1
    data.setdefault('collection_report',{})['odds_refresh']=report
    return data
