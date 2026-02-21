FROM python:3.11-slim

# Установляем системные зависимости (включая tesseract)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаем необходимые папки
RUN mkdir -p uploads/photos data

# Запускаем приложение
CMD ["python", "app.py"]
