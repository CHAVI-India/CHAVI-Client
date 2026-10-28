"""Smoke test for the date-shift refactor (run before the refactor lands).

Simulates the planned pipeline exactly:
  1. candidate spans from shape regexes (month-name tokens validated,
     parse validated BEFORE the span is recorded — an invalid candidate
     must not swallow a real date in dedup)
  2. strict gate for search_dates long-tail surfaces
  3. parse via dateparser: ordered date_formats list, then DMY settings
     fallback; PREFER_DAY_OF_MONTH='first' / PREFER_MONTH_OF_YEAR='first'
  4. shift by N days, emit DD/MM/YYYY with any trailing time kept verbatim

Run: venv/bin/python scripts/dateparser_smoke_test.py
"""

import re
from datetime import timedelta

from dateparser import parse as dp_parse
from dateparser.search import search_dates

# ---------------------------------------------------------------- settings
PREFER = {'PREFER_DAY_OF_MONTH': 'first', 'PREFER_MONTH_OF_YEAR': 'first',
          'RETURN_AS_TIMEZONE_AWARE': False}
DMY = dict(PREFER, DATE_ORDER='DMY')

DATE_FORMATS = [
    # day-first numeric (clinical / en-GB convention)
    '%d/%m/%Y', '%d/%m/%y',
    '%d.%m.%Y', '%d.%m.%y',
    '%d-%m-%Y', '%d-%m-%y',
    # year-first (ISO)
    '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d',
    # day + month name + year
    '%d %b %Y', '%d %b %y', '%d %B %Y', '%d %B %y',
    '%d %b, %Y', '%d %b, %y', '%d %B, %Y', '%d %B, %y',
    # month name + day + year
    '%b %d %Y', '%b %d %y', '%B %d %Y', '%B %d %y',
    '%b %d, %Y', '%B %d, %Y',
    # month name + day (no year -> current year)
    '%b %d', '%B %d',
    # month name + year (no day -> 1st)
    '%b %Y', '%B %Y', '%b %y', '%B %y',
    # day + month name (no year -> current year)
    '%d %b', '%d %B',
]

# ---------------------------------------------------------------- parsing
_MONTH_NAMES = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11,
    'dec': 12,
}


def month_number(token):
    t = token.lower()
    if t in _MONTH_NAMES:
        return _MONTH_NAMES[t]
    if len(t) >= 3:
        for name, num in _MONTH_NAMES.items():
            if t.startswith(name):
                return num
    return None


def parse_date_span(surface):
    # Require an explicit date component (year token or month name).
    # This rejects pure time-of-day ('14:30'), durations ('3 days') and
    # relative expressions at the parse entry itself — dateparser would
    # otherwise resolve them against *now*. A two-digit year only counts
    # inside a 3-token date with date separators (never a clock '09:15').
    if any(month_number(w) for w in re.findall(r"[A-Za-z']+", surface)):
        pass
    elif re.search(r'\b\d{4}\b', surface):
        pass
    elif re.search(r'\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2}\b', surface):
        pass
    elif re.search(r'\b\d{2}[/.-]\d{1,2}[/.-]\d{1,4}\b', surface):
        pass
    else:
        return None
    parsed = dp_parse(surface, date_formats=DATE_FORMATS,
                      languages=['en'], settings=PREFER)
    if parsed is None:
        parsed = dp_parse(surface, languages=['en'], settings=DMY)
    return parsed


def is_single_component(surface):
    """A bare year '1985', day '27' or month 'Oct' — shifting would
    fabricate the missing parts, so it is left untouched."""
    if re.fullmatch(r'\d{1,4}', surface):
        return True
    if re.fullmatch(r"[A-Za-z']{3,9}", surface):
        return month_number(surface) is not None
    return False


def is_shiftable_surface(surface):
    """Strict gate for long-tail (search_dates) surfaces: a real month
    name, no other words besides 'of', and a year token."""
    bare = re.sub(r'\d+\s*(?:st|nd|rd|th)', ' ', surface)
    words = [w.lower().strip("'") for w in re.findall(r"[A-Za-z']+", bare)]
    if not any(month_number(w) for w in words):
        return False
    if any(w != 'of' and month_number(w) is None for w in words):
        return False
    if not re.search(r'\d{4}', surface) and not re.search(r'\b\d{2}\b', bare):
        return False
    return True


TIME_SUFFIX_RE = re.compile(
    r'[,;]?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm]\.?)?$')


