"""Refresh current Cup rider declarations; never substitute historical riders."""
import json
import re
import time
from datetime import datetime,timezone,date
from urllib.parse import urlparse
from xml.etree import ElementTree
from bs4 import BeautifulSoup
from .collector import OFFICIAL,parse_official
from .sources import fetch
from .pedigree import normalized

NEWS='https://www.sportinglife.com/sitemap-news.xml'


def clean_rider(value):
    value=re.sub(r'\s+',' ',value or '').strip()
    return value if value.casefold() not in ('','-','--','-- --','n/a','na','tba','tbd','unknown','not declared') else None


def announcement(html,horses,year,cutoff):
    """Accept only a current-year explicit future booking for the headline horse."""
    soup=BeautifulSoup(html,'html.parser')
    articles=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            item=json.loads(script.get_text())
            if isinstance(item,dict) and item.get('@type')=='Article':
                articles.append(item)
        except ValueError:
            continue
    if len(articles)!=1:
        return None
    meta=articles[0]
    published=date.fromisoformat(meta['datePublished'][:10])
    title=meta.get('headline','')
    if published.year!=year or published<date(year,9,1) or published>cutoff or not re.search(r"Breeders.?\s*Cup",title,re.I):
        return None
    candidates=[h for h in horses if re.search(r'(?<![A-Za-z])'+re.escape(re.sub(r'\s*\([A-Z]{2,3}\)$','',h['name']))+r'(?![A-Za-z])',title,re.I)]
    if len(candidates)!=1:
        return None
    matches=[]
    for paragraph in soup.find_all('p'):
        text=paragraph.get_text(' ',strip=True)
        # This explicit confirmation excludes past rides and projected bookings.
        match=re.search(r"\bwith ([A-Z][a-z]+(?:[-'][A-Za-z]+)?(?: [A-Z][a-z]+(?:[-'][A-Za-z]+)?){1,3}), who (?:he|she|they) confirmed will ride the horse (?:in Kentucky|at Keeneland)",text)
        if match:
            matches.append((match.group(1),text))
    if len(set(r for r,_ in matches))!=1:
        return None
    return candidates[0]['id'],matches[0][0],published.isoformat(),matches[0][1]


def refresh_jockeys(data):
    retrieved=datetime.now(timezone.utc).isoformat()
    report={'policy':'Confirmed Breeders Cup riders only; no last-race substitutions',
            'retrieved_at':retrieved,'official_source':OFFICIAL,'errors':[],'announcements':[]}
    try:
        fresh=parse_official(fetch(OFFICIAL),data['year'],retrieved)
        lookup={h['id']:h for h in fresh['horses']}
        for horse in data['horses']:
            current=lookup.get(horse['id'])
            if not current:
                continue
            # Stable official ID plus name protects against a shifted record.
            if normalized(current['name'])!=normalized(horse['name']):
                report['errors'].append({'name':horse['name'],'reason':'Official identity mismatch'})
                continue
            rider=clean_rider(current.get('jockey'))
            if rider:
                horse.update(jockey=rider,jockey_status='confirmed',jockey_retrieved_at=retrieved)
                horse.setdefault('field_sources',{})['jockey']=current['source_url']
    except Exception as exc:
        report['errors'].append({'source':OFFICIAL,'reason':str(exc)})
    try:
        sitemap=ElementTree.fromstring(fetch(NEWS))
        urls=sorted({loc.text for loc in sitemap.findall('.//{*}loc')
                     if loc.text and '/racing/news/' in loc.text and 'breeders-cup' in loc.text})
        cutoff=min(date.today(),min(date.fromisoformat(r['date']) for r in data['races']))
        for url in urls:
            if urlparse(url).netloc!='www.sportinglife.com':
                continue
            time.sleep(0.5)
            try:
                booking=announcement(fetch(url),data['horses'],data['year'],cutoff)
                if booking:
                    hid,rider,published,quote=booking
                    horse=next(h for h in data['horses'] if h['id']==hid)
                    if horse.get('jockey_status')=='confirmed' and horse.get('jockey') and normalized(horse['jockey'])!=normalized(rider):
                        report['errors'].append({'name':horse['name'],'reason':'Announcement differs from official declaration; official retained'})
                        continue
                    horse.update(jockey=rider,jockey_status='confirmed',jockey_retrieved_at=retrieved)
                    horse.setdefault('field_sources',{})['jockey']=url
                    report['announcements'].append({'name':horse['name'],'jockey':rider,'published':published,'url':url,'evidence':quote})
            except Exception as exc:
                report['errors'].append({'source':url,'reason':str(exc)})
    except Exception as exc:
        report['errors'].append({'source':NEWS,'reason':str(exc)})
    report['horses_checked']=len(data['horses'])
    report['confirmed']=sum(h.get('jockey_status')=='confirmed' and bool(h.get('jockey')) for h in data['horses'])
    report['unconfirmed']=[h['name'] for h in data['horses'] if not h.get('jockey') or h.get('jockey_status')!='confirmed']
    data.setdefault('collection_report',{})['jockeys']=report
    data['collection_report'].setdefault('missing_field_counts',{})['jockey']=sum(not h.get('jockey') for h in data['horses'])
    return data
