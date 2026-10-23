"""One yearly workbook, with stable row matching and atomic pick-preserving saves."""
from copy import deepcopy,copy
from datetime import datetime,timezone,timedelta,date
from pathlib import Path
import hashlib
import json
import os
import tempfile
import re
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from .pedigree import normalized
from .core import prepare
from .workbook import generate,fit_columns,arrange_columns


def current_date():
    try:
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('America/Los_Angeles')
    except (ImportError,KeyError):
        now=datetime.now(timezone.utc)
        # Windows may lack IANA data. US Pacific DST starts/ends at these UTC hours.
        march=date(now.year,3,1)
        november=date(now.year,11,1)
        start=datetime(now.year,3,1+(6-march.weekday())%7+7,10,tzinfo=timezone.utc)
        end=datetime(now.year,11,1+(6-november.weekday())%7,9,tzinfo=timezone.utc)
        zone=timezone(timedelta(hours=-7 if start<=now<end else -8))
    return datetime.now(zone).date()


def current_year():
    return current_date().year


def copy_cell(source,target):
    target.value=Translator(source.value,origin=source.coordinate).translate_formula(target.coordinate) if source.data_type=='f' else source.value
    if source.data_type=='s':
        target.data_type='s'
    for attr in ('font','fill','border','alignment','protection'):
        setattr(target,attr,copy(getattr(source,attr)))
    target.number_format=source.number_format
    target.comment=copy(source.comment)
    target.hyperlink=copy(source.hyperlink)


def freeze_past_races(data,old,previous,as_of):
    """Rebuild past fields from existing rows, not from a changed live feed."""
    sheet=old[str(data['year'])]
    metadata={r['id']:deepcopy(r) for r in data['races']}
    metadata.update({r['id']:deepcopy(r) for r in (previous or {}).get('races',[])})
    by_name={normalized(r['name']):r['id'] for r in metadata.values()}
    old_horses={h['id']:h for h in (previous or data)['horses']}
    by_horse_name={normalized(h['name']):h['id'] for h in list(old_horses.values())+data['horses']}
    groups={}
    for row in race_rows(sheet):
        rid=(row[19].value if len(row)>19 else None) or by_name.get(normalized(row[0].value))
        if rid in metadata and normalized(row[0].value)!=normalized(metadata[rid]['name']):
            rid=by_name.get(normalized(row[0].value))
        if rid in metadata:
            groups.setdefault(rid,[]).append(row)
    locked={}
    for rid,rows in groups.items():
        header=rows[0][0].row-1
        # The workbook's visible date wins if a live feed changes a saved race date.
        match=re.search(r'\b(\d{2}-\d{2}-\d{4})\b',str(sheet.cell(header,1).value or ''))
        when=datetime.strptime(match.group(1),'%m-%d-%Y').date() if match else date.fromisoformat(metadata[rid]['date'])
        if when>=as_of:
            continue
        race=metadata[rid]
        race['date']=when.isoformat()
        locked[rid]={'race':race,'header':header,'rows':rows}
    if not locked:
        return {},set()
    data['races']=[r for r in data['races'] if r['id'] not in locked]+[v['race'] for v in locked.values()]
    data['entries']=[e for e in data['entries'] if e['race_id'] not in locked]
    horses={h['id']:h for h in data['horses']}
    for rid,block in locked.items():
        for row in block['rows']:
            hid=(row[18].value if len(row)>18 else None) or by_horse_name.get(normalized(row[5].value))
            if hid in old_horses and normalized(row[5].value)!=normalized(old_horses[hid]['name']):
                hid=by_horse_name.get(normalized(row[5].value))
            if not hid:
                raise ValueError('Cannot identify a saved past-race horse; workbook was not changed')
            if hid not in horses:
                horse=deepcopy(old_horses.get(hid,{'id':hid,'name':row[5].value,'source_url':'Existing workbook'}))
                data['horses'].append(horse);horses[hid]=horse
            entry={'horse_id':hid,'race_id':rid}
            for col,field in ((2,'post'),(3,'result'),(4,'odds'),(7,'jockey')):
                entry[field]=row[col-1].value
            if str(entry.get('odds','')).upper()=='SCR':
                entry['scratched']=True
            data['entries'].append(entry)
    # Current/future assignments must not filter an archived past-race row.
    frozen_horses={e['horse_id'] for e in data['entries'] if e['race_id'] in locked}
    data['assignments']={h:r for h,r in data.get('assignments',{}).items() if h not in frozen_horses}
    live_horses={e['horse_id'] for e in data['entries'] if e['race_id'] not in locked}
    return locked,frozen_horses-live_horses


