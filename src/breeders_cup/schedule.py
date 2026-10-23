"""Discover and parse official current-year championship schedule tables."""
import json
import re
from datetime import datetime,date,time,timezone,timedelta
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
from .sources import fetch
from .pedigree import normalized
from .core import prepare

HOME='https://www.breederscup.com'


def schedule_links(html,year):
    soup=BeautifulSoup(html,'html.parser')
    values=[a['href'] for a in soup.find_all('a',href=True)]
    script=soup.select_one('#__NEXT_DATA__')
    def walk(value):
        if isinstance(value,dict):
            for v in value.values():walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
        elif isinstance(value,str):values.append(value)
    if script:
        walk(json.loads(script.get_text()))
    return {urljoin(HOME,v) for v in values if v.startswith(('/',HOME+'/')) and
            f'/news/{year}/' in v and 'race-order' in v.lower() and
            urlparse(urljoin(HOME,v)).netloc=='www.breederscup.com'}


def eastern_zone(day):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('America/New_York')
    except (ImportError,KeyError):
        march=date(day.year,3,1);november=date(day.year,11,1)
        start=date(day.year,3,1+(6-march.weekday())%7+7)
        end=date(day.year,11,1+(6-november.weekday())%7)
        return timezone(timedelta(hours=-4 if start<=day<end else -5))


def parse_schedule(html,races,year):
    soup=BeautifulSoup(html,'html.parser')
    script=soup.select_one('#__NEXT_DATA__')
    if script is None:raise ValueError('Official announcement lacks structured article data')
    blocks=json.loads(script.get_text())['props']['pageProps']['blocks']
    articles=[b['articleMetadata']['article'] for b in blocks if 'articleMetadata' in b]
    if len(articles)!=1:raise ValueError('Expected one official announcement')
    article=articles[0]
    if str(year) not in article['title'] or f'/news/{year}/' not in article['url'] or int(article['publishDate'][:4])!=year:
        raise ValueError('Race-order announcement is for a different year')
    body=BeautifulSoup(article['content'],'html.parser')
    expected={normalized(r['name']):r for r in races}
    if len(expected)!=len(races):raise ValueError('Duplicate championship race names')
    found={};positions=set()
    for table in body.find_all('table'):
        headers=[h.get_text(' ',strip=True) for h in table.find_all('th')]
        if not all(h in headers for h in ['Race','Post Time (ET)','Race Name']):continue
        table_dates=set()
        for row in table.find_all('tr'):
            cells=row.find_all('td',recursive=False)
            if len(cells)<3:continue
            label,post,name=[c.get_text(' ',strip=True) for c in cells[:3]]
            number=re.fullmatch(r'Race\s+(\d+)',label)
            championship=re.search(r"Breeders[’']?\s+Cup\s+(.+?)(?:\s*\(G[1-3]\)?|$)",name,re.I)
            if not championship:continue
            key=normalized(championship.group(1))
            if key not in expected:raise ValueError(f'Unknown championship in schedule: {name}')
            if not number:raise ValueError('Championship row lacks a track race number')
            race=expected[key];day=date.fromisoformat(race['date'])
            table_dates.add(day)
            clock=datetime.strptime(post,'%I:%M %p').time()
            stamp=datetime.combine(day,clock,tzinfo=eastern_zone(day)).astimezone(timezone.utc)
            position=(day,int(number.group(1)))
            if race['id'] in found or position in positions:raise ValueError('Duplicate championship or race number')
            positions.add(position)
            found[race['id']]={'number':position[1],'scheduled_at':stamp.isoformat(),'post_time_et':post}
        if len(table_dates)>1:raise ValueError('Schedule table mixes race dates')
    if len(found)!=len(races) or len(found)!=14:
        raise ValueError(f'Incomplete official schedule: {len(found)}/{len(races)} races')
    return found,article['publishDate']


def enrich_schedule(data,discovery_html=''):
    report={'matched':0,'errors':[]}
    try:
        links=schedule_links(discovery_html,data['year']) if discovery_html else set()
        for index in (HOME,HOME+'/news'):
            if links:break
            links.update(schedule_links(fetch(index),data['year']))
        if not links:raise ValueError('Official current-year race-order announcement not found')
        candidates=[]
        for url in sorted(links):
            try:
                found,published=parse_schedule(fetch(url),data['races'],data['year'])
                candidates.append((published,url,found))
            except Exception as exc:
                report['errors'].append({'source':url,'reason':str(exc)})
        if not candidates:raise ValueError('No complete, valid official schedule was available')
        published,url,found=max(candidates,key=lambda x:x[0])
        for race in data['races']:
            race.update(found[race['id']])
            race['number_source_url']=url
            race['number_retrieved_at']=datetime.now(timezone.utc).isoformat()
        prepare(data)
        report.update(matched=len(found),source=url,published=published)
        summary=data.setdefault('collection_report',{})
        summary['limitations']=[s for s in summary.get('limitations',[]) if 'Track race numbers are unavailable' not in s]
    except Exception as exc:
        report['errors'].append({'reason':str(exc)})
    data.setdefault('collection_report',{})['race_schedule']=report
    return data
