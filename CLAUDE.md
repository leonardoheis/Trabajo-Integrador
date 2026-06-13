# CLAUDE.md — Municipalidad de Rosario Document Scraper

Bulk scraper and downloader for municipal documents (Municipalidad de Rosario, Argentina).
Reads PDF metadata from CSVs in `Scrapper/` and downloads the files organized by category.

## Structure

```
/
├── Scrapper/               CSV files with metadata and source links (10 document types)
├── downloader.py           Async bulk downloader — saves PDFs to local disk
└── colab_downloader.ipynb  Google Colab version of the downloader
```

## Running the downloader

```bash
pip install aiohttp aiofiles tqdm beautifulsoup4 lxml weasyprint
python downloader.py --output ./downloads --concurrency 5 --delay 0.5
```

Arguments:
- `--output` — destination folder (default: `./downloads`)
- `--concurrency` — parallel downloads, keep ≤ 5 to avoid rate-limiting (default: 5)
- `--delay` — seconds between requests (default: 0.5)

A `checkpoint.json` file is written to track progress; re-running skips already-downloaded files.

## Code conventions

- **Python**: standard library + aiohttp/aiofiles/tqdm/beautifulsoup4/weasyprint.
- All comments and strings are in English.
- No type stubs required — plain type hints where useful.

## Link resolution strategies in downloader.py

| Type | How it works |
|------|-------------|
| `direct_pdf` | URL already points to the PDF |
| `normativa` | Extracts `idNormativa` from the URL and builds a direct download URL |
| `boletin_html` | Scrapes the bulletin index page to find internal PDF IDs |
| `html_to_pdf` | Downloads a Plone HTML page and converts it to PDF via weasyprint |
| `scrape_page` | Generic scraping for compendium pages |

## Downloaded documents

Available on Google Drive:
https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link
