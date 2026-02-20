#!/bin/bash
# Deploy do Flight Monitor para Google Cloud Run Jobs
# Executa tarefas agendadas via Cloud Scheduler

set -e

PROJECT_ID="codigos-465200"
REGION="southamerica-east1"
JOB_NAME="revo-flight-monitor"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${JOB_NAME}"

echo "=========================================="
echo "DEPLOY - REVO Flight Monitor"
echo "=========================================="

# 1. Build da imagem
echo "[1/5] Building Docker image..."
gcloud builds submit --tag ${IMAGE_NAME} .

# 2. Criar/Atualizar o Job
echo "[2/5] Creating Cloud Run Job..."
gcloud run jobs create ${JOB_NAME} \
    --image ${IMAGE_NAME} \
    --region ${REGION} \
    --memory 1Gi \
    --cpu 1 \
    --max-retries 1 \
    --task-timeout 10m \
    --set-env-vars "TZ=America/Sao_Paulo" \
    --set-secrets "SF_USERNAME=sf-username:latest,SF_PASSWORD=sf-password:latest,SF_SECURITY_TOKEN=sf-token:latest,SF_DOMAIN=sf-domain:latest,TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,TELEGRAM_CHAT_ID=telegram-chat-id:latest" \
    2>/dev/null || \
gcloud run jobs update ${JOB_NAME} \
    --image ${IMAGE_NAME} \
    --region ${REGION} \
    --memory 1Gi \
    --cpu 1 \
    --max-retries 1 \
    --task-timeout 10m \
    --set-env-vars "TZ=America/Sao_Paulo" \
    --set-secrets "SF_USERNAME=sf-username:latest,SF_PASSWORD=sf-password:latest,SF_SECURITY_TOKEN=sf-token:latest,SF_DOMAIN=sf-domain:latest,TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,TELEGRAM_CHAT_ID=telegram-chat-id:latest"

echo "[3/5] Job criado/atualizado com sucesso!"

# 3. Criar schedulers para cada tarefa
echo "[4/5] Configurando Cloud Scheduler..."

# Briefing matinal - 06:00
gcloud scheduler jobs create http briefing-matinal-0600 \
    --location ${REGION} \
    --schedule "0 6 * * *" \
    --time-zone "America/Sao_Paulo" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
    --message-body '{"overrides":{"containerOverrides":[{"args":["--briefing"]}]}}' \
    2>/dev/null || echo "  briefing-matinal-0600 ja existe"

# Verificação de voos - a cada 15 minutos
gcloud scheduler jobs create http check-voos-15min \
    --location ${REGION} \
    --schedule "*/15 * * * *" \
    --time-zone "America/Sao_Paulo" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
    --message-body '{"overrides":{"containerOverrides":[{"args":["--check-now"]}]}}' \
    2>/dev/null || echo "  check-voos-15min ja existe"

# Verificação meteorológica - a cada 30 minutos
gcloud scheduler jobs create http check-weather-30min \
    --location ${REGION} \
    --schedule "*/30 * * * *" \
    --time-zone "America/Sao_Paulo" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
    --message-body '{"overrides":{"containerOverrides":[{"args":["--weather-now"]}]}}' \
    2>/dev/null || echo "  check-weather-30min ja existe"

# Imagens meteorológicas - 09:00, 12:00, 15:00, 17:00
for hora in 9 12 15 17; do
    gcloud scheduler jobs create http weather-images-${hora}h \
        --location ${REGION} \
        --schedule "0 ${hora} * * *" \
        --time-zone "America/Sao_Paulo" \
        --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method POST \
        --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
        --message-body '{"overrides":{"containerOverrides":[{"args":["--weather-images"]}]}}' \
        2>/dev/null || echo "  weather-images-${hora}h ja existe"
done

# Alertas proativos - a cada 2 horas
gcloud scheduler jobs create http proactive-alerts-2h \
    --location ${REGION} \
    --schedule "0 */2 * * *" \
    --time-zone "America/Sao_Paulo" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
    --message-body '{"overrides":{"containerOverrides":[{"args":["--proactive-alert"]}]}}' \
    2>/dev/null || echo "  proactive-alerts-2h ja existe"

# Resumo diário - 18:00
gcloud scheduler jobs create http resumo-diario-1800 \
    --location ${REGION} \
    --schedule "0 18 * * *" \
    --time-zone "America/Sao_Paulo" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
    --message-body '{"overrides":{"containerOverrides":[{"args":["--summary-now"]}]}}' \
    2>/dev/null || echo "  resumo-diario-1800 ja existe"

# IPMet Tendencia do Tempo - a cada 30 minutos
gcloud scheduler jobs create http ipmet-tendencia-30min \
    --location ${REGION} \
    --schedule "*/30 * * * *" \
    --time-zone "America/Sao_Paulo" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
    --message-body '{"overrides":{"containerOverrides":[{"args":["--ipmet-tendencia"]}]}}' \
    2>/dev/null || echo "  ipmet-tendencia-30min ja existe"

echo "[5/5] Deploy concluido!"
echo ""
echo "=========================================="
echo "RESUMO DOS AGENDAMENTOS"
echo "=========================================="
echo "  06:00     - Briefing matinal (voos 3 dias + meteo)"
echo "  */15 min  - Verificacao de voos"
echo "  */30 min  - Verificacao meteorologica"
echo "  */30 min  - IPMet Tendencia do Tempo"
echo "  09/12/15/17h - Imagens meteorologicas"
echo "  */2h      - Alertas proativos"
echo "  18:00     - Resumo diario"
echo "=========================================="
echo ""
echo "Para testar manualmente:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --args='--briefing'"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --args='--ipmet-tendencia'"
