# Despliegue en la nube — Descargador Municipalidad de Rosario

## Estimación de escala

| Categoría | Documentos |
|---|---|
| boletines | 2.035 |
| compendios | 27 |
| decretos | 5.483 |
| decretos concejo | 6.738 |
| ordenanzas | 5.306 |
| resoluciones | 173 |
| resoluciones concejo | 167 |
| convenios | 8 |
| declaraciones concejo | 37 |
| decreto-ordenanzas | 344 |
| **TOTAL** | **~20.318** |

Asumiendo ~200 KB promedio por PDF → **~4 GB** de almacenamiento total.

---

## Opción A — Google Colab + Google Drive (recomendada para empezar)

### Ventajas
- Sin costo (cuenta gratuita alcanza para el almacenamiento)
- Drive tiene 15 GB gratis; más que suficiente para ~4 GB
- Setup en minutos

### Pasos

1. Subir los archivos CSV a `Mi Drive / Rosario_Docs / Scrapper/`
2. Subir `downloader.py` a `Mi Drive / Rosario_Docs/`
3. Abrir `colab_downloader.ipynb` en Colab
4. Ejecutar celda a celda

### Limitación importante
La sesión de Colab gratuito se desconecta tras ~90 minutos de inactividad.  
Soluciones:
- **Recomendado**: usar el checkpoint (`checkpoint.json`) que guarda el progreso → volver a ejecutar retoma donde paró
- **Alternativa**: Colab Pro (~$10/mes) tiene sesiones de hasta 24 h
- **Anti-idle**: ejecutar en el navegador el siguiente snippet en la consola JS para simular actividad:

```javascript
// Pegar en la consola del navegador (F12 → Console)
function keep_alive() {
  document.querySelector("colab-connect-button")?.click();
}
setInterval(keep_alive, 60000);
```

---

## Opción B — Azure Student Credits (recomendada para producción)

Los créditos Azure for Students otorgan **$100 USD** sin tarjeta de crédito.  
El costo estimado de este job es **< $5 USD** en total.

### Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    Azure Subscription                   │
│                                                         │
│  ┌──────────────────┐     ┌──────────────────────────┐  │
│  │  Azure Container │────▶│   Azure Blob Storage     │  │
│  │  Registry (ACR)  │     │   (rosario-docs)         │  │
│  │  (imagen Docker) │     │   boletines/             │  │
│  └──────────────────┘     │   decretos/              │  │
│           │               │   ordenanzas/            │  │
│           ▼               │   ...                    │  │
│  ┌──────────────────┐     └──────────────────────────┘  │
│  │  Azure Container │                                   │
│  │  Instances (ACI) │                                   │
│  │  (job de Python) │                                   │
│  └──────────────────┘                                   │
│                                                         │
│  (Opcional: Storage File Share para montar los CSVs)    │
└─────────────────────────────────────────────────────────┘
```

### Componentes a provisionar

| Componente | SKU | Costo estimado |
|---|---|---|
| Azure Container Registry | Basic | ~$0.17/día → <$1 total |
| Azure Container Instances | 1 vCPU, 1.5 GB RAM | ~$0.02/hora → <$1 por corrida |
| Azure Blob Storage | LRS, Hot tier | ~$0.018/GB/mes → <$0.10/mes |
| **Total** | | **< $2 USD** |

### Pasos de despliegue

#### 1. Crear recursos en Azure (Azure CLI)

```bash
# Login
az login --use-device-code

# Variables
RG="rg-rosario-docs"
LOCATION="eastus"
ACR_NAME="rosariodocsacr"          # debe ser único globalmente
STORAGE_NAME="rosariodocsstorage"  # debe ser único globalmente
CONTAINER_NAME="rosario-docs"

# Resource Group
az group create --name $RG --location $LOCATION

# Storage Account
az storage account create \
  --name $STORAGE_NAME \
  --resource-group $RG \
  --location $LOCATION \
  --sku Standard_LRS

# Blob container
CONN_STR=$(az storage account show-connection-string \
  --name $STORAGE_NAME --resource-group $RG --query connectionString -o tsv)

az storage container create \
  --name $CONTAINER_NAME \
  --connection-string "$CONN_STR"

# Azure Container Registry
az acr create --name $ACR_NAME --resource-group $RG --sku Basic --admin-enabled true
```

#### 2. Construir y subir la imagen Docker

```bash
cd azure_deploy/

# Build y push directamente en ACR (sin Docker local)
az acr build \
  --registry $ACR_NAME \
  --image rosario-downloader:latest \
  --file Dockerfile \
  ..    # contexto = raíz del proyecto
```

#### 3. Ejecutar el job en Azure Container Instances

```bash
ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
ACR_PASS=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

az container create \
  --resource-group $RG \
  --name rosario-downloader \
  --image $ACR_SERVER/rosario-downloader:latest \
  --registry-login-server $ACR_SERVER \
  --registry-username $ACR_NAME \
  --registry-password "$ACR_PASS" \
  --cpu 1 \
  --memory 1.5 \
  --restart-policy Never \
  --environment-variables \
    AZURE_STORAGE_CONNECTION_STRING="$CONN_STR" \
    AZURE_CONTAINER_NAME="$CONTAINER_NAME" \
    CONCURRENCY="8" \
    DELAY="0.4"

# Ver logs en tiempo real
az container logs --resource-group $RG --name rosario-downloader --follow
```

#### 4. Acceder a los archivos descargados

```bash
# Listar todos los blobs
az storage blob list \
  --container-name $CONTAINER_NAME \
  --connection-string "$CONN_STR" \
  --query "[].name" -o tsv | head -20

# Descargar una categoría completa
az storage blob download-batch \
  --destination ./downloads/decretos \
  --source $CONTAINER_NAME \
  --pattern "decretos/*" \
  --connection-string "$CONN_STR"
```

#### 5. Programar ejecución periódica (para mantener actualizado)

```bash
# Usando Azure Logic Apps o simplemente re-ejecutando el container
# El checkpoint garantiza que solo descarga documentos nuevos
az container start --resource-group $RG --name rosario-downloader
```

---

## Recomendación final

| Criterio | Colab + Drive | Azure |
|---|---|---|
| Setup | ★★★★★ Muy fácil | ★★★ Requiere CLI |
| Costo | Gratis | < $2 USD |
| Velocidad | Media (CPU compartida) | Alta (dedicada) |
| Supervisión | Manual | Logs automáticos |
| Persistencia | Depende de sesión | Blob Storage permanente |
| Escalabilidad | Limitada | Alta |

**Para un trabajo universitario o PoC → Colab + Drive.**  
**Si el dataset va a actualizarse periódicamente → Azure.**
