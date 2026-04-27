# Camera to PDF Roadmap

## Product Direction

First AI Agent should evolve into a local-first document assistant that can turn phone camera pictures into PDF files, then let the user ask questions about those PDFs.

Core idea:

> Take photos of paper documents, convert them into a PDF, then chat with the document privately.

## Why This Feature Matters

This feature makes the project more useful because many real documents still begin on paper:

- Class notes
- Receipts
- Forms
- Letters
- Handwritten pages
- Printed articles
- Contracts
- Book pages

Instead of only supporting existing PDFs, the app can help users create PDFs from real-world documents.

## MVP Flow

1. User opens the app from a phone or browser.
2. User taps **Scan / Add Photos**.
3. User takes pictures using the phone camera or uploads images.
4. App previews selected images.
5. User can remove bad images.
6. App converts selected images into one PDF.
7. User downloads the PDF.
8. User places the PDF in `data/documents/`.
9. First AI Agent can read or summarize the PDF.

## Phase 1: Browser-Only Demo

Goal: prove the feature works without changing the backend too much.

Build:

- Add a `scan.html` page or scan section in the current web UI.
- Use phone camera/image upload support:

```html
<input type="file" accept="image/*" capture="environment" multiple>
```

- Show image previews.
- Convert images into a PDF inside the browser.
- Allow the user to download the PDF.

Best for:

- Live demo
- Phone testing
- Simple public preview

## Phase 2: Local Save Mode

Goal: connect the scanner directly to the local agent.

Build:

- Add upload endpoint in `run_web.py`.
- Save generated PDFs into `data/documents/`.
- Add a button: **Ask this PDF**.
- After saving, call the existing document Q&A flow.

Best for:

- Private local use
- Offline workflow
- Personal document assistant

## Phase 3: Optional OCR

Goal: improve scanned document readability.

Important note: image-to-PDF does not automatically make text searchable. If the image is only a picture, the agent may not extract text unless OCR is added.

Possible OCR options:

- Local OCR with Tesseract
- Python OCR library later
- Cloud OCR only for optional live mode, not default private mode

Keep OCR as a later upgrade. The first goal is camera/photo to PDF.

## Safety and Privacy Rules

- Local mode should keep documents on the user's machine.
- Live demo should avoid private/sensitive document uploads at first.
- Do not allow public live users to run local terminal commands.
- Do not expose private files.
- Keep the public demo simple and safe.

## Best Product Positioning

Name ideas:

- First AI Agent Scanner
- Scan & Ask AI
- SnapPDF AI
- LocalPDF Agent

Best tagline:

> Turn photos into PDFs, then ask questions from your documents privately.

## Success Criteria

The feature is working when a user can:

1. Open the scanner on a phone.
2. Take or upload multiple pictures.
3. Preview the images.
4. Convert them into one PDF.
5. Download the PDF.
6. Use the PDF inside First AI Agent.

## Next Build Step

Start with Phase 1:

- Create a simple browser scanner page.
- Add camera/photo input.
- Add preview.
- Add PDF export.

Do not rebuild the whole project. Add this as a focused feature on top of the existing local-first agent.
