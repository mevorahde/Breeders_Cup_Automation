import argparse
import json
import sys
from pathlib import Path
from .core import prepare
from .workbook import generate
from .sources import SOURCES, fetch, extract_table
from .collector import collect, repair_incomplete_identities
from .pedigree import enrich
from .netkeiba import enrich_remaining
from .pedigreequery import enrich_query
from .famous import annotate_famous
from .jockeys import refresh_jockeys
from .demo import prepare_demo
from .updates import current_year,merge_research,upsert,save_state


def main():
    parser = argparse.ArgumentParser(description="Breeders' Cup Excel automation")
    commands = parser.add_subparsers(dest='command', required=True)
    update=commands.add_parser('update',help='Create or refresh the single yearly workbook, preserving picks')
    update.add_argument('--year',type=int,default=current_year())
    update.add_argument('--generated-dir',type=Path,default=Path('generated'))
    update.add_argument('--cache',type=Path,default=Path('data/cache/pedigree'))
    update.add_argument('--template',type=Path,default=Path('templates/2024 Breeders Cup Final.xlsx'))
    demo=commands.add_parser('demo-build',help='Create a 13-horse-per-race DEMO with sample posts and random odds')
    demo.add_argument('--data',type=Path,required=True)
    demo.add_argument('--output',type=Path)
    demo.add_argument('--seed',type=int,default=2026)
    demo.add_argument('--cache',type=Path,default=Path('data/cache/pedigree'))
    demo.add_argument('--template',type=Path,default=Path('templates/2024 Breeders Cup Final.xlsx'))
    live = commands.add_parser('collect-build', help='Fetch official contenders and generate a yearly workbook')
    live.add_argument('--year', type=int, default=current_year())
    live.add_argument('--pedigree', action='store_true', help='Enrich pedigrees using the public fallback database')
    live.add_argument('--cache', type=Path, default=Path('data/cache/pedigree'))
    live.add_argument('--output', type=Path)
    live.add_argument('--template', type=Path, default=Path('templates/2024 Breeders Cup Final.xlsx'))
    secondary = commands.add_parser('enrich-build', help='Fill missing pedigrees in saved data and generate a new workbook')
    secondary.add_argument('--data', type=Path, required=True)
    secondary.add_argument('--output', type=Path)
    secondary.add_argument('--cache', type=Path, default=Path('data/cache/pedigree'))
    secondary.add_argument('--template', type=Path, default=Path('templates/2024 Breeders Cup Final.xlsx'))
    for sub in (live,secondary):
        sub.add_argument('--jockeys',action='store_true',help='Refresh confirmed Breeders Cup jockeys from official declarations and explicit current-year announcements')
        sub.add_argument('--test',action='store_true',help='Limit the annual sheet to 13 horses per race; retain all Overage horses')
    for command in ('validate', 'build'):
        sub = commands.add_parser(command)
        sub.add_argument('--data', type=Path, required=True)
        sub.add_argument('--final', action='store_true', help='Require single-race assignment for cross-entries')
        if command == 'build':
            sub.add_argument('--cache',type=Path,default=Path('data/cache/pedigree'),help='Existing pedigree cache for deeper famous-ancestor links')
            sub.add_argument('--test',action='store_true',help='Limit the annual sheet to 13 horses per race; retain all Overage horses')
            sub.add_argument('--template', type=Path, default=Path('templates/2024 Breeders Cup Final.xlsx'))
            sub.add_argument('--output', type=Path, help='Default: generated/Breeders Cup YEAR.xlsx')
    commands.add_parser('check-sources', help='Probe HTTP access; does not claim parser coverage')
    sub = commands.add_parser('extract-table', help='Extract an explicitly mapped saved HTML table to JSON')
    sub.add_argument('--html', type=Path, required=True)
    sub.add_argument('--selector', required=True)
    sub.add_argument('--columns', type=Path, required=True, help='JSON: source column label -> normalized field')
    sub.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[1:] or ['update'])
    try:
        if args.command=='update':
            state=Path('data/state')/f'{args.year}.json'
            previous=json.loads(state.read_text(encoding='utf8')) if state.exists() else None
            data=merge_research(repair_incomplete_identities(collect(args.year)),previous)
            data=enrich(data,args.cache)
            data=enrich_remaining(data,args.cache)
            data=enrich_query(data,args.cache)
            data=refresh_jockeys(annotate_famous(data,args.cache))
            output=args.generated_dir/f'Breeders Cup {args.year}.xlsx'
            data,count=upsert(args.template,data,output,previous=previous)
            save_state(data)
            print(f'Saved {output}: {count} race rows; existing picks and results preserved')
            report=data.get('collection_report',{})
            stage=report.get('source_stage','unknown')
            posts=report.get('declared_post_positions',0)
            riders=report.get('jockeys',{}).get('confirmed',sum(bool(h.get('jockey')) for h in data['horses']))
            odds=report.get('morning_line_odds',0)
            print(f'Official feed: {stage}; declared post positions: {posts}; confirmed jockeys: {riders}; morning-line odds: {odds}')
            if stage=='pre-entries':
                print('NOTICE: Official final declarations are not available in the fetched feed. Pre-entry positions are not imported as draw positions.')
            print(f'Research: data/state/{args.year}.json; report: data/reports/{args.year}.json')
            return 0
        if args.command=='demo-build':
            data=json.loads(args.data.read_text(encoding='utf8'))
            output=args.output or Path('generated')/f'Breeders Cup {data["year"]} - DEMO.xlsx'
            data_path=output.with_suffix('.data.json')
            report_path=output.with_suffix('.report.json')
            if any(p.exists() for p in (output,data_path,report_path)):
                raise FileExistsError('Output or sidecar already exists; choose a new filename')
            data=prepare_demo(annotate_famous(data,args.cache),args.seed)
            count=generate(args.template,data,output,test_generation=True)
            data_path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf8')
            report_path.write_text(json.dumps(data['collection_report'],indent=2),encoding='utf8')
            print(f'Created {output}: {count} DEMO race entries; {len(data["horses"])} Overage horses')
            print(data['demo']['notice'])
            return 0
        if args.command in ('collect-build', 'enrich-build'):
            data = collect(args.year) if args.command == 'collect-build' else json.loads(args.data.read_text(encoding='utf8'))
            output = args.output or Path('generated') / f'Breeders Cup {data["year"]}.xlsx'
            state=Path('data/state')/f'{data["year"]}.json'
            previous=json.loads(state.read_text(encoding='utf8')) if state.exists() else None
            data=merge_research(data,previous)
            prepare(data)
            if args.command == 'collect-build' and args.pedigree:
                data = enrich(data, args.cache)
                data['collection_report']['limitations'] = [s for s in data['collection_report']['limitations']
                                                          if 'Deeper pedigree enrichment is pending' not in s]
                data['collection_report']['limitations'].append('Pedigree fallback coverage is partial; see pedigree unresolved records.')
            if args.command == 'enrich-build' or args.pedigree:
                data = repair_incomplete_identities(data)
                data = enrich_remaining(data, args.cache)
                data = enrich_query(data, args.cache)
                if data['collection_report'].get('pedigree_complete'):
                    limitations = data['collection_report'].get('limitations',[])
                    data['collection_report']['limitations'] = [s for s in limitations
                        if 'Pedigree fallback coverage is partial' not in s and
                           'Deeper pedigree enrichment is pending' not in s]
            data = annotate_famous(data,args.cache)
            if args.jockeys:
                data = refresh_jockeys(data)
            data,count = upsert(args.template, data, output,previous=previous,test_generation=args.test)
            data['collection_report']['workbook_generation'] = {'test_generation':args.test,
                'max_horses_per_race':13 if args.test else None,'displayed_race_entries':count,
                'overage_horses':len(data['horses'])}
            save_state(data)
            print(f'Created {output}: {len(data["horses"])} horses; {count} possible race entries')
            print(f'Coverage and limitations: data/reports/{data["year"]}.json')
            for name, status in data['collection_report'].get('sources', {}).items():
                print(f'{name}: {status}')
            return 0
        if args.command == 'check-sources':
            failed = False
            for name, url in SOURCES.items():
                try:
                    html = fetch(url)
                    print(f'{name}: HTTP accessible ({len(html)} characters); parsing UNVERIFIED')
                except Exception as exc:
                    failed = True
                    print(f'{name}: UNAVAILABLE: {exc}')
            return int(failed)
        if args.command == 'extract-table':
            records = extract_table(args.html.read_text(encoding='utf-8'), args.selector,
                                    json.loads(args.columns.read_text(encoding='utf-8')))
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(records, stream, indent=2)
            print(f'Extracted {len(records)} records; normalize IDs and merge into event data before build')
            return 0
        data = json.loads(args.data.read_text(encoding='utf-8'))
        if args.command == 'validate':
            races, horses, entries = prepare(data, args.final)
            print(f'Valid: {len(races)} races, {len(horses)} horses, {len(entries)} active entries')
        else:
            output = args.output or Path('generated') / f"Breeders Cup {data['year']}.xlsx"
            data = annotate_famous(data,args.cache)
            state=Path('data/state')/f'{data["year"]}.json'
            previous=json.loads(state.read_text(encoding='utf8')) if state.exists() else None
            data,count = upsert(args.template, data, output,previous=previous,final=args.final,test_generation=args.test)
            save_state(data)
            print(f'Created {output}: {count} race entries; {len(data["horses"])} horses in Overage')
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
