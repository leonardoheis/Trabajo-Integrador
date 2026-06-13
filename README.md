# Document Scraper — Municipalidad de Rosario

This repository contains the scraper and bulk downloader for municipal documents from the open-data portal of the Municipalidad de Rosario (Argentina).

The scraper collects metadata from the portal and downloads tens of thousands of PDF documents organized by category.

## Downloaded Documents

The scraped documents are available on Google Drive:

[https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link](https://drive.google.com/drive/folders/1_IPfa4m1mmz6wFPOLtEf3T4xYknJap7B?usp=drive_link)

## Repository Structure

```
/
├── Scrapper/               CSV files with document metadata and source links
│   ├── boletines.csv
│   ├── compendios_de_boletines.csv
│   ├── convenios.csv
│   ├── declaraciones_concejo_municipal.csv
│   ├── decreto_ordenanzas.csv
│   ├── decretos.csv
│   ├── decretos_concejo_municipal.csv
│   ├── ordenanzas.csv
│   ├── resoluciones.csv
│   └── resoluciones_concejo_municipal.csv
├── downloader.py           Async bulk downloader (local disk output)
└── colab_downloader.ipynb  Google Colab notebook version
```

## Document Categories

| Folder | Description |
|--------|-------------|
| `boletines` | Municipal bulletins |
| `compendios_de_boletines` | Bulletin compendiums |
| `convenios` | Agreements |
| `declaraciones_concejo_municipal` | Municipal council declarations |
| `decreto_ordenanzas` | Decree-ordinances |
| `decretos` | Decrees |
| `decretos_concejo_municipal` | Municipal council decrees |
| `ordenanzas` | Ordinances |
| `resoluciones` | Resolutions |
| `resoluciones_concejo_municipal` | Municipal council resolutions |

## Running the Downloader

### Install dependencies

```bash
pip install aiohttp aiofiles tqdm beautifulsoup4 lxml weasyprint
```

### Run

```bash
python downloader.py --output ./downloads --concurrency 5 --delay 0.5
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--output` | `./downloads` | Destination folder for PDFs |
| `--concurrency` | `5` | Parallel downloads — keep low to avoid being rate-limited |
| `--delay` | `0.5` | Seconds between requests |

The downloader creates a `checkpoint.json` file to resume interrupted runs. Re-run the same command and it will skip already-downloaded files.

### Google Colab

Open `colab_downloader.ipynb` directly in Google Colab to run the downloader using cloud resources without any local setup.

## How It Works

The downloader reads each CSV in `Scrapper/`, resolves the PDF URL for each row (handling several URL patterns used by the portal), and downloads the file with retry logic and rate limiting. A checkpoint file tracks progress so interrupted runs can be resumed without re-downloading completed files.

Supported link resolution strategies:

- **direct_pdf** — URL already points to the PDF
- **normativa** — extracts the document ID from `visualExterna.do?idNormativa=X` and builds the direct download URL
- **boletin_html** — scrapes the bulletin index page to find internal PDF IDs
- **html_to_pdf** — downloads a Plone HTML page and renders it to PDF via `weasyprint`
- **scrape_page** — generic scraping for compendium pages
