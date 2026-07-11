# -*- coding: utf-8 -*-  
from __future__ import annotations  
  
import argparse  
import importlib  
import json  
import shlex  
import sys  
import traceback  
from cmd import Cmd  
from datetime import datetime  
from pathlib import Path  
from urllib.parse import urlparse, urlunparse  
  
ROOT_DIR = Path(__file__).resolve().parent  
COMMITTEES_DIR = ROOT_DIR / 'committees'  
VALID_CHAMBERS = ('house', 'senate')  
  
def normalize_link(url):  
    url = (url or '').strip()  
    if not url:  
        return ''  
    parsed = urlparse(url)  
    scheme = (parsed.scheme or 'https').lower()  
    netloc = parsed.netloc.lower().replace('www.', '')  
    path = (parsed.path or '').rstrip('/')  
    return urlunparse((scheme, netloc, path, '', parsed.query, ''))  
  
def discover_committees(chamber):  
    chamber = (chamber or '').strip().lower()  
    if chamber not in VALID_CHAMBERS:  
        raise ValueError(f'Unsupported chamber: {chamber}')  
    chamber_dir = COMMITTEES_DIR / chamber  
    if not chamber_dir.exists():  
        raise FileNotFoundError(f'Missing directory: {chamber_dir}')  
    modules = {}  
    for file in sorted(chamber_dir.glob('*.py')):  
        if file.stem.startswith('_'):  
            continue  
        modules[file.stem] = f'committees.{chamber}.{file.stem}'  
    return modules  
  
def call_runner(run_committee):  
    try:  
        items = run_committee(existing_links=set())  
    except TypeError as exc:  
        if "unexpected keyword argument 'existing_links'" in str(exc):  
            items = run_committee()  
        else:  
            raise  
    if not isinstance(items, list):  
        raise TypeError('run_committee should return list')  
    return items  
  
def load_runner(chamber, committee):  
    committee = (committee or '').strip().lower()  
    modules = discover_committees(chamber)  
    if committee not in modules:  
        available = ', '.join(sorted(modules.keys()))  
        raise KeyError(f"Unknown committee '{committee}' in {chamber}. Available: {available}")  
    module = importlib.import_module(modules[committee])  
    runner = getattr(module, 'run_committee', None)  
    if not callable(runner):  
        raise AttributeError(f"{modules[committee]} has no callable run_committee")  
    return runner  
  
def fetch_committee(chamber, committee):  
    return call_runner(load_runner(chamber, committee)) 
  
def dedupe_items(items):  
    seen = set()  
    deduped = []  
    for item in items:  
        if not isinstance(item, dict):  
            continue  
        key = (  
            normalize_link(item.get('link') or ''),  
            (item.get('sort_date') or item.get('date') or '').strip(),  
            (item.get('committee_en') or item.get('committee_cn') or '').strip().lower(),  
            (item.get('title') or '').strip().lower(),  
        )  
        if key in seen:  
            continue  
        seen.add(key)  
        deduped.append(item)  
    return deduped  
  
def sort_items(items):  
    return sorted(  
        items,  
        key=lambda row: (  
            row.get('sort_date') or row.get('date') or '',  
            row.get('committee_en') or row.get('committee_cn') or '',  
            row.get('title') or '',  
        ),  
        reverse=True,  
    )  
  
def fetch_target(target):  
    target = (target or '').strip().lower()  
    if target not in ('house', 'senate', 'all'):  
        raise ValueError('target only supports house, senate, all')  
    targets = VALID_CHAMBERS if target == 'all' else (target,)  
    all_items = []  
    all_errors = {}  
    for chamber in targets:  
        modules = discover_committees(chamber)  
        chamber_errors = {}  
        print(f'\n[{chamber.upper()}] committees: {len(modules)}')  
        for committee in sorted(modules.keys()):  
            print(f'\n========== {chamber}.{committee} ==========')  
            try:  
                items = fetch_committee(chamber, committee)  
                print(f'grabbed: {len(items)}')  
                all_items.extend(items)  
            except Exception as exc:  
                chamber_errors[committee] = str(exc)  
                print(f'grab failed: {exc}')  
        all_errors[chamber] = chamber_errors  
    return dedupe_items(sort_items(all_items)), all_errors  
  
