# OCR Setup for First AI Agent

Optional local OCR mode for scanned image PDFs.

## macOS

```bash
brew install tesseract poppler
pip install -r requirements-ocr.txt
```

## What OCR adds

- Read scanned PDFs made from camera photos
- Searchable extracted text
- Better summaries and Q&A
- Works locally/private mode

## Recommended next integration

When a scanned PDF is saved to data/documents/, run OCR and create a sidecar .txt file for the agent to read.
