# Dockerfile
FROM python:3.10-slim

# instalar dependências do sistema para Chromium + libs comuns
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    wget \
    ca-certificates \
    curl \
    unzip \
    gnupg2 \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxdamage1 \
    libxrandr2 \
    libx11-6 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copia código e requirements
COPY . .

# instalar dependências python
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# variáveis de ambiente padrão (podem ser sobrescritas no Railway)
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV HEADLESS=true

# comando de execução
CMD ["python", "main.py"]
