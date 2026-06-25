#!/usr/bin/env python3
"""
sync_poam.py — DISCO POA&M Jira Sync Script
============================================
Queries the Jira Cloud REST API for all DISCO project issues,
then updates three sections of the HTML artifact in-place:

  1. Checklist data (MONTHS array) — toggles the ✓ prefix on items
     whose DISCO key is now Done in Jira; removes ✓ from items that
     have been re-opened.

  2. Status Report tab — refreshes the reporting date, issue counts,
     and the In Progress / Peer Review table with current assignees
     and staleness flags.

  3. Header chips — updates the "X Child Issues" count.

Usage
-----
  # Set env vars (or use a .env file with python-dotenv):
  export JIRA_EMAIL="you@fiveforty.io"
  export JIRA_TOKEN="your-api-token"        # from id.atlassian.com
  export JIRA_BASE="https://fiveforty.atlassian.net"
  export POAM_FILE="Digital_Binder_Tier1_POAM_v3.html"

  python sync_poam.py

  # Or pass arguments directly:
  python sync_poam.py --email you@fiveforty.io --token TOKEN --file path/to/poam.html

Dependencies
------------
  pip install requests python-dateutil
"""

import os
import re
import sys
import json
import base64
import argparse
import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' not installed. Run: pip install requests")

try:
    from dateutil import parser as dateparser
    from dateutil.relativedelta import relativedelta
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False


# ── CLI / environment config ─────────────────────────────────────────

def get_config():
    p = argparse.ArgumentParser(description="Sync DISCO Jira data into the POA&M HTML.")
    p.add_argument("--email",  default=os.getenv("JIRA_EMAIL"),  help="Atlassian account email")
    p.add_argument("--token",  default=os.getenv("JIRA_TOKEN"),  help="Jira API token")
    p.add_argument("--base",   default=os.getenv("JIRA_BASE", "https://fiveforty.atlassian.net"))
    p.add_argument("--project",default=os.getenv("JIRA_PROJECT", "DISCO"))
    p.add_argument("--file",   default=os.getenv("POAM_FILE", "Digital_Binder_Tier1_POAM_v3.html"))
    p.add_argument("--dry-run",action="store_true", help="Print diff but do not write file")
    args = p.parse_args()

    if not args.email or not args.token:
        sys.exit(
            "ERROR: Jira credentials required.\n"
            "  Set JIRA_EMAIL and JIRA_TOKEN env vars, or pass --email / --token.\n"
            "  Get a token at: https://id.atlassian.com/manage-profile/security/api-tokens"
        )
    return args


# ── Jira API ─────────────────────────────────────────────────────────

def make_auth_header(email, token):
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def fetch_issues(base, project, headers):
    """Return list of all issues in the project via paginated JQL search."""
    issues = []
    start = 0
    page_size = 100
    jql = f"project = {project} ORDER BY key ASC"
    fields = "summary,status,assignee,updated,priority,issuetype,parent"

    while True:
        url = f"{base}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "fields": fields,
            "startAt": start,
            "maxResults": page_size,
        }
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code == 401:
            sys.exit("ERROR 401: Invalid credentials. Check your email and API token.")
        if resp.status_code == 403:
            sys.exit("ERROR 403: Forbidden. Verify the API token has read access to DISCO.")
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        start += len(batch)
        if start >= data.get("total", 0) or not batch:
            break

    print(f"  Fetched {len(issues)} issues from {project}")
    return issues


