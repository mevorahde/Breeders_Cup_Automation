"""Generate clearly marked, repeatable synthetic posts and odds for previews."""
from copy import deepcopy
import random
from .core import prepare,post_order

DEMO_ODDS=('1-1','6-5','7-5','8-5','9-5','2-1','5-2','3-1','7-2','4-1',
           '9-2','5-1','6-1','8-1','10-1','12-1','15-1','20-1','30-1','50-1')


def prepare_demo(data,seed=2026):
    result=deepcopy(data)
    races,horses,entries=prepare(result)
    rng=random.Random(seed)
    selected=[]
    for race in races:
        field=sorted((e for e in entries if e['race_id']==race['id']),
                     key=lambda e:post_order(e,horses[e['horse_id']]))[:13]
        rng.shuffle(field)
        for post,entry in enumerate(field,1):
            entry.update(post=post,odds=rng.choice(DEMO_ODDS),result=None,pick=None,
                         demo_values=True)
            entry.setdefault('field_sources',{}).update(post='Generated DEMO value',odds='Generated DEMO value')
            selected.append(entry)
    result['entries']=selected
    result['assignments']={}
    result['demo']={'seed':seed,'max_horses_per_race':13,
                    'notice':'DEMO: post positions and odds are generated sample values, not official declarations.'}
    result.setdefault('collection_report',{})['workbook_generation']={
        'demo':True,'test_generation':True,'seed':seed,'max_horses_per_race':13,
        'displayed_race_entries':len(selected),'overage_horses':len(horses),
        'notice':result['demo']['notice']}
    return result
