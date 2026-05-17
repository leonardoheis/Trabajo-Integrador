# Trabajo Integrador - Clasificación de Documentos Municipales

Este repositorio contiene el código fuente y la documentación para el Trabajo Integrador. El proyecto consta de un pipeline completo para la ingesta, clasificación inteligente y gestión de documentos, enfocado principalmente en el procesamiento de normativas de la Municipalidad de Rosario.

## 🏗 Arquitectura del Proyecto

El proyecto está estructurado en varios componentes clave:

### 1. Ingesta de Datos (`downloader.py` y `Scrapper/`)
Un script asíncrono y robusto en Python diseñado para descargar y organizar decenas de miles de documentos PDF a partir del portal de datos abiertos de la Municipalidad de Rosario.
- **Carpeta `Scrapper/`**: Contiene archivos CSV (`boletines.csv`, `decretos.csv`, `ordenanzas.csv`, etc.) con los metadatos y enlaces de origen.
- **Técnicas**: Utiliza `aiohttp` para descargas concurrentes, `BeautifulSoup` para el scraping de enlaces internos y `weasyprint` para renderizar páginas HTML complejas como PDFs.
- **Resiliencia**: Cuenta con un sistema de *checkpoint* (`checkpoint.json`) que permite reanudar descargas interrumpidas.

### 2. Backend API (`backend/`)
Una API REST desarrollada con **FastAPI** encargada de la lógica de negocio y clasificación de los documentos.
- **Tecnologías Core**: Python, FastAPI, LangGraph, Azure AI Document Intelligence.
- **Funcionalidad**: 
  - Expone endpoints para la subida de documentos (`/api/v1/upload`).
  - Clasifica automáticamente los archivos subidos utilizando IA y los enruta a carpetas categorizadas (`invoices`, `contracts`, `reports`, `review`, etc.).
  - Integra un orquestador LangGraph para manejar flujos complejos de decisión y procesamiento de documentos.

### 3. Frontend de Usuario (`frontend/`)
Una aplicación web de una sola página (SPA) desarrollada con **React** y construida con **Vite**.
- **Tecnologías Core**: React 18, TypeScript, Tailwind CSS, React Router, Axios.
- **Funcionalidad**: Interfaz intuitiva y moderna que permite a los usuarios finales subir archivos, monitorear el progreso de la clasificación (jobs) y revisar la auditoría del procesamiento.

### 4. Despliegue y Orquestación (`docker-compose.yml`, `azure_deploy/`, `DEPLOY.md`)
- **Docker Compose**: Proporciona un entorno de desarrollo unificado (`docker-compose.yml`) que levanta de manera coordinada el frontend, el backend y los volúmenes para almacenar la salida.
- **Cloud (Azure/Colab)**: Scripts y guías detalladas en [DEPLOY.md](DEPLOY.md) para escalar la descarga y procesamiento usando Azure Container Instances, Blob Storage o Google Colab.

---

## 🚀 Guía de Inicio Rápido

### Requisitos Previos
- [Docker](https://docs.docker.com/get-docker/) y Docker Compose.
- Opcional (para desarrollo local sin Docker): Python 3.10+, Node.js 18+.

### Levantar el Entorno con Docker

La forma más rápida de ejecutar el proyecto completo es mediante Docker Compose:

```bash
# Construir e iniciar los servicios en segundo plano
docker-compose up --build -d
```

Una vez que los contenedores estén en ejecución:
- 🌐 **Frontend (Interfaz Gráfica)**: [http://localhost:5173](http://localhost:5173)
- ⚙️ **Backend (API Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)

El sistema soporta *Hot-Reload* tanto en el backend como en el frontend gracias a los volúmenes mapeados en el `docker-compose.yml`.

---

## 🗄 Uso del Descargador Masivo

Si deseas poblar tu entorno con el corpus documental de la Municipalidad de Rosario:

1. Crea un entorno virtual e instala las dependencias:
   ```bash
   pip install aiohttp aiofiles tqdm beautifulsoup4 lxml weasyprint
   ```

2. Ejecuta el script principal:
   ```bash
   python downloader.py --output ./downloads --concurrency 5 --delay 0.5
   ```
   *Nota: Se recomienda mantener la concurrencia baja (`5`) y un delay prudente (`0.5s`) para evitar ser bloqueado por los servidores del municipio.*

3. **Colab Notebook**: Alternativamente, puedes importar y ejecutar el archivo `colab_downloader.ipynb` directamente en Google Colab para utilizar recursos en la nube.

Para estrategias de despliegue avanzadas en Azure, consulta detalladamente el documento de despliegue: [DEPLOY.md](DEPLOY.md).
