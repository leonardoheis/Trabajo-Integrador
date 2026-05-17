FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar scripts (el azure usa downloader.py para importar helpers)
COPY ../downloader.py .
COPY downloader_azure.py .
COPY ../Scrapper/ ./Scrapper/

ENV PYTHONUNBUFFERED=1

CMD ["python", "downloader_azure.py"]