def parse_issues(issues):
    """
    Returns:
      status_map  : {key: 'Done'|'In Progress'|'Peer Review'|'To Do'|...}
      active_list : [{key, summary, assignee, status, updated_str, stale_days}]
                    for In Progress + Peer Review items only
      counts      : {done, in_progress, peer_review, to_do, total_children}
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    status_map = {}
    active = []
    counts = {"done": 0, "in_progress": 0, "peer_review": 0, "to_do": 0, "total_children": 0}

    for issue in issues:
        key   = issue["key"]
        fields = issue["fields"]
        itype  = fields.get("issuetype", {}).get("name", "")
        status = fields.get("status", {}).get("name", "To Do")
        summary = fields.get("summary", "")
        assignee_obj = fields.get("assignee") or {}
        assignee = assignee_obj.get("displayName", "Unassigned")
        updated_raw = fields.get("updated", "")

        # Parse updated timestamp
        stale_days = None
        updated_str = updated_raw[:10] if updated_raw else "—"
        if updated_raw and HAS_DATEUTIL:
            try:
                updated_dt = dateparser.parse(updated_raw)
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=datetime.timezone.utc)
                delta = now - updated_dt
                stale_days = delta.days
            except Exception:
                pass

        status_map[key] = status

        # Count only child issues (not epics)
        if itype != "Epic":
            counts["total_children"] += 1
            if status == "Done":
                counts["done"] += 1
            elif status == "In Progress":
                counts["in_progress"] += 1
            elif status == "Peer Review":
                counts["peer_review"] += 1
            else:
                counts["to_do"] += 1

        if status in ("In Progress", "Peer Review"):
            active.append({
                "key": key,
                "summary": summary,
                "assignee": assignee,
                "status": status,
                "updated": updated_str,
                "stale_days": stale_days,
            })

    return status_map, active, counts


# ── HTML patch helpers ────────────────────────────────────────────────

def toggle_done_prefix(item_str, is_done):
    """Add or remove the '✓ ' prefix based on Jira Done status."""
    has_check = item_str.startswith("'✓ ") or item_str.startswith('"✓ ')
    quote = item_str[0]  # ' or "
    inner = item_str[1:-1]  # strip outer quotes

    if is_done and not has_check:
        inner = "✓ " + inner
    elif not is_done and has_check:
        inner = inner[2:]  # strip '✓ '

    return f"{quote}{inner}{quote}"


def patch_months_array(html, status_map):
    """
    Walks every quoted string in the MONTHS array that contains a
    DISCO-XX reference and toggles the ✓ prefix to match Jira status.
    Returns patched html and count of changes made.
    """
    changes = 0

    # Match single-quoted strings containing DISCO-XX (inside the JS array)
    pattern = re.compile(r"('(?:[^'\\]|\\.)*DISCO-(\d+)(?:[^'\\]|\\.)*')")

    def replacer(m):
        nonlocal changes
        full = m.group(1)
        key  = f"DISCO-{m.group(2)}"
        status = status_map.get(key, "")
        is_done = (status == "Done")
        new_full = toggle_done_prefix(full, is_done)
        if new_full != full:
            changes += 1
            print(f"    {key}: {status!r} → {'added ✓' if is_done else 'removed ✓'}")
        return new_full

    # Only operate inside the MONTHS constant block
    months_start = html.find("const MONTHS=[")
    months_end   = html.find("];", months_start) + 2
    if months_start == -1:
        print("  WARNING: MONTHS array not found in HTML — checklist not updated")
        return html, 0

    before  = html[:months_start]
    months  = html[months_start:months_end]
    after   = html[months_end:]
    patched = pattern.sub(replacer, months)
    return before + patched + after, changes


def build_active_table(active):
    """Generate the HTML table rows for §4 In Progress / Peer Review."""
    rows = []
    for item in active:
        key   = item["key"]
        summ  = item["summary"]
        asgn  = item["assignee"]
        stat  = item["status"]
        upd   = item["updated"]
        sd    = item["stale_days"]

        if sd is None:
            stale_cell = '<span class="lgr lbl">—</span>'
        elif sd <= 2:
            stale_cell = '<span class="fresh">No</span>'
        else:
            stale_cell = f'<span class="stale">{sd} days</span>'

        jira_url = f"https://fiveforty.atlassian.net/browse/{key}"
        rows.append(
            f'      <tr>'
            f'<td><a href="{jira_url}" style="color:#185FA5;text-decoration:none">{key}</a></td>'
            f'<td>{summ}</td>'
            f'<td>{asgn}</td>'
            f'<td>{stat}</td>'
            f'<td>{upd}</td>'
            f'<td>{stale_cell}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def patch_status_report(html, active, counts, today_str):
    """
    Updates §2 metrics boxes, §4 in-progress table, and the
    report date in the sr-hdr. Returns patched html.
    """
    # ── Reporting date in sr-hdr ──────────────────────────────────
    html = re.sub(
        r'(<span class="edt" contenteditable="true">)'
        r'(DISCO Sprint \d+[^<]*)</span>',
        lambda m: m.group(1) + f"Jira sync · {today_str}</span>",
        html,
        count=1,
    )

    # ── Metrics: completed last 24h, active, blocked, high-priority ──
    # We detect "done in last 24h" conservatively as 0 unless we have
    # full timestamp data — teams can update manually as needed.
    active_count = counts["in_progress"] + counts["peer_review"]

    def replace_mbox_n(label, new_val, html_local):
        """Replace the number in the mbox whose label matches."""
        pattern = re.compile(
            r'(<div class="mbox-n"[^>]*>)\s*[\d/]+\s*(</div>\s*<div class="mbox-l">'
            + re.escape(label) + r'</div>)',
            re.DOTALL
        )
        return pattern.sub(lambda m: f'{m.group(1)}{new_val}{m.group(2)}', html_local)

    html = replace_mbox_n("Active (In Progress + Peer Review)", str(active_count), html)

    # ── Status distribution table ─────────────────────────────────
    dist_pattern = re.compile(
        r'(<tr><td>⬜ To Do[^<]*</td><td>)\d+(</td></tr>)'
    )
    html = dist_pattern.sub(lambda m: f"{m.group(1)}{counts['to_do']}{m.group(2)}", html)

    dist_ip = re.compile(r'(🔄 In Progress</td><td>)\d+(</td>)')
    html = dist_ip.sub(lambda m: f"{m.group(1)}{counts['in_progress']}{m.group(2)}", html)

    dist_pr = re.compile(r'(🔍 Peer Review</td><td>)\d+(</td>)')
    html = dist_pr.sub(lambda m: f"{m.group(1)}{counts['peer_review']}{m.group(2)}", html)

    dist_dn = re.compile(r'(✅ Done</td><td>)\d+(</td>)')
    html = dist_dn.sub(lambda m: f"{m.group(1)}{counts['done']}{m.group(2)}", html)

    # ── In Progress table (§4) ────────────────────────────────────
    table_pattern = re.compile(
        r'(<!-- IN PROGRESS -->.*?'
        r'<tr><th>Key</th><th>Summary</th>.*?</tr>)'
        r'(.*?)'
        r'(</table>\s*<div[^>]*Five of seven)',
        re.DOTALL
    )

    new_rows = build_active_table(active)
    stale_count = sum(1 for a in active if a["stale_days"] and a["stale_days"] > 3)
    note_text   = (
        f"    <div style=\"font-size:10px;color:#5f5e5a;margin-top:2px\">"
        f"{stale_count} of {len(active)} active items stale (&gt;3 days). "
        f"Synced from Jira on {today_str}.</div>"
    )

    def table_replacer(m):
        return m.group(1) + "\n" + new_rows + "\n    " + m.group(3)

    html_new = table_pattern.sub(table_replacer, html)
    if html_new == html:
        print("  NOTE: In-progress table regex did not match — table not updated.")
    else:
        html = html_new

    return html


def patch_header_chip(html, total_children):
    """Update the 'X Child Issues' chip in the page header."""
    html = re.sub(
        r'(\d+) Child Issues',
        f'{total_children} Child Issues',
        html,
        count=1
    )
    return html


# ── Main ─────────────────────────────────────────────────────────────

def main():
    cfg = get_config()
    poam_path = Path(cfg.file)

    if not poam_path.exists():
        sys.exit(f"ERROR: HTML file not found: {poam_path}")

    print(f"\n{'='*55}")
    print(f"  DISCO POA&M Jira Sync")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Source : {cfg.base}/jira/software/projects/{cfg.project}")
    print(f"  Target : {poam_path}")
    print(f"{'='*55}\n")

    headers = make_auth_header(cfg.email, cfg.token)

    print("Fetching issues...")
    issues = fetch_issues(cfg.base, cfg.project, headers)

    print("Parsing statuses...")
    status_map, active, counts = parse_issues(issues)

    print(f"\n  Done        : {counts['done']}")
    print(f"  In Progress : {counts['in_progress']}")
    print(f"  Peer Review : {counts['peer_review']}")
    print(f"  To Do       : {counts['to_do']}")
    print(f"  Total child : {counts['total_children']}\n")

    html = poam_path.read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()

    print("Patching MONTHS array (checklist Done status)...")
    html, chk_changes = patch_months_array(html, status_map)
    print(f"  {chk_changes} checklist items updated\n")

    print("Patching status report section...")
    html = patch_status_report(html, active, counts, today)

    print("Patching header chip...")
    html = patch_header_chip(html, counts["total_children"])

    if cfg.dry_run:
        print("\n[DRY RUN] No file written.")
    else:
        poam_path.write_text(html, encoding="utf-8")
        print(f"\n✓ {poam_path} updated successfully.")

    print(f"\n{'='*55}\n")


if __name__ == "__main__":
    main()
