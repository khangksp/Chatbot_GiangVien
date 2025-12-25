# --- SỬA DÒNG NÀY: Nâng lên 3.10 để fix lỗi cú pháp và warning Google ---
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- SỬA DÒNG NÀY: Thêm ffmpeg vào danh sách cài đặt ---
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    git \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-vie \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- CÁC PHẦN DƯỚI GIỮ NGUYÊN ---
RUN pip install --upgrade pip

# Cài Torch CPU
RUN pip install --no-cache-dir torch==2.3.1 torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Cài các thư viện tính toán
RUN pip install --no-cache-dir numpy==1.24.3 pandas==2.0.0 scipy scikit-learn==1.2.2 beautifulsoup4
# Cài Transformers
RUN pip install --no-cache-dir transformers==4.35.2 sentence-transformers==2.7.0

# Cài Langchain
RUN pip install --no-cache-dir langchain==0.1.0 langchain-community==0.0.10 langchain-core==0.1.8 langchain-google-genai==0.0.6

# COPY và cài requirements
COPY requirements.txt .
RUN sed -i '/torch/d' requirements.txt && \
    sed -i '/numpy/d' requirements.txt && \
    sed -i '/pandas/d' requirements.txt && \
    sed -i '/transformers/d' requirements.txt && \
    sed -i '/sentence-transformers/d' requirements.txt && \
    sed -i '/langchain/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3019
CMD ["python", "manage.py", "runserver", "0.0.0.0:3019"]