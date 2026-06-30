# Retail Velocity Decision Tool

Prescriptive analytics dashboard for Cinderhaven Provisions (specialty food). Nine decision modes help a CEO answer questions like "Is this SKU at risk of delisting?" and "How much should I produce?" using scan data from 6 retail channels.

## Stack

- **Backend:** Python 3.12, Dash 4.x, Flask-Caching (FileSystemCache)
- **Database:** Postgres (Fly.io), psycopg2 ThreadedConnectionPool
- **Frontend:** AG Grid, Plotly, Dash Bootstrap Components
- **Deploy:** Fly.io, single gunicorn worker, Docker
- **Tests:** pytest (163 tests), ruff lint, GitHub Actions CI

## Code layout

- `app/` — all application code (Dockerfile copies from here)
- `app/data.py` — SQL queries + caching layer
- `app/calcs.py` — pure calculation functions (no DB access)
- `app/constants.py` — thresholds, colors, retailer lists
- `app/decisions/` — one module per decision mode
- `tests/` — pytest suite (runs from project root: `cd app && python -m pytest ../tests`)
- `docs/solutions/` — documented solutions to past problems (bugs, best practices, workflow patterns), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`)

## Design System

Read `../lailara-design-system/LAILARA_DESIGN_SYSTEM.md` before any visual work — colors, typography, layout, components, charts, voice, interactions. It is the single source of truth.

---

Never write secrets, tokens, or passwords into tracked files, READMEs, or commit messages — use environment variables and secret stores only.
