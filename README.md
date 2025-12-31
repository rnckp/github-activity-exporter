# GitHub Activity Exporter and Analyzer

**Export and analyze your GitHub activity across organizations.**

[![Python](https://img.shields.io/badge/python-v3.13+-blue.svg)](https://github.com/rnckpa/github-activity-exporter)
![GitHub License](https://img.shields.io/github/license/rnckpa/github-activity-exporter)
[![GitHub Stars](https://img.shields.io/github/stars/rnckpa/github-activity-exporter.svg)](https://github.com/rnckpa/github-activity-exporter/stargazers)
<a href="https://github.com/astral-sh/ruff"><img alt="linting - Ruff" class="off-glb" loading="lazy" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>

## What It Does

1. `01_get_activity.py` — Fetches your GitHub activity via API and exports to CSV/JSON
2. `02_explore_activity.ipynb` — Jupyter notebook for visualizing and analyzing the data

### Activity Types Collected

| Kind            | Description                     |
| --------------- | ------------------------------- |
| `commits`       | Your commits (default branches) |
| `prs_opened`    | PRs you created                 |
| `prs_merged`    | PRs you merged                  |
| `prs_reviewed`  | PRs you reviewed                |
| `prs_commented` | PRs you commented on            |
| `issues_opened` | Issues you created              |
| `involves_me`   | Issues/PRs involving you        |

## Installation

```bash
git clone https://github.com/rnckpa/github-activity.git
cd github-activity

pip3 install uv
uv venv
uv sync
```

## GitHub Token Setup

1. Go to [GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)](https://github.com/settings/tokens)
2. Click **"Generate new token"**
3. Set name and expiration
4. **Required permissions:**

   - `repo` — Access repository data
   - `user -> read:user` — Read ALL user profile data

5. Copy the token

```bash
export GITHUB_TOKEN="github_pat_..."
```

## Usage

### Export Activity

```bash
# Default: rolling last 365 days, all orgs you're a member of
uv run 01_get_activity.py

# Custom date range
uv run 01_get_activity.py --from 2025-01-01 --to 2025-12-31

# Specific organization(s)
uv run 01_get_activity.py --org my-org --org another-org

# Custom output prefix
uv run 01_get_activity.py --out my_activity
```

**Output:** `github_activity_YYYY-MM-DD_YYYY-MM-DD.csv` and `.json`

### Analyze Activity

Open `02_explore_activity.ipynb` in Jupyter/VS Code. The notebook provides:

- Activity type distribution
- Top repositories by commits
- Monthly/weekly/hourly commit patterns
- Day-of-week heatmaps
- Commit message analysis
- Organization breakdown

## Troubleshooting

| Issue                     | Solution                                                                     |
| ------------------------- | ---------------------------------------------------------------------------- |
| `ERROR: set GITHUB_TOKEN` | Export your token: `export GITHUB_TOKEN="..."`                               |
| `403 Forbidden`           | Token lacks required permissions. Regenerate with `read:org` + `repo`        |
| `404 Not Found` on org    | You're not a member, or token doesn't have access to that org                |
| Rate limit hit            | Script auto-waits. For large exports, run during off-peak hours              |
| Empty results             | Check date range. Verify org membership with `gh api /user/memberships/orgs` |
| Missing commits           | Only default branch commits are indexed by GitHub Search API                 |

### Verify Token and Access

**Verify the token is being used and identify the login.**

Run these two calls and ensure you get your expected username back:

```bash
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/user | jq -r .login

curl -i -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/rate_limit | head
```

If `/user` doesn’t return your login, the script will search for the wrong user and likely get zero hits.

**Debug the org discovery (this is the most common “empty output” cause).**

Try both endpoints manually:

```bash
# Membership objects (active/pending) for the authenticated user
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/user/memberships/orgs?state=active&per_page=100" | jq '.[].organization.login'

# Orgs for the authenticated user (often simpler)
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/user/orgs?per_page=100" | jq '.[].login'
```

If these return empty lists, your token likely lacks `read:org` permission or you are not a member of any orgs.

## Feedback and Contributing

For feedback or contributions open an issue or pull request.

I use [`ruff`](https://docs.astral.sh/ruff/) for linting and formatting.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
