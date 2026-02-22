FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости (tesseract) и затем Python-зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
	tesseract-ocr \
	libtesseract-dev \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем необходимые директории
RUN mkdir -p uploads/photos data

# Запускаем приложение
CMD ["python", "app.py"]
