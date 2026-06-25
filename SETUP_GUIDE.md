# DISCO POA&M — Setup Guide
## window.storage persistence + GitHub Actions Jira sync

---

## Part 1 — window.storage (already active)

The `Digital_Binder_Tier1_POAM_v3.html` artifact now persists checklist
state automatically when opened inside Claude.ai. No setup required.

**What it does:**
- Every checkbox toggle is saved to `window.storage` under the key
  `disco-poam-checklist-v3`.
- On page load the saved state is restored before the progress bars
  calculate — so M1 and M2 pre-checked items (DISCO-1, 10, 14, 15, 16)
  remain correct alongside anything the team has checked off.
- A small green "✓ Progress saved" toast appears bottom-right on every
  successful write.

**Limitation:** `window.storage` persists only within the Claude.ai
artifact environment. If you download the HTML and open it standalone
in a browser, state will not persist (browser localStorage would be
needed for that use case — ask Claude to add it if required).

---

## Part 2 — GitHub Actions Jira Sync

### What you need before starting

- [ ] A GitHub repository (can be private) where the POA&M HTML lives
- [ ] Your Atlassian account email (the one you log into Jira with)
- [ ] A Jira API token (generate one at the link below — takes 60 seconds)

**Generate API token:**
https://id.atlassian.com/manage-profile/security/api-tokens
→ "Create API token" → label it "DISCO POA&M sync" → copy the value

---

### Step 1 — Add files to your repository

Place these three files in your repository root:

```
your-repo/
├── Digital_Binder_Tier1_POAM_v3.html   ← the POA&M artifact
├── sync_poam.py                          ← Jira sync script
└── .github/
    └── workflows/
        └── sync-poam.yml                ← Actions workflow
```

Commit and push to `main`.

---

### Step 2 — Add repository secrets

In GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name  | Value                          |
|-------------|-------------------------------|
| `JIRA_EMAIL` | your Atlassian account email  |
| `JIRA_TOKEN` | the API token you generated   |

Do **not** add the token to any file — only as a secret.

---

### Step 3 — (Optional) Set repository variables

If your workspace URL, project key, or filename differ from the defaults,
add them under **Settings → Secrets and variables → Actions → Variables**:

| Variable name  | Default value                           |
|---------------|----------------------------------------|
| `JIRA_BASE`   | `https://fiveforty.atlassian.net`      |
| `JIRA_PROJECT`| `DISCO`                                |
| `POAM_FILE`   | `Digital_Binder_Tier1_POAM_v3.html`   |

---

### Step 4 — Enable GitHub Pages (optional)

If you want the POA&M to be accessible at a URL after each sync:

**Settings → Pages → Source → GitHub Actions**

The workflow will deploy automatically after each successful sync.
The URL will be: `https://<your-org>.github.io/<your-repo>/`

---

### Step 5 — Test the pipeline

Run it manually before waiting for the schedule:

**Actions tab → "Sync POA&M from Jira" → Run workflow → Run workflow**

Tick "Dry run" on the first run to confirm it connects to Jira
without writing any changes. Review the output in the Actions log,
then run again without dry run to commit the first live sync.

---

### What the sync updates

Each run refreshes three sections of the HTML:

1. **Team Checklists tab** — the `✓` prefix on checklist items is
   toggled to match the current Done/Not-Done status in Jira. Items
   resolved since the last sync gain `✓`; items re-opened lose it.

2. **Status Report tab** — issue counts (Done / In Progress / Peer Review /
   To Do), the in-progress table with assignees and staleness flags,
   and the reporting date are all rewritten from the live API response.

3. **Header chip** — the "X Child Issues" count updates to match
   the current total.

Sprint-plan narrative, monthly objectives, milestone cards, and the
Gantt are **not** modified by the sync script — those reflect deliberate
planning decisions and should be updated by asking Claude to revise them.

---

### Re-using this pattern for future POA&M versions

When Claude generates a revised HTML artifact, the sync script works
against any version as long as:
- The `const MONTHS=[` JS array is present (checklist sync)
- The `<!-- IN PROGRESS -->` HTML comment is present (status report sync)
- Issue keys appear in the format `DISCO-XX` inside quoted strings

Claude can regenerate `sync_poam.py` for a new artifact version by
asking: *"Update sync_poam.py to match the new HTML structure."*

---

### Adjusting the schedule

Edit `.github/workflows/sync-poam.yml`, line 24:

```yaml
- cron: '0 6 * * *'   # 06:00 UTC daily
```

Common alternatives:
- `'0 6 * * 1-5'`  — weekdays only
- `'0 0,6,12 * * *'` — three times daily (midnight, 6am, noon UTC)
- Remove the `schedule:` block entirely to disable automatic runs
  and rely on manual dispatch only.