def restore_past_rows(old,new,locked,frozen_overage):
    old_sheet=old[next(s for s in old.sheetnames if s!='Overage')]
    new_sheet=new[old_sheet.title]
    for rid,block in locked.items():
        rows=[r for r in race_rows(new_sheet) if new_sheet.cell(r[0].row,20).value==rid]
        if len(rows)!=len(block['rows']):
            raise ValueError('Update would change a past-race field; workbook was not changed')
        pairs=[(block['header'],rows[0][0].row-1)]+[(a[0].row,b[0].row) for a,b in zip(block['rows'],rows)]
        for source_row,target_row in pairs:
            for col in range(1,21):
                if col<19 or old_sheet.cell(source_row,col).value is not None:
                    copy_cell(old_sheet.cell(source_row,col),new_sheet.cell(target_row,col))
            new_sheet.row_dimensions[target_row].height=old_sheet.row_dimensions[source_row].height
        old_summary=next((r[0].row for r in old_sheet if r[0].value=='RESULTS SUMMARY'),None)
        new_summary=next((r[0].row for r in new_sheet if r[0].value=='RESULTS SUMMARY'),None)
        if old_summary and new_summary:
            key=normalized(block['race']['name'])
            source=next((r for r in range(old_summary+1,old_sheet.max_row+1) if normalized(old_sheet.cell(r,1).value)==key),None)
            target=next((r for r in range(new_summary+1,new_sheet.max_row+1) if normalized(new_sheet.cell(r,1).value)==key),None)
            if source and target:
                for col in range(1,21):
                    copy_cell(old_sheet.cell(source,col),new_sheet.cell(target,col))
    for hid in frozen_overage:
        target=next((r for r in new['Overage'].iter_rows(min_row=2) if new['Overage'].cell(r[0].row,19).value==hid),None)
        source=next((r for r in old['Overage'].iter_rows(min_row=2) if old['Overage'].cell(r[0].row,19).value==hid or
                     (target and normalized(r[5].value)==normalized(target[5].value))),None)
        if source and target:
            for col in range(1,21):
                if col<19 or old['Overage'].cell(source[0].row,col).value is not None:
                    copy_cell(old['Overage'].cell(source[0].row,col),new['Overage'].cell(target[0].row,col))


def merge_research(data,previous):
    result=deepcopy(data)
    if not previous or previous.get('year')!=result['year']:
        return result
    prior_races={r['id']:r for r in previous.get('races',[])}
    for race in result.get('races',[]):
        prior=prior_races.get(race['id'])
        if prior and race.get('number') is None and prior.get('number') is not None and race['date']==prior['date'] and normalized(race['name'])==normalized(prior['name']):
            for field in ('number','scheduled_at','post_time_et','number_source_url','number_retrieved_at'):
                if field in prior:race[field]=prior[field]
    old={h['id']:h for h in previous['horses']}
    fields=('grandfathers','great_grandfathers','pedigree_ancestors','pedigree_branches',
            'famous_ancestor_evidence','other_ancestors','date_of_birth','color','father','dam',
            'maternal_grandsire','identity_source','identity_method')
    for horse in result['horses']:
        prior=old.get(horse['id'])
        if not prior or normalized(prior['name'])!=normalized(horse['name']):
            continue
        if any(horse.get(f) not in (None,'','--') and prior.get(f) not in (None,'','--') and
               normalized(horse[f])!=normalized(prior[f]) for f in ('father','dam','date_of_birth')):
            continue
        for field in fields:
            if not horse.get(field) or horse.get(field)=='--':
                if prior.get(field) and prior[field]!='--':
                    horse[field]=deepcopy(prior[field])
                    if field in prior.get('field_sources',{}):
                        horse.setdefault('field_sources',{})[field]=prior['field_sources'][field]
        if not horse.get('jockey') and prior.get('jockey_status')=='confirmed':
            for field in ('jockey','jockey_status','jockey_retrieved_at'):
                if prior.get(field):
                    horse[field]=prior[field]
            if prior.get('field_sources',{}).get('jockey'):
                horse.setdefault('field_sources',{})['jockey']=prior['field_sources']['jockey']
    return result


def race_rows(sheet):
    stop=next((r[0].row for r in sheet if r[0].value=='RESULTS SUMMARY'),sheet.max_row+1)
    name_col=next(c.column-1 for c in sheet[1] if c.value=='Name')
    return [r for r in sheet.iter_rows(min_row=2,max_row=stop-1) if r[name_col].value]


