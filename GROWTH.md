# EvidenceOS Growth System

> Structural foundation to grow EvidenceOS with **10/10 confidence** —
> App Store approval, user trust, viral distribution, and platform scale.

## Confidence model

| Layer | Target | Owner path |
|---|---|---|
| **Compliance** | 10/10 | Legal pages, health disclaimers, privacy labels |
| **App Store** | 10/10 | iOS shell, metadata, TestFlight, review notes |
| **Product trust** | 10/10 | Cited answers, abstention, source highlights |
| **Distribution** | 10/10 | Share cards, auto-run links, launch playbook |
| **Platform** | 10/10 | API, domain packs, citation-engine merge |

Run the gate:

```bash
python3 scripts/verify_release_readiness.py
```

## Repository map

```
first-ai-agent/
├── backend/app/
│   ├── main.py              # API + demo + share cards
│   └── pages/legal.py       # /privacy /support /terms /health-disclaimer /app
├── ios/                     # App Store shell (SwiftUI + WKWebView)
├── store/                   # App Store Connect metadata
├── docs/
│   ├── growth/ROADMAP.md    # Phase plan to 10/10
│   └── app-store/CHECKLIST.md
├── scripts/
│   └── verify_release_readiness.py
├── LAUNCH.md                # Viral launch copy
└── GROWTH.md                # This file
```

## Phase 0 — Foundation (now)

- [x] Public demo `/try` with examples + highlights
- [x] Shareable proof cards `/s/<id>`
- [x] Legal pages for App Store
- [x] iOS Swift scaffold
- [x] Release readiness script
- [x] App Store metadata template

## Phase 1 — App Store ready (next)

1. Enroll Apple Developer Program
2. Deploy production (`render.yaml`)
3. Set `PUBLIC_SITE_URL`, `SUPPORT_EMAIL`, `PRIVACY_EMAIL`
4. Generate Xcode project (`ios/README.md`)
5. TestFlight on real iPhone
6. Submit with `store/app-store-metadata.json`

See: `docs/app-store/CHECKLIST.md`

## Phase 2 — Viral growth

- Auto-run share links (`/try?run=prediabetes`)
- "Watch it refuse" as default marketing hook
- Show HN / r/LocalLLaMA / Product Hunt (`LAUNCH.md`)
- Dynamic OG images per share card (future)

## Phase 3 — Product depth

- PDF upload in demo + iOS
- Claim-check mode ("is this statement supported?")
- Saved documents workspace
- Domain packs (NYC, health, legal, research)

## Phase 4 — Platform

- Public API for cited answers
- Merge `citation-engine` as verification backend
- Embeddable "Verified by EvidenceOS" badge
- Tenant workspaces + audit exports

## Environment variables (production)

| Variable | Purpose |
|---|---|
| `PUBLIC_SITE_URL` | Share links + iOS base URL |
| `ALLOWED_ORIGINS` | CORS for web + app |
| `SUPPORT_EMAIL` | Support page + App Store |
| `PRIVACY_EMAIL` | Privacy contact |
| `APP_ENV` | `production` |

## Weekly operating rhythm

1. Run `verify_release_readiness.py`
2. Check `/health` and `/ready` on production
3. Review new share-card abstain rate (are refusals working?)
4. Triage App Store reviews within 24h
5. Ship one domain pack or one native iOS improvement per week

## What makes this different (never dilute)

1. **Extractive answers** — answer is the cited source text
2. **Abstention** — no evidence, no answer
3. **Visible proof** — highlighted source sentences
4. **Shareable artifacts** — proof cards, not chat threads
5. **Honest positioning** — not medical/legal advice

## Next command

```bash
python3 scripts/verify_release_readiness.py && cd backend && .venv/bin/python -m pytest -q
```
