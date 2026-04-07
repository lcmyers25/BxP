"""
inject_data.py — BxP Data Injector
====================================
Reads your two CSV files and bakes the data into bxp_template.html,
producing a fully self-contained bxp.html that needs no network access.

USAGE:
  1. Place this script in the same folder as bxp_template.html
  2. Export your two Google Sheets tabs as CSV files and put them
     in the same folder:
       - master_data.csv       (your Sample Master Data Sheet)
       - presentations.csv     (your BxP Presentations List)
  3. Run:  python3 inject_data.py
  4. Open bxp.html in your browser — done.
"""

import csv
import json
import re
import sys
from pathlib import Path

# ── FILE PATHS ───────────────────────────────────────────────────────────────
TEMPLATE   = Path("bxp_template.html")
OUTPUT     = Path("bxp.html")
MASTER_CSV = Path("master_data.csv")
PRES_CSV   = Path("presentations.csv")

# ── COLUMN NAMES ─────────────────────────────────────────────────────────────
COL_ID        = "ID"
COL_PRES_NAME = "PRESENTATION NAME"
COL_TOPICS    = "PRESENTATION DEFINITION"
COL_BROAD     = "BROAD DIFFERENTIAL"
COL_SPECIFIC  = "SPECIFIC DIFFERENTIAL"
COL_MECH      = "MECHANISM EXPLANATION"
COL_RESOURCES = "RESOURCES"
COL_NOTES     = "SPECIAL NOTES"
COL_PATIENT   = "Mechanistic Explanation for Patients"
COL_POP       = "Patient Population (Adult or Pediatric)"

COL_PDEF_NAME = "PRESENTATION NAME"
COL_PDEF_DEF  = "PRESENTATION DEFINITION"

# ── HELPERS ──────────────────────────────────────────────────────────────────
def clean(s):
    """Strip whitespace and normalise line endings."""
    return s.strip().replace('\r\n', '\n').replace('\r', '\n') if s else ''

def clean_inline(s):
    """Collapse ALL newlines and extra whitespace to a single space.
    Use for fields that must stay on one line inside JS strings."""
    return ' '.join(s.split()) if s else ''

def clean_def(s):
    """For single-line fields like presentation definitions."""
    return ' '.join(s.split()) if s else ''

def clean_multiline(s):
    """Keep paragraph breaks (double newline → sentinel) but strip everything else.
    The sentinel survives JSON encoding and can be split in JS if needed."""
    if not s:
        return ''
    # normalise line endings first
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    # collapse runs of 3+ newlines to double newline
    s = re.sub(r'\n{3,}', '\n\n', s)
    # replace double newlines with a safe sentinel that won't break JS
    s = s.replace('\n\n', ' | ')
    # replace remaining single newlines with a space
    s = re.sub(r' *\n', ' ', s)
    return s.strip().rstrip()

def read_csv(path):
    """Read CSV, stripping BOM and whitespace from headers."""
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            rows.append({k.strip(): clean(v) for k, v in row.items()})
    return rows

# ── LOAD PRESENTATIONS LIST ──────────────────────────────────────────────────
print(f"Reading {PRES_CSV}...")
try:
    pres_rows = read_csv(PRES_CSV)
except FileNotFoundError:
    print(f"ERROR: {PRES_CSV} not found.")
    sys.exit(1)

pres_defs = {}
for row in pres_rows:
    name = row.get(COL_PDEF_NAME, '').strip()
    defn = row.get(COL_PDEF_DEF, '')
    if name:
        pres_defs[name] = clean_def(defn)

print(f"  Loaded {len(pres_defs)} presentation definitions.")

# ── LOAD MASTER DATA ─────────────────────────────────────────────────────────
print(f"Reading {MASTER_CSV}...")
try:
    master_rows = read_csv(MASTER_CSV)
except FileNotFoundError:
    print(f"ERROR: {MASTER_CSV} not found.")
    sys.exit(1)

sample = master_rows[0] if master_rows else {}
missing = [c for c in [COL_ID, COL_PRES_NAME, COL_BROAD] if c not in sample]
if missing:
    print(f"\nERROR: These expected columns were not found in {MASTER_CSV}:")
    for m in missing:
        print(f"  '{m}'")
    print("\nActual columns found:")
    for h in sample.keys():
        print(f"  '{h}'")
    sys.exit(1)

master = []
skipped = 0
for row in master_rows:
    rid  = row.get(COL_ID, '').strip()
    pn   = row.get(COL_PRES_NAME, '').strip()
    bd   = clean_inline(row.get(COL_BROAD, ''))
    sd   = clean_inline(row.get(COL_SPECIFIC, ''))
    mech = clean_multiline(row.get(COL_MECH, ''))
    res  = clean_multiline(row.get(COL_RESOURCES, ''))
    notes= clean_multiline(row.get(COL_NOTES, ''))
    pat  = clean_multiline(row.get(COL_PATIENT, ''))
    pop  = clean_inline(row.get(COL_POP, ''))
    topics = clean_inline(row.get(COL_TOPICS, ''))

    if not rid and not pn:
        skipped += 1
        continue

    master.append({
        "id":        rid,
        "pn":        pn,
        "bd":        bd,
        "sd":        sd,
        "mech":      mech,
        "resources": res,
        "notes":     notes,
        "patient":   pat,
        "pop":       pop,
        "topics":    topics,
    })

print(f"  Loaded {len(master)} master entries ({skipped} blank rows skipped).")

matched = sum(1 for r in master if r['pn'] in pres_defs)
print(f"  Presentation definitions matched: {matched} entries.")

# ── GENERATE JS (ensure_ascii=False, separators keep it compact) ─────────────
pres_defs_js = "const PRES_DEFS = " + json.dumps(
    pres_defs, ensure_ascii=False, separators=(',', ':')) + ";"

master_js = "const MASTER = " + json.dumps(
    master, ensure_ascii=False, separators=(',', ':')) + ";"

# Sanity check — should be exactly 1 line each
assert '\n' not in pres_defs_js, "PRES_DEFS still contains newlines!"
assert '\n' not in master_js,    "MASTER still contains newlines!"
print("  ✅ JS sanity check passed — no embedded newlines.")

# ── INJECT INTO TEMPLATE ─────────────────────────────────────────────────────
print(f"Reading template {TEMPLATE}...")
try:
    html = TEMPLATE.read_text(encoding='utf-8')
except FileNotFoundError:
    print(f"ERROR: {TEMPLATE} not found.")
    sys.exit(1)

def replace_block(html, start_marker, end_marker, new_content):
    pattern = re.compile(
        re.escape(start_marker) + r'.*?' + re.escape(end_marker),
        re.DOTALL
    )
    replacement = f"{start_marker}\n{new_content}\n{end_marker}"
    result, count = pattern.subn(replacement, html)
    if count == 0:
        print(f"WARNING: Marker '{start_marker}' not found in template.")
    return result

html = replace_block(html,
    '// @@PRES_DEFS_START@@', '// @@PRES_DEFS_END@@',
    pres_defs_js)

html = replace_block(html,
    '// @@MASTER_DATA_START@@', '// @@MASTER_DATA_END@@',
    master_js)

# ── WRITE OUTPUT ─────────────────────────────────────────────────────────────
OUTPUT.write_text(html, encoding='utf-8')
size_kb = OUTPUT.stat().st_size / 1024
print(f"\n✅  Done! Output written to {OUTPUT}  ({size_kb:.0f} KB)")
print(f"    {len(master)} entries · {len(pres_defs)} presentation definitions")
print(f"\nOpen bxp.html in Chrome to test it locally.")