def capture(book,data,previous):
    """Read manual input before rebuilding. IDs are preferred; names migrate old files."""
    races={normalized(r['name']):r['id'] for r in data['races']}
    horses={normalized(h['name']):h['id'] for h in data['horses']}
    if previous:
        races.update({normalized(r['name']):r['id'] for r in previous['races']})
        horses.update({normalized(h['name']):h['id'] for h in previous['horses']})
    horse_names={}
    race_names={}
    for records in (data,previous or data):
        for h in records['horses']:
            horse_names.setdefault(h['id'],set()).add(normalized(h['name']))
        for r in records['races']:
            race_names.setdefault(r['id'],set()).add(normalized(r['name']))
    saved={}
    for sn in (str(data['year']),'Overage'):
        if sn not in book:
            raise ValueError(f'Existing workbook is missing {sn}; it was not changed')
        sheet=book[sn]
        rows=race_rows(sheet) if sn!='Overage' else list(sheet.iter_rows(min_row=2))
        for row in rows:
            if not row[5].value:
                continue
            hid=row[18].value if len(row)>18 else None
            if hid and normalized(row[5].value) not in horse_names.get(hid,set()):
                hid=None  # Recover safely after a manual sort excluding hidden IDs.
            hid=hid or horses.get(normalized(row[5].value))
            rid=None if sn=='Overage' else (row[19].value if len(row)>19 else None) or races.get(normalized(row[0].value))
            if rid and normalized(row[0].value) not in race_names.get(rid,set()):
                rid=races.get(normalized(row[0].value))
            if not hid or (sn!='Overage' and not rid):
                if row[4].value is not None or row[2].value is not None:
                    raise ValueError(f'Cannot safely identify a row containing picks/results: {sn}!F{row[5].row}')
                continue
            key=(sn,hid,rid)
            if key in saved:
                raise ValueError('Duplicate saved horse/race identity; workbook was not changed')
            saved[key]={c:copy(row[c-1]) for c in (2,3,4,5)}
    return saved


def preserve_summary(old,new):
    old_header=next((r[0].row for r in old if r[0].value=='RESULTS SUMMARY'),None)
    new_header=next((r[0].row for r in new if r[0].value=='RESULTS SUMMARY'),None)
    if old_header is None or new_header is None:
        return
    old_rows={normalized(old.cell(r,1).value):r for r in range(old_header+1,old.max_row+1) if old.cell(r,1).value}
    for r in range(new_header+1,new.max_row+1):
        prior=old_rows.get(normalized(new.cell(r,1).value))
        if prior:
            for c in range(2,6):
                cell=old.cell(prior,c)
                # Generated totals are recreated with new row references.
                if cell.value is not None and cell.data_type!='f':
                    new.cell(r,c).value=cell.value


