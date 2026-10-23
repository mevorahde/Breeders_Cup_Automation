"""Create a new workbook from the user's 2024 styles; never overwrite an output."""
from copy import copy
from datetime import date
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment
from .core import FIELDS, prepare, famous_ancestors, post_order
from .famous_horses import FAMOUS_HORSES

HEADERS = ['BC Race', 'Post', 'Result', 'Odds', 'Pick', 'Name', 'Jockey',
           'Trainer', 'Color', 'Last Previous Race', 'Father', 'Grandfather(s)',
           'Great Grandfather(s)', 'Other Ancestors', 'Date of Birth']


def text(cell, value):
    # Scraped text must remain text, including formula-looking horse names.
    cell.value = value
    if isinstance(value, str):
        cell.data_type = 's'


def styled_row(target, row, values, source, source_row):
    target.row_dimensions[row].height = source.row_dimensions[source_row].height
    for col, value in enumerate(values, 1):
        cell = target.cell(row, col)
        original = source.cell(source_row, min(col, 14))
        cell.font = copy(original.font)
        cell.fill = copy(original.fill)
        cell.border = copy(original.border)
        cell.number_format = original.number_format
        cell.protection = copy(original.protection)
        cell.alignment = Alignment(horizontal='center' if col <= 5 or col in (9, 15) else 'left',
                                   vertical='center', wrap_text=False)
        text(cell, value)
        if isinstance(value, date):
            cell.number_format = 'mm/dd/yyyy'
    target.row_dimensions[row].height = source.row_dimensions[source_row].height or 12


def results_summary(sheet, row, races, source):
    header = next((r[0].row for r in source.iter_rows(min_col=1,max_col=1)
                   if r[0].value=='RESULTS SUMMARY'),None)
    if header is None:
        raise ValueError('Template is missing RESULTS SUMMARY')
    def copy_style(cell,original):
        for attr in ('font','fill','border','alignment','protection'):
            setattr(cell,attr,copy(getattr(original,attr)))
        cell.number_format=original.number_format
    def copy_summary_row(destination, template_row, values):
        for col in range(1,16):
            cell=sheet.cell(destination,col)
            original=source.cell(template_row,col)
            copy_style(cell,original)
            if col<=len(values):
                value=values[col-1]
                if isinstance(value,str) and value.startswith('='):
                    cell.value=value
                else:
                    text(cell,value)
        sheet.row_dimensions[destination].height=12
    # Keep the template's black separator above the summary.
    copy_summary_row(row,header-1,[])
    for cell in sheet[row]:
        cell.fill=copy(source.cell(header-1,1).fill)
    row+=1
    copy_summary_row(row,header,['RESULTS SUMMARY','De','$','H','$','Win = $2'])
    first=row+1
    for i,race in enumerate(races):
        copy_summary_row(first+i,header+1,[race['name'],None,None,None,None,
            'Place = $1' if i==0 else 'Low Total = $10' if i==1 else None])
        if i>1:
            copy_style(sheet.cell(first+i,6),source.cell(header+4,6))
    last=first+len(races)-1
    subtotal=last+1
    low=last+2
    final=last+3
    copy_summary_row(subtotal,header+15,['SubTotals'])
    copy_summary_row(low,header+16,['Low Total'])
    copy_summary_row(final,header+17,['Final Totals'])
    for col in ('C','E'):
        sheet[f'{col}{subtotal}']=f'=IF(COUNT({col}{first}:{col}{last})=0,"",SUM({col}{first}:{col}{last}))'
        sheet[f'{col}{final}']=f'=IF({col}{subtotal}="","",{col}{subtotal})'
    for col in ('B','D'):
        sheet[f'{col}{low}']=f'=IF(COUNT({col}{first}:{col}{last})=0,"",SUM({col}{first}:{col}{last}))'


def fit_columns(sheet,overage):
    """Save explicit fitted widths on both views, including restored manual input."""
    for col in range(1,16):
        widths=[]
        for target in (sheet,overage):
            for cells in target.iter_rows(min_col=col,max_col=col):
                value=cells[0].value
                display='' if cells[0].data_type=='f' else value.strftime('%m/%d/%Y') if isinstance(value,date) else str(value or '')
                widths.append(sum(0.45 if c in " ilI.,:;'|" else 1.25 if c in 'MW@' else 0.9 for c in display)+2)
        letter=sheet.cell(1,col).column_letter
        width=min(255,max(sheet.column_dimensions[letter].width,max(widths,default=0)))
        for target in (sheet,overage):
            target.column_dimensions[letter].width=width
            target.column_dimensions[letter].bestFit=True


