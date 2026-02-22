FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости (tesseract) и затем Python-зависимости
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
	tesseract-ocr \
	libtesseract-dev \
	build-essential \
	pkg-config \
	libjpeg62-turbo-dev \
	zlib1g-dev \
	libpng-dev \
	libfreetype6-dev \
	libgl1 \
	libglib2.0-0 \
	libsm6 \
	libxrender1 \
	libxext6 \
	libmupdf-dev \
	python3-dev \
	cmake \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Обновим pip/setuptools/wheel, чтобы pip мог загрузить prebuilt wheels (решает ошибки сборки типа PyMuPDF)
RUN pip install --upgrade pip setuptools wheel && \
	pip install --prefer-binary --no-cache-dir PyMuPDF==1.20.1 && \
	pip install --prefer-binary --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем необходимые директории
RUN mkdir -p uploads/photos data

# Запускаем приложение
CMD ["python", "app.py"]
