# Используем легковесный образ Python
FROM python:3.11-slim

# Устанавливаем только ffmpeg, без лишнего мусора для разработки
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения 
COPY . .

# Открываем порт для FastAPI
EXPOSE 8000

# Запускаем Uvicorn сервер
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
