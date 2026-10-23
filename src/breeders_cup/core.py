"""Validated source records and race-assignment rules, independent of Excel."""
from collections import Counter
from datetime import date, datetime
import re

FIELDS = ('post', 'result', 'odds', 'pick', 'name', 'jockey', 'trainer',
          'color', 'last_previous_race', 'father', 'grandfathers',
          'great_grandfathers', 'other_ancestors', 'date_of_birth')


def key(value):
    return re.sub(r'\s+', ' ', str(value).strip()).casefold()


def famous_ancestors(horse, watchlist):
    """Return unique watchlist names actually present in the supplied pedigree.

    `pedigree_ancestors` is a flat list of ancestor names from the source, including
    deeper generations. No substring matching or speculative bloodline inference.
    """
    names = horse.get('pedigree_ancestors', [])
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        raise ValueError('pedigree_ancestors must be a list of names')
    names = list(names)
    for field in ('father', 'grandfathers', 'great_grandfathers'):
        value = horse.get(field)
        if value:
            names.extend(value.split(';'))
    from .pedigree import normalized
    observed = {normalized(n) for n in names if n.strip()}
    matches = {}
    for name in watchlist:
        if name.strip() and normalized(name) in observed:
            matches.setdefault(normalized(name),name.strip())
    return '; '.join(matches[k] for k in sorted(matches))


def post_order(entry, horse):
    """Numeric posts first, then AE, SCR, and unassigned entries alphabetically."""
    post = entry.get('post', horse.get('post'))
    value = str(post).strip().upper()
    if re.fullmatch(r'[1-9][0-9]*', value):
        group, number = 0, int(value)
    elif value == 'AE':
        group, number = 1, 0
    elif value in ('SCR', 'SCRATCHED'):
        group, number = 2, 0
    elif post is None or value == '':
        group, number = 3, 0
    else:
        raise ValueError(f'Unsupported post position: {post!r}')
    return group, number, key(horse['name']), entry['horse_id']


def prepare(data, final=False):
    year = data['year']
    if type(year) is not int or not 2000 <= year <= 2100:
        raise ValueError('year must be an integer between 2000 and 2100')
    races = data.get('races', [])
    race_ids, positions = set(), set()
    for race in races:
        rid = race['id']
        when = date.fromisoformat(race['date'])
        number = race['number']
        if not isinstance(rid, str) or not rid.strip() or rid in race_ids:
            raise ValueError('Race IDs must be unique nonblank strings')
        if not str(race['name']).strip():
            raise ValueError('Race name is required')
        if when.year != year or when.weekday() not in (4, 5):
            raise ValueError('Race date must be Friday or Saturday in the requested year')
        if number is None:
            scheduled = datetime.fromisoformat(race['scheduled_at'])
            if scheduled.tzinfo is None or scheduled.year != year:
                raise ValueError('Missing race number requires a timezone-aware schedule')
            position = (when, scheduled)
        else:
            position = (when, number)
        if (number is not None and (type(number) is not int or number < 1)) or position in positions:
            raise ValueError('Race numbers must be positive and unique within each day')
        if key(race['name']) in ('classic', "breeders' cup classic", 'breeders cup classic') and when.weekday() != 5:
            raise ValueError('The Classic must be Saturday')
        if not race.get('source_url'):
            raise ValueError('Each race needs a schedule source_url')
        race_ids.add(rid)
        positions.add(position)
    horses, entry_ids = {}, set()
    for horse in data['horses']:
        hid = horse['id']
        if not isinstance(hid, str) or not hid.strip() or hid in horses or not horse['name'].strip():
            raise ValueError('Horse IDs must be unique nonblank strings; names are required')
        if not horse.get('source_url'):
            raise ValueError('Each horse needs a source_url')
        if horse.get('date_of_birth') and date.fromisoformat(horse['date_of_birth']) > date(year, 12, 31):
            raise ValueError('Horse birth date is after the event year')
        horses[hid] = horse
    entries = data.get('entries', [])
    for entry in entries:
        pair = (entry['horse_id'], entry['race_id'])
        if pair[0] not in horses or pair[1] not in race_ids or pair in entry_ids:
            raise ValueError('Unknown horse/race or duplicate horse/race entry')
        entry_ids.add(pair)
    assignments = data.get('assignments', {})
    for hid, rid in assignments.items():
        if (hid, rid) not in entry_ids:
            raise ValueError('Assignment must match an existing horse/race entry')
    counts = Counter(e['horse_id'] for e in entries)
    if final:
        unresolved = [hid for hid in horses if counts[hid] == 0 or
                      (counts[hid] > 1 and hid not in assignments)]
        if unresolved:
            raise ValueError('Final race assignment required for: ' + ', '.join(unresolved))
    selected = [e for e in entries if e['horse_id'] not in assignments or assignments[e['horse_id']] == e['race_id']]
    # In contender mode all potential entries remain. Explicit assignments remove other entries.
    if races and any(r['number'] is None for r in races) and not all(r.get('scheduled_at') for r in races):
        raise ValueError('All races need scheduled_at when any race number is unknown')
    return sorted(races, key=lambda r: (r['date'], r.get('scheduled_at') or '', r['number'] or 0)), horses, selected


def last_race_before(history, event_date):
    """Select the latest completed start strictly before the target race date."""
    cutoff = date.fromisoformat(event_date)
    eligible = [r for r in history if date.fromisoformat(r['date']) < cutoff
                and r.get('status', 'completed') == 'completed']
    return max(eligible, key=lambda r: r['date']) if eligible else None