def shifted_date_text(surface, shift_days):
    stripped = surface.strip()
    if is_single_component(stripped):
        return None
    m = TIME_SUFFIX_RE.search(stripped)
    time_part = ''
    date_part = stripped
    if m:
        date_part, time_part = stripped[:m.start()].rstrip(), stripped[m.start():]
    parsed = parse_date_span(date_part)
    if parsed is None:
        return None
    return (parsed + timedelta(days=shift_days)).strftime('%d/%m/%Y') + time_part


# ------------------------------------------------------- candidate shapes
# (regex, group index of the month-name token, or None for numeric shapes)
SHAPES = [
    (re.compile(r'\b(\d{1,4})([/.-])(\d{1,2})\2(\d{1,4})\b'), None),
    (re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\s+'
                r'(\d{4}|\d{2})\b'), 2),
    (re.compile(r'\b([A-Za-z]{3,9})(,)?\s+(\d{1,2})(,)?\s+(\d{4}|\d{2})\b'),
     1),
    (re.compile(r'\b([A-Za-z]{3,9})\s+(\d{4}|\d{2})\b'), 1),
    (re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\b'), 2),
]


def shift_document(text, shift_days):
    spans = {}
    for rx, month_group in SHAPES:
        for m in rx.finditer(text):
            surface = m.group(0)
            start, end = m.span()
            if start in spans and spans[start][0] - start >= end - start:
                continue
            if month_group is not None and \
                    month_number(m.group(month_group)) is None:
                continue
            parsed = parse_date_span(surface)
            if parsed is None:
                continue
            spans[start] = (end, surface)
    # long-tail recall
    try:
        hits = search_dates(text, languages=['en'], settings=DMY,
                            strategy='ngram')
    except Exception:
        hits = []
    for raw_surface, _ in hits or []:
        tm = TIME_SUFFIX_RE.search(raw_surface)
        if tm:
            raw_surface = raw_surface[:tm.start()].rstrip(',;')
        if not raw_surface.strip() or not is_shiftable_surface(raw_surface):
            continue
        pos = text.find(raw_surface)
        while pos != -1:
            e = pos + len(raw_surface)
            if not any(pos < ee and e > ss for ss, (ee, *_r) in spans.items()):
                if parse_date_span(raw_surface) is not None:
                    spans[pos] = (e, raw_surface)
            pos = text.find(raw_surface, e)
    ordered = sorted(spans.items(), key=lambda kv: (kv[0], -(kv[1][0] - kv[0])))
    kept = []
    for start, span in ordered:
        if not kept or start >= kept[-1][1][0]:
            kept.append((start, span))
    out = text
    for start, (end, surface) in reversed(kept):
        new_surface = shifted_date_text(surface, shift_days)
        if new_surface is None:
            continue
        out = out[:start] + new_surface + out[end:]
    return out


