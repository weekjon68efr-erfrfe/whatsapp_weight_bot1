FROM python:3.11

WORKDIR /app

# Устанавливаем системные зависимости (tesseract) и затем Python-зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
	tesseract-ocr \
	libtesseract-dev \
	build-essential \
	pkg-config \
	libjpeg-dev \
	zlib1g-dev \
	libpng-dev \
	libfreetype6-dev \
	libgl1 \
	libglib2.0-0 \
	libsm6 \
	libxrender1 \
	libxext6 \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Обновим pip/setuptools/wheel, чтобы pip мог загрузить prebuilt wheels (решает ошибки сборки типа PyMuPDF)
RUN pip install --upgrade pip setuptools wheel
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем необходимые директории
RUN mkdir -p uploads/photos data

# Запускаем приложение
CMD ["python", "app.py"]
