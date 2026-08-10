# App Store Checklist — 10/10 Confidence

## Before you enroll
- [ ] Product name decided: **EvidenceOS**
- [ ] Domain purchased
- [ ] Support email active (`SUPPORT_EMAIL`)
- [ ] Privacy email active (`PRIVACY_EMAIL`)

## Apple Developer
- [ ] Enroll at https://developer.apple.com/programs/ ($99/yr)
- [ ] App Store Connect access confirmed
- [ ] Bundle ID created: `com.evidenceos.app` (or your org prefix)
- [ ] App name reserved in App Store Connect

## Production backend
- [ ] GitHub repo pushed
- [ ] Render Blueprint deployed (`render.yaml`)
- [ ] `PUBLIC_SITE_URL` set to production domain
- [ ] `ALLOWED_ORIGINS` includes production domain
- [ ] `/try` loads in browser
- [ ] `/privacy` and `/support` load (required URLs)

## iOS app (`ios/`)
- [ ] Xcode project created (see `ios/README.md`)
- [ ] `EVIDENCEOS_BASE_URL` points to production
- [ ] Signing team selected
- [ ] Runs on physical iPhone
- [ ] Import `.txt` from Files works
- [ ] Share button works
- [ ] First-launch disclaimer shows
- [ ] Airplane mode shows offline screen

## App Store Connect listing
Use `store/app-store-metadata.json` as copy source.

- [ ] App name + subtitle
- [ ] Description (no "diagnose" / "cure" language)
- [ ] Keywords
- [ ] Privacy Policy URL → `/privacy`
- [ ] Support URL → `/support`
- [ ] 1024×1024 app icon
- [ ] Screenshots: 6.7" and 6.5" iPhone
- [ ] App Privacy questionnaire completed honestly
- [ ] Export compliance: No (HTTPS only) unless you add custom encryption
- [ ] Review notes filled (see metadata `review_notes`)

## Health / legal safety (required for your demos)
- [ ] `/health-disclaimer` linked in App Store description
- [ ] In-app disclaimer on first launch (iOS)
- [ ] Footer disclaimer on web `/try`
- [ ] No claims of medical diagnosis or legal advice

## TestFlight (do this before public submit)
- [ ] Build uploaded to App Store Connect
- [ ] Internal testing group created
- [ ] 5+ testers install successfully
- [ ] Zero crashes in TestFlight crash logs
- [ ] Ask + refuse flows tested on device

## Submit
- [ ] `python3 scripts/verify_release_readiness.py` passes
- [ ] Submit for review
- [ ] Monitor Resolution Center for Apple questions

## After approval (ratings 10/10)
- [ ] Respond to every review in first 2 weeks
- [ ] Default first-run example = memorable (refuse or diabetes)
- [ ] Monitor `/health` uptime
- [ ] Ship PDF import within 30 days (common 1★ cause if missing)

## Rejection playbook

| Rejection | Fix |
|---|---|
| 4.2 Minimum Functionality | Emphasize native import, share, disclaimer in resubmission notes |
| 5.1 Privacy | Ensure `/privacy` matches App Privacy labels |
| 1.4.1 Health | Strengthen disclaimers; remove diagnostic language |
| 2.1 Crashes | Fix via TestFlight before resubmit |
