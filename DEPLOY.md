# Deployment Guide — Municipalidad de Rosario Downloader

## Scale estimate

| Category | Documents |
|---|---|
| boletines | 2,035 |
| compendios | 27 |
| decretos | 5,483 |
| decretos concejo | 6,738 |
| ordenanzas | 5,306 |
| resoluciones | 173 |
| resoluciones concejo | 167 |
| convenios | 8 |
| declaraciones concejo | 37 |
| decreto-ordenanzas | 344 |
| **TOTAL** | **~20,318** |

Assuming ~200 KB average per PDF → **~4 GB** total storage.

---

## Google Colab + Google Drive (recommended)

### Advantages
- Free (a free account is enough for ~4 GB)
- Google Drive provides 15 GB free storage
- Setup in minutes

### Steps

1. Upload the CSV files to `My Drive / Rosario_Docs / Scrapper/`
2. Upload `downloader.py` to `My Drive / Rosario_Docs/`
3. Open `colab_downloader.ipynb` in Colab
4. Run cells top to bottom

### Session timeout

Free Colab sessions disconnect after ~90 minutes of inactivity. Options:

- **Recommended**: the `checkpoint.json` file saves progress — just re-run and it picks up where it left off
- **Alternative**: Colab Pro (~$10/month) supports sessions up to 24 hours
- **Anti-idle snippet**: paste this in the browser console (F12 → Console) to simulate activity:

```javascript
function keep_alive() {
  document.querySelector("colab-connect-button")?.click();
}
setInterval(keep_alive, 60000);
```
