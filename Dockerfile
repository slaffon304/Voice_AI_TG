# Используем легковесный образ Python
FROM python:3.10-slim

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# 1. Обновляем pip до последней версии (чтобы он видел готовые wheels)
# 2. Ставим av<12.0.0 строго бинарником, чтобы избежать компиляции и падений
# 3. Устанавливаем остальные пакеты
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --only-binary=av "av<12.0.0" && \
    pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Открываем порт для FastAPI
EXPOSE 8000

# Запускаем Uvicorn сервер
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
