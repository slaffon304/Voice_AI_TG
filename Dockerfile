# Используем легковесный образ Python
FROM python:3.11-slim

# Устанавливаем системные зависимости для работы со звуком
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    libsoxr-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения 
COPY . .

# Переменные окружения по умолчанию для новой модели Gemini Live
ENV GEMINI_LIVE_MODEL=gemini-3.8-live \
    ARCHIVIST_MODELS=gemini-3.8-flash,gemini-3.1-flash-lite,gemini-4-argon \
    PIPELINE_SAMPLE_RATE=16000 \
    WEB_OUTPUT_SAMPLE_RATE=24000

# Открываем порт для FastAPI и Asterisk AudioSocket
EXPOSE 8000
EXPOSE 8085

# Запускаем Uvicorn сервер
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