# ------------------------------------------------------------------ main
def main():
    print('=== 1. per-surface parsing (date_formats, then DMY settings) ===')
    cases = [
        ('27/10/26', '2026-10-27 00:00:00'),
        ('27.10.2026', '2026-10-27 00:00:00'),
        ('27-10-26', '2026-10-27 00:00:00'),
        ('2026-10-27', '2026-10-27 00:00:00'),
        ('2026/10/27', '2026-10-27 00:00:00'),
        ('10.27.26', '2026-10-27 00:00:00'),   # US-style month-first
        ('10/27/26', '2026-10-27 00:00:00'),
        ('1/2/2026', '2026-02-01 00:00:00'),    # ambiguous -> day-first
        ('99/03/25', '1999-03-25 00:00:00'),
        ('27 Oct 26', '2026-10-27 00:00:00'),
        ('27 Oct 2026', '2026-10-27 00:00:00'),
        ('27 October 2026', '2026-10-27 00:00:00'),
        ('27th Oct 2026', '2026-10-27 00:00:00'),
        ('27th of October 2026', '2026-10-27 00:00:00'),
        ('Oct 27, 2026', '2026-10-27 00:00:00'),
        ('Oct 27 26', '2026-10-27 00:00:00'),
        ('October 2026', '2026-10-01 00:00:00'),
        ('Oct 26', '2026-10-26 00:00:00'),     # month + day (no year)
        ('27 Oct', '2026-10-27 00:00:00'),      # no year -> current year
        ('Oct', '2026-10-01 00:00:00'),
        ('1979', '1979-01-01 00:00:00'),
        ('27 Oct 26 14:30', '2026-10-27 14:30:00'),
        ('27/10/2026 14:30', '2026-10-27 14:30:00'),
        ('27 Oct 26 14:30:10', '2026-10-27 14:30:10'),
        ('27 Oct 26, 2:30 pm', '2026-10-27 14:30:00'),
        ('27/10/26 2:30 PM', '2026-10-27 14:30:00'),
        ('2026-10-27 09:15:00', '2026-10-27 09:15:00'),
        ('3 days', None),                        # relative -> reject
        ('2 weeks', None),                       # relative -> reject
        ('09:15:00', None),                      # time only -> reject
        ('14:30', None),                         # time only -> reject
        ('2:30 pm', None),                       # 12h time only -> reject
        ('visit 05', None),                      # not a date
        # invalid dates must NOT parse to a fake valid date
        ('31/02/2024', None),
        ('32/13/2024', None),
    ]
    fails = 0
    for surface, want in cases:
        got = parse_date_span(surface)
        got_s = str(got) if got else None
        ok = got_s == want
        fails += not ok
        print(f"  {'OK ' if ok else 'FAIL'} {surface:<24} -> {got_s}"
              f"{'   (want ' + str(want) + ')' if not ok else ''}")

    print()
    print('=== 2. false-positive guards (gate rejects / parse is None) ===')
    bad = ['56 years', '10 years', '3 days', '2 weeks', 'next Tuesday',
           'in 2 weeks after the 27/10/26', '09:15:00', '14:30', '1:2',
           'Grade III', 'A3', 'MR/24/012817', 'DOB', 'March', 'October',
           '1 month', '2 hours', '15 minutes']
    for s in bad:
        gated = is_shiftable_surface(s)
        parsed = None if gated is False else parse_date_span(s)
        safe = not gated or parsed is None
        fails += not safe
        print(f"  {'OK ' if safe else 'FAIL'} {s:<28} gated={gated!s:<5} "
              f"parsed={parsed}")

    print()
    print('=== 3. shifted emission (DD/MM/YYYY, time kept verbatim) ===')
    emit_cases = [
        ('27/10/26', 7, '03/11/2026'),
        ('27.10.2026', 7, '03/11/2026'),
        ('2026-10-27', -7, '20/10/2026'),
        ('27 Oct 26', 7, '03/11/2026'),
        ('16th of September 2026', 5, '21/09/2026'),
        ('Oct 27, 2026', -2, '25/10/2026'),
        ('27 Oct 26 14:30', 7, '03/11/2026 14:30'),
        ('27/10/2026 14:30', -7, '20/10/2026 14:30'),
        ('27 Oct 26, 2:30 pm', 10, '06/11/2026, 2:30 pm'),
        ('15/12/2024', 10, '25/12/2024'),
        ('28/12/2024', 10, '07/01/2025'),
        ('31/02/2024', 10, None),               # invalid -> untouched
        ('next Tuesday', 10, None),             # relative -> untouched
        ('1985', 10, None),                     # bare year -> untouched
        ('27', 10, None),                       # bare day -> untouched
        ('Oct', 10, None),                      # bare month -> untouched
    ]
    for surface, shift, want in emit_cases:
        got = shifted_date_text(surface, shift)
        ok = got == want
        fails += not ok
        print(f"  {'OK ' if ok else 'FAIL'} {surface:<24} +{shift:<4} -> "
              f"{got!r}{'   (want ' + repr(want) + ')' if not ok else ''}")

    print()
    print('=== 4. whole-document pass (one shift per document) ===')
    docs = [
        # (text, shift, must_be_gone, must_stay)
        ('DOB: 12/03/1985. Last visit 05.01.24 09:15. Next review Oct 2026. '
         'Fever for 3 days, follow up in 2 weeks.',
         10,
         ['12/03/1985', '05.01.24', 'Oct 2026'],
         ['09:15', '2 weeks', '3 days']),
        ('Admitted on 27 Oct 26 14:30 for observation. Born 3rd of '
         'September 1979, discharged 2024-11-02. MR/24/012817.',
         -5,
         ['27 Oct 26', '3rd of September 1979', '2024-11-02'],
         ['MR/24/012817', '14:30']),
        ('SINCE 27 Oct, the symptoms persist. Age 56 years, hypertension '
         'for 10 years.',
         3,
         ['27 Oct'],
         ['Age 56 years', '10 years']),
    ]
    for text, shift, gone, stay in docs:
        out = shift_document(text, shift)
        print(f'  in : {text}')
        print(f'  out: {out}')
        for c in gone:
            ok = c not in out
            fails += not ok
            print(f"    {'OK GONE ' if ok else 'FAIL GONE '} {c!r}")
        for c in stay:
            ok = c in out
            fails += not ok
            print(f"    {'OK KEPT ' if ok else 'FAIL KEPT '} {c!r}")
        print()

    print(f"{'FAILURES: %d' % fails if fails else 'ALL CHECKS PASSED'}")


if __name__ == '__main__':
    main()