def generate(template, data, output, final=False, test_generation=False):
    if final and test_generation:
        raise ValueError('Test generation cannot be combined with final race assignments')
    races, horses, entries = prepare(data, final)
    output = Path(output)
    if output.resolve() == Path(template).resolve():
        raise ValueError('Output must differ from template')
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    original = load_workbook(template)
    source = original['2024']
    if [source.cell(1, c).value for c in range(1, 15)] != HEADERS[:14]:
        raise ValueError('Template 2024 headers differ from expected layout')
    result = Workbook()
    if data.get('demo'):
        result.properties.title=f'Breeders Cup {data["year"]} - DEMO'
        result.properties.description=data['demo']['notice']
    sheet = result.active
    sheet.title = str(data['year'])
    overage = result.create_sheet('Overage')
    for target in (sheet, overage):
        for col in 'ABCDEFGHIJKLMN':
            target.column_dimensions[col].width = source.column_dimensions[col].width
        target.column_dimensions['O'].width = 14
        target.sheet_view.zoomScale = 100
        target.freeze_panes = 'F2'
        target.sheet_properties.pageSetUpPr = copy(source.sheet_properties.pageSetUpPr)
        target.page_setup = copy(source.page_setup)
        target.print_title_rows = '1:1'
        styled_row(target, 1, HEADERS, source, 1)
        if data.get('demo'):
            text(target['A1'],'BC Race (DEMO)')
    row = 2
    displayed_entries=0
    for race in races:
        matching = sorted((e for e in entries if e['race_id'] == race['id']),
                          key=lambda e: post_order(e, horses[e['horse_id']]))
        if test_generation:
            matching=matching[:13]
        displayed_entries+=len(matching)
        when = date.fromisoformat(race['date'])
        label = f"Race {race['number']}" if race['number'] is not None else 'Race # pending'
        styled_row(sheet, row, [when.strftime('%A %m-%d-%Y'), label] + [None]*13, source, 4)
        row += 1
        for entry in matching:
            horse = horses[entry['horse_id']]
            merged = {**horse, **{k:v for k,v in entry.items() if k in FIELDS and k != 'name'}}
            merged['pick'] = None  # DE and H are personal picks, entered manually in Excel.
            merged['other_ancestors'] = famous_ancestors(horse, FAMOUS_HORSES)
            values = [race['name']] + [merged.get(f) for f in FIELDS]
            if merged.get('date_of_birth'):
                values[-1] = date.fromisoformat(merged['date_of_birth'])
            styled_row(sheet, row, values, source, 5)
            text(sheet.cell(row,19),horse['id'])
            text(sheet.cell(row,20),race['id'])
            row += 1
    if races:
        results_summary(sheet,row,races,source)
    # Overage is this year's complete research registry, one row per horse,
    # independent of whether race nominations or a schedule have been published.
    import json
    race_names = {r['id']: r['name'] for r in races}
    for r, (hid, horse) in enumerate(sorted(horses.items(), key=lambda item:
                                          (key_name(item[1]['name']), item[0])), 2):
        active = [e for e in entries if e['horse_id'] == hid]
        merged = dict(horse)
        if len(active) == 1:
            merged.update({k:v for k,v in active[0].items() if k in FIELDS and k != 'name'})
        else:
            # Posts, odds, results and engagements belong to a specific race.
            for field in ('post', 'result', 'odds'):
                merged[field] = None
            if active and all(e.get('scratched') or str(e.get('post','')).upper()=='SCR' for e in active):
                merged['odds']='SCR'
            riders={e.get('jockey') or horse.get('jockey') for e in active}
            riders.discard(None)
            merged['jockey']=next(iter(riders)) if len(riders)==1 else None
        merged['pick'] = None
        merged['other_ancestors'] = famous_ancestors(horse, FAMOUS_HORSES)
        values = ['; '.join(race_names[e['race_id']] for e in active) or None] + [merged.get(f) for f in FIELDS]
        if merged.get('date_of_birth'):
            values[-1] = date.fromisoformat(merged['date_of_birth'])
        styled_row(overage, r, values, source, 5)
        text(overage.cell(r,19),hid)
        for col, value in enumerate((horse['source_url'], horse.get('retrieved_at'),
                                     json.dumps(horse.get('field_sources', {}))), 16):
            text(overage.cell(r, col), value)
    for col, label in enumerate(('Source URL', 'Retrieved at', 'Field sources (JSON)'), 16):
        cell = overage.cell(1, col)
        text(cell, label)
        cell.font = copy(overage['A1'].font)
        cell.fill = copy(overage['A1'].fill)
    for col in ('P', 'Q', 'R'):
        overage.column_dimensions[col].width = 40
        overage.column_dimensions[col].hidden = True
    overage.auto_filter.ref = f'A1:T{max(1, len(horses)+1)}'
    for target in (sheet, overage):
        text(target['S1'],'Horse ID')
        text(target['T1'],'Race ID')
        target.column_dimensions['S'].hidden=True
        target.column_dimensions['T'].hidden=True
        target.print_area = f'A1:O{target.max_row}'
    # Excel's bestFit flag does not calculate a stored width. Estimate the text
    # width at the retained nine-point template font and save explicit widths.
    fit_columns(sheet,overage)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against another run creating the same output.
    with output.open('xb') as stream:
        result.save(stream)
    original.close()
    return displayed_entries


def key_name(name):
    return name.strip().casefold()