def upsert(template,data,output,previous=None,final=False,test_generation=False,as_of=None):
    data=deepcopy(data)
    output=Path(output)
    if data.get('demo'):
        raise ValueError('DEMO data cannot update the production yearly workbook')
    if output.resolve()==Path(template).resolve():
        raise ValueError('Output must differ from template')
    old=None
    fingerprint=None
    saved={}
    locked={}
    frozen_overage=set()
    if output.exists():
        fingerprint=hashlib.sha256(output.read_bytes()).hexdigest()
        old=load_workbook(output)
        if str(data['year']) not in old:
            old.close()
            raise ValueError('Existing workbook belongs to a different year')
        try:
            arrange_columns(old,legacy=True)
            locked,frozen_overage=freeze_past_races(data,old,previous,as_of or current_date())
            saved=capture(old,data,previous)
        except Exception:
            old.close()
            raise
    old_horses={h['id']:h for h in (previous or data)['horses']}
    old_races={r['id']:r for r in (previous or data)['races']}
    horse_ids={h['id'] for h in data['horses']}
    race_ids={r['id'] for r in data['races']}
    pairs={(e['horse_id'],e['race_id']) for e in data['entries']}
    for (sn,hid,rid),cells in saved.items():
        if sn=='Overage' and hid not in horse_ids and any(cells[c].value is not None for c in (3,5)):
            if hid not in old_horses:
                raise ValueError('Saved Overage pick has no previous research identity; workbook was not changed')
            data['horses'].append(deepcopy(old_horses[hid]));horse_ids.add(hid)
        if sn=='Overage' or (hid,rid) in pairs or not any(cells[c].value is not None for c in (3,5)):
            continue
        # A disappearing source row must not silently discard someone's pick/result.
        if hid not in old_horses or rid not in old_races:
            raise ValueError('Saved pick has no previous research identity; workbook was not changed')
        if hid not in horse_ids:
            data['horses'].append(deepcopy(old_horses[hid]));horse_ids.add(hid)
        if rid not in race_ids:
            data['races'].append(deepcopy(old_races[rid]));race_ids.add(rid)
        data['entries'].append({'horse_id':hid,'race_id':rid,'retained_manual_row':True})
        pairs.add((hid,rid))
    for entry in data['entries']:
        if entry['race_id'] in locked:
            continue
        if entry.get('scratched') or str(entry.get('post','')).upper()=='SCR':
            entry['odds']='SCR'
            prior=saved.get((str(data['year']),entry['horse_id'],entry['race_id']))
            if str(entry.get('post','')).upper()=='SCR' and prior and str(prior[2].value).isdigit():
                entry['post']=prior[2].value
    # Explicit withdrawal notices also cover horses removed from the live cards.
    by_horse={h['id']:h for h in data['horses']}
    by_race={r['id']:r for r in data['races']}
    for line in data.get('withdrawals',[]):
        if ' has withdrawn from the ' not in line:
            continue
        name,race=line.split(' has withdrawn from the ',1)
        race=race.split(' (AE')[0]
        for entry in data['entries']:
            if entry['race_id'] in locked:
                continue
            if normalized(by_horse[entry['horse_id']]['name'])==normalized(name) and normalized(by_race[entry['race_id']]['name'])==normalized(race):
                entry.update(scratched=True,odds='SCR')
    prepare(data,final)
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=output.parent,prefix='.updating-') as directory:
            temporary=Path(directory)/output.name
            count=generate(template,data,temporary,final,test_generation,_legacy_layout=True)
            book=load_workbook(temporary)
            restored=set()
            for sn in (str(data['year']),'Overage'):
                sheet=book[sn]
                rows=race_rows(sheet) if sn!='Overage' else list(sheet.iter_rows(min_row=2))
                for row in rows:
                    hid=row[18].value if len(row)>18 else None
                    rid=None if sn=='Overage' else row[19].value
                    prior=saved.get((sn,hid,rid))
                    if not prior:
                        continue
                    restored.add((sn,hid,rid))
                    for col in (3,5):
                        source=prior[col]
                        if source.value is not None:
                            cell=sheet.cell(row[0].row,col)
                            cell.value=Translator(source.value,origin=source.coordinate).translate_formula(cell.coordinate) if source.data_type=='f' else source.value
                            if col==5:
                                cell.font=copy(source.font);cell.fill=copy(source.fill)
                    for col in (2,4):
                        cell=sheet.cell(row[0].row,col)
                        # Missing source data must not erase the last known post/odds.
                        if cell.value is None:
                            cell.value=prior[col].value
                if old and sn!='Overage':
                    preserve_summary(old[sn],sheet)
            if old and locked:
                restore_past_rows(old,book,locked,frozen_overage)
            if any(key not in restored and any(cells[c].value is not None for c in (3,5)) for key,cells in saved.items()):
                book.close()
                raise ValueError('Update would hide a saved pick/result; workbook was not changed')
            arrange_columns(book)
            fit_columns(book[str(data['year'])],book['Overage'])
            book.save(temporary);book.close()
            if old:
                old.close();old=None
            if fingerprint is not None:
                if not output.exists() or hashlib.sha256(output.read_bytes()).hexdigest()!=fingerprint:
                    raise ValueError('Workbook changed during update; rerun to preserve the latest edits')
                os.replace(temporary,output)
            else:
                # Exclusive creation prevents overwriting a concurrent first run.
                with output.open('xb') as stream:
                    stream.write(temporary.read_bytes())
    finally:
        if old:
            old.close()
    data.setdefault('collection_report',{})['yearly_update']={'file':str(output),'updated_existing':fingerprint is not None,
        'displayed_race_entries':count,'picks_preserved':sum(cells[5].value is not None for cells in saved.values()),
        'past_races_preserved':[{'id':rid,'name':b['race']['name'],'date':b['race']['date']} for rid,b in locked.items()],
        'date_guard_timezone':'America/Los_Angeles'}
    return data,count


def save_state(data,root=Path('data')):
    for folder,value in [('state',data),('reports',data.get('collection_report',{}))]:
        target=Path(root)/folder/f'{data["year"]}.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=target.parent,delete=False,suffix='.tmp') as stream:
            json.dump(value,stream,indent=2,ensure_ascii=False)
            temporary=Path(stream.name)
        os.replace(temporary,target)
