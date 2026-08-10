# Growth Roadmap → 10/10 Confidence

## Phase 0 — Foundation ✅
**Goal:** Structural skeleton exists

- Legal pages live (`/privacy`, `/support`, `/terms`, `/health-disclaimer`, `/app`)
- iOS scaffold in `ios/`
- App Store metadata in `store/`
- Release gate script
- Viral demo with share cards

**Exit criteria:** `python3 scripts/verify_release_readiness.py` passes

---

## Phase 1 — App Store 10/10
**Goal:** TestFlight + first App Store approval

| Task | Confidence impact |
|---|---|
| Apple Developer enrollment | Required |
| Production deploy + domain | Required |
| Xcode project + signing | Required |
| TestFlight 10 installs, 0 crashes | High |
| Privacy labels in App Store Connect | High |
| Health disclaimer in-app + web | High |
| Native import + share | Passes 4.2 guideline |

**Exit criteria:** App Store status = Ready for Sale

---

## Phase 2 — Trust 10/10
**Goal:** Users believe the product

| Task | Confidence impact |
|---|---|
| Source URL on every public example | High |
| Highlight cited sentences | High |
| Refusal gallery / marketing | Medium |
| Synonym expansion for questions | Medium |
| Stricter off-topic abstention | High |

**Exit criteria:** >80% demo questions return correct citation or honest refusal

---

## Phase 3 — Distribution 10/10
**Goal:** Organic growth loops

| Task | Confidence impact |
|---|---|
| Share cards with OG tags | High |
| Auto-run deep links | High |
| Launch posts (LAUNCH.md) | Medium |
| Open-source + deploy button | Medium |
| Domain packs (NYC, health, legal) | High |

**Exit criteria:** 100+ share link opens/week

---

## Phase 4 — Platform 10/10
**Goal:** Infrastructure, not just an app

| Task | Confidence impact |
|---|---|
| Public API (`/api/demo/ask` hardened) | High |
| Workspace + document library | High |
| `citation-engine` merge | Very high |
| Embeddable verification badge | Medium |
| Enterprise audit exports | High |

**Exit criteria:** 1 external integration using EvidenceOS API

---

## Confidence scorecard (track weekly)

| Area | Start | Target |
|---|---|---|
| Compliance pages | 10 | 10 |
| iOS App Store readiness | 4 | 10 |
| Production hosting | 6 | 10 |
| Demo trust (cite/refuse) | 8 | 10 |
| Viral loops | 7 | 10 |
| Platform/API | 3 | 10 |

**Overall today:** ~6.5/10 structural · **Target in 30 days:** 9/10 · **Target in 90 days:** 10/10
