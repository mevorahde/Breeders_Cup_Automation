"""Find watchlist ancestors using observed, linked cached pedigree records."""
import hashlib
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote_plus
from bs4 import BeautifulSoup
from .pedigree import normalized, pedigree_table
from .pedigreequery import parse_pedigree
from .core import famous_ancestors
from .famous_horses import FAMOUS_HORSES


def node_key(url):
    parsed=urlparse(url)
    if parsed.netloc=='www.pedigreequery.com':
        alias=parse_qs(parsed.query).get('h',[parsed.path.strip('/')])[0]
        return 'pq:'+unquote_plus(alias).casefold().strip()
    if parsed.netloc=='en.netkeiba.com':
        return 'nk:'+parsed.path.replace('/ped/','/').rstrip('/')
    if parsed.netloc=='racedb.com':
        return 'rd:'+parsed.path
    return None


def annotate_famous(data, cache):
    """Join only source horse IDs, never same-name horses from unrelated records.

    A known parent may have a deeper pedigree in another already-collected table.
    Such joins retain an explicit parent-by-parent path and source evidence.
    Unavailable records are not fetched by this offline calculation.
    """
    cache=Path(cache)
    names={}
    edges=defaultdict(lambda:defaultdict(set))
    evidence={}
    starts=defaultdict(set)
    pages={}
    failures=[]
    for horse in data['horses']:
        urls=set()
        for field in ('grandfathers','great_grandfathers'):
            value=horse.get('field_sources',{}).get(field,[])
            urls.update([value] if isinstance(value,str) else value)
        for url in sorted(urls):
            try:
                if url not in pages:
                    host=urlparse(url).netloc
                    folder={'racedb.com':'','en.netkeiba.com':'netkeiba',
                            'www.pedigreequery.com':'pedigreequery'}.get(host)
                    if folder is None:
                        continue
                    path=cache/folder/(hashlib.sha256(url.encode()).hexdigest()+'.html')
                    if not path.exists():
                        failures.append({'name':horse['name'],'reason':'Source page not in selected cache','url':url})
                        continue
                    html=path.read_text(encoding='utf8')
                    tree=parse_pedigree(html) if host=='www.pedigreequery.com' else pedigree_table(html)
                    root=node_key(url)
                    if host=='www.pedigreequery.com':
                        table=BeautifulSoup(html,'html.parser').select_one('table.pedigreetable')
                        alias=table.get('summary')
                        if alias:
                            root=node_key('https://www.pedigreequery.com/'+alias)
                    pages[url]=(tree,root)
                    keys={'':root}
                    names.setdefault(root,tree['name'])
                    for branch,node in tree['nodes'].items():
                        key=node_key(node['url']) if node.get('url') else None
                        key=key or f'{root}#{branch}'
                        keys[branch]=key
                        if node.get('name'):
                            names.setdefault(key,node['name'])
                    for branch,key in keys.items():
                        for side in ('S','D'):
                            child=keys.get(branch+side)
                            if child:
                                edges[key][side].add(child)
                                evidence[(key,child)]=url
                tree,root=pages[url]
                if normalized(tree['name'])==normalized(horse['name']):
                    starts[horse['id']].add(root)
                else:
                    for side,field in [('S','father'),('D','dam')]:
                        if normalized(tree['name'])==normalized(horse.get(field)):
                            synthetic='horse:'+horse['id']
                            names[synthetic]=horse['name']
                            edges[synthetic][side].add(root)
                            evidence[(synthetic,root)]=url
                            starts[horse['id']].add(synthetic)
            except (ValueError,KeyError,OSError) as exc:
                failures.append({'name':horse['name'],'url':url,'reason':str(exc)})
    watch={normalized(n):n for n in FAMOUS_HORSES}
    for horse in data['horses']:
        proofs={}
        queue=deque((root,[horse['name']],[]) for root in sorted(starts[horse['id']]))
        visited=set()
        while queue:
            current,path,sources=queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            match=watch.get(normalized(names.get(current,'')))
            if match and len(path)>1:
                proofs.setdefault(match,{'path':path,'generations':len(path)-1,'sources':sorted(set(sources))})
            for side in ('S','D'):
                candidates=edges[current].get(side,set())
                if len(candidates)!=1:
                    continue  # Source identity with conflicting parents cannot be joined.
                child=next(iter(candidates))
                if names.get(child):
                    queue.append((child,path+[names[child]],sources+[evidence[(current,child)]]))
        horse['famous_ancestor_evidence']=proofs
        horse['pedigree_ancestors']=sorted(set(horse.get('pedigree_ancestors',[]))|set(proofs))
        horse['other_ancestors']=famous_ancestors(horse,FAMOUS_HORSES)
        if proofs:
            horse.setdefault('field_sources',{})['other_ancestors']=sorted({u for p in proofs.values() for u in p['sources']})
    report={'watchlist':FAMOUS_HORSES,'horses_checked':len(data['horses']),
            'horses_with_matches':sum(bool(h['other_ancestors']) for h in data['horses']),
            'no_match_in_available_records':[h['name'] for h in data['horses'] if not h['other_ancestors']],
            'coverage':'Collected pedigree tables plus deeper parent links found in the selected source cache',
            'cache_issues':failures}
    data.setdefault('collection_report',{})['famous_ancestors']=report
    return data