def list_committees(target):  
    target = (target or 'all').strip().lower()  
    if target not in ('house', 'senate', 'all'):  
        raise ValueError('list supports house, senate, all')  
    targets = VALID_CHAMBERS if target == 'all' else (target,)  
    for chamber in targets:  
        modules = discover_committees(chamber)  
        print(f'\n{chamber.upper()} ({len(modules)})')  
        for name in sorted(modules.keys()):  
            print(f'  - {name}')  
  
def save_json(path, items):  
    output = Path(path).expanduser().resolve()  
    output.parent.mkdir(parents=True, exist_ok=True)  
    output.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')  
    return output  
  
def show_items(items, limit):  
    if not items:  
        print('no data')  
        return  
    limit = max(1, int(limit))  
    print(f'\nshow {min(limit, len(items))} / {len(items)}')  
    for idx, item in enumerate(items[:limit], start=1):  
        sort_date = item.get('sort_date') or item.get('date') or 'unknown-date'  
        chamber = item.get('chamber') or 'unknown-chamber'  
        committee = item.get('committee_cn') or item.get('committee_en') or 'unknown-committee'  
        category = item.get('category') or item.get('category_en') or 'unknown-category'  
        title = item.get('title') or 'untitled'  
        link = item.get('link') or ''  
        print(f'{idx:02d}. [{sort_date}] {chamber} - {committee}')  
        print(f'    {category} - {title}')  
        if link:  
            print(f'    {link}') 
  
def run_sync(target):  
    target = (target or '').strip().lower()  
    if target not in ('house', 'senate', 'all'):  
        raise ValueError('sync target only supports house, senate, all')  
    if target in ('house', 'all'):  
        print('\n[sync] run_house.main()')  
        run_house = importlib.import_module('run_house')  
        run_house.main()  
    if target in ('senate', 'all'):  
        print('\n[sync] run_senate.main()')  
        run_senate = importlib.import_module('run_senate')  
        run_senate.main()  
  
def print_error(exc):  
    print(f'\nERROR: {exc}')  
    traceback.print_exc()  
  
def parse_options(tokens, default_limit=10):  
    target = ''  
    output = ''  
    limit = default_limit  
    rest = list(tokens)  
    if rest and not rest[0].startswith('--'):  
        target = rest[0].lower()  
        rest = rest[1:]  
    idx = 0  
    while idx != len(rest):  
        token = rest[idx]  
        if token == '--limit':  
            if idx + 1 == len(rest):  
                raise ValueError('missing value for --limit')  
            limit = int(rest[idx + 1])  
            idx = idx + 2  
            continue  
        if token == '--output':  
            if idx + 1 == len(rest):  
                raise ValueError('missing value for --output')  
            output = rest[idx + 1]  
            idx = idx + 2  
            continue  
        raise ValueError(f'unknown arg: {token}')  
    return target, limit, output  
  
