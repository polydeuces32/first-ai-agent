# EvidenceOS iOS App

Thin native shell for App Store distribution. Loads the hosted `/try` demo in a `WKWebView` and adds native value:

- Import `.txt` from Files / iCloud
- Share app link
- First-launch health / advice disclaimer
- Offline error screen
- In-app links to Privacy / Support / Health disclaimer

## Prerequisites

- Mac with **Xcode 15+**
- Apple Developer account ($99/yr)
- Production URL deployed (see `render.yaml` + `GROWTH.md`)

## Create the Xcode project (fastest)

### Option A — Manual (5 min)

1. Xcode → **File → New → Project → iOS App**
2. Product name: `EvidenceOS`
3. Bundle ID: `com.yourname.evidenceos`
4. Interface: SwiftUI · Language: Swift
5. Save into `ios/` (replace generated Swift files with files in `ios/EvidenceOS/`)
6. Set **Info.plist** values from `ios/EvidenceOS/Info.plist`
7. Add key `EVIDENCEOS_BASE_URL` = `https://your-domain.com`
8. Signing & Capabilities → select your Team
9. Run on simulator or device

### Option B — XcodeGen (if installed)

```bash
brew install xcodegen
cd ios
xcodegen generate
open EvidenceOS.xcodeproj
```

## App Store URLs (required)

Set these in App Store Connect:

| Field | Value |
|---|---|
| Privacy Policy | `https://your-domain.com/privacy` |
| Support URL | `https://your-domain.com/support` |
| Marketing URL | `https://your-domain.com/try` |

## TestFlight checklist

- [ ] `/try` loads on production URL
- [ ] Import `.txt` fills document box
- [ ] Ask question → cited answer or refusal
- [ ] Share link works
- [ ] Disclaimer shows on first launch
- [ ] Privacy / Support links open in Safari
- [ ] No crash on airplane mode (shows offline screen)

## Bundle ID

Recommended: `com.yourname.evidenceos`

Reserve the app name in App Store Connect as soon as your developer account is active.