class CongressShell(Cmd):  
    prompt = 'fincept-congress: '  
  
    def __init__(self):  
        super().__init__()  
        house_count = len(discover_committees('house'))  
        senate_count = len(discover_committees('senate'))  
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  
        self.intro = (  
            '\n========================================================\n'  
            ' Fincept Congress Terminal (US Committees Only)\n'  
            f' Time: {now}\n'  
            f' House: {house_count} committees  Senate: {senate_count} committees\n'  
            '========================================================\n'  
            'commands:\n'  
            '  list [house/senate/all]\n'  
            '  fetch house_or_senate committee [--limit N] [--output FILE]\n'  
            '  run [house/senate/all] [--limit N] [--output FILE]\n'  
            '  sync [house/senate/all]\n'  
            '  exit\n'  
        ) 
  
    def do_list(self, arg):  
        target = (arg.strip() or 'all').lower()  
        try:  
            list_committees(target)  
        except Exception as exc:  
            print_error(exc)  
  
    def do_fetch(self, arg):  
        tokens = shlex.split(arg)  
        if len(tokens) == 0 or len(tokens) == 1:  
            print('usage: fetch house_or_senate committee [--limit N] [--output FILE]')  
            return  
        chamber = tokens[0].lower()  
        committee = tokens[1].lower()  
        try:  
            _, limit, output = parse_options(tokens[2:], default_limit=10)  
            items = sort_items(dedupe_items(fetch_committee(chamber, committee)))  
            print(f'\nDone: {chamber}.{committee} items {len(items)}')  
            show_items(items, limit)  
            if output:  
                saved = save_json(output, items)  
                print(f'saved to {saved}')  
        except Exception as exc:  
            print_error(exc)  
  
    def do_run(self, arg):  
        tokens = shlex.split(arg)  
        target, limit, output = parse_options(tokens, default_limit=10)  
        if not target:  
            target = 'all'  
        try:  
            items, errors = fetch_target(target)  
            print(f'\nDone total items after dedupe: {len(items)}')  
            show_items(items, limit)  
            if output:  
                saved = save_json(output, items)  
                print(f'saved to {saved}')  
            total_errors = 0  
            for chamber_name in errors:  
                total_errors = total_errors + len(errors[chamber_name])  
            if total_errors:  
                print('\nfailed committees:')  
                for chamber_name in errors:  
                    for committee_name in errors[chamber_name]:  
                        print(f"  - {chamber_name}.{committee_name}: {errors[chamber_name][committee_name]}")  
        except Exception as exc:  
            print_error(exc)  
  
    def do_sync(self, arg):  
        target = (arg.strip() or 'all').lower()  
        try:  
            run_sync(target)  
            print('sync done')  
        except Exception as exc:  
            print_error(exc)  
  
    def do_exit(self, arg):  
        print('bye')  
        return True  
  
    do_quit = do_exit  
  
    def do_EOF(self, arg):  
        print()  
        return self.do_exit(arg)  
  
def build_parser():  
    parser = argparse.ArgumentParser(  
        prog='congress_terminal',  
        description='Fincept style US Congress committee terminal',  
    )  
    sub = parser.add_subparsers(dest='command')  
  
    p_list = sub.add_parser('list', help='list committees')  
    p_list.add_argument('--chamber', choices=['house', 'senate', 'all'], default='all')  
  
    p_fetch = sub.add_parser('fetch', help='fetch one committee')  
    p_fetch.add_argument('--chamber', choices=['house', 'senate'], required=True)  
    p_fetch.add_argument('--committee', required=True)  
    p_fetch.add_argument('--limit', type=int, default=10)  
    p_fetch.add_argument('--output', default='')  
  
    p_run = sub.add_parser('run', help='fetch house senate or all')  
    p_run.add_argument('--target', choices=['house', 'senate', 'all'], default='all')  
    p_run.add_argument('--limit', type=int, default=10)  
    p_run.add_argument('--output', default='')  
  
    p_sync = sub.add_parser('sync', help='run existing notion sync')  
    p_sync.add_argument('--target', choices=['house', 'senate', 'all'], default='all')  
  
    sub.add_parser('shell', help='start interactive shell')  
    return parser 
  
def handle_cli(args):  
    if args.command == 'list':  
        list_committees(args.chamber)  
        return 0  
  
    if args.command == 'fetch':  
        items = sort_items(dedupe_items(fetch_committee(args.chamber, args.committee)))  
        print(f'Done: {args.chamber}.{args.committee} items {len(items)}')  
        show_items(items, args.limit)  
        if args.output:  
            saved = save_json(args.output, items)  
            print(f'saved to {saved}')  
        return 0  
  
    if args.command == 'run':  
        items, errors = fetch_target(args.target)  
        print(f'Done total items after dedupe: {len(items)}')  
        show_items(items, args.limit)  
        if args.output:  
            saved = save_json(args.output, items)  
            print(f'saved to {saved}')  
        total_errors = 0  
        for chamber_name in errors:  
            total_errors = total_errors + len(errors[chamber_name])  
        if total_errors:  
            print('failed committees:')  
            for chamber_name in errors:  
                for committee_name in errors[chamber_name]:  
                    print(f"  - {chamber_name}.{committee_name}: {errors[chamber_name][committee_name]}")  
        return 0  
  
    if args.command == 'sync':  
        run_sync(args.target)  
        print('sync done')  
        return 0  
  
    shell = CongressShell()  
    shell.cmdloop()  
    return 0  
  
def main():  
    parser = build_parser()  
    args = parser.parse_args()  
    try:  
        return handle_cli(args)  
    except Exception as exc:  
        print_error(exc)  
        return 1  
  
if __name__ == '__main__':  
    sys.exit(main()) 
