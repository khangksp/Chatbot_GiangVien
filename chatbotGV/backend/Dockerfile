FROM python:3.10-slim

# Thiết lập biến môi trường
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV KMP_DUPLICATE_LIB_OK=TRUE
# Cache model AI để không phải tải lại mỗi lần build lại image
ENV TRANSFORMERS_CACHE=/app/ai_models_cache

WORKDIR /app

# 1. Cài đặt các gói hệ thống cần thiết (System Dependencies)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        build-essential \
        libpq-dev \
        git \
        curl \
        ffmpeg \
        libsndfile1 \
        tesseract-ocr \
        tesseract-ocr-vie \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 2. Cài đặt Python Dependencies
COPY requirements.txt .

# 🛠️ MẸO: Cài trước các gói nặng để cache layer Docker tối ưu
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install "numpy<2.0.0" && \
    pip install --no-cache-dir torch==2.3.1 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir sentence-transformers==2.7.0 && \
    pip install --no-cache-dir -r requirements.txt

# 3. Copy toàn bộ code vào container
COPY . .

# 4. Tạo thư mục cần thiết và cấp quyền
RUN mkdir -p logs media staticfiles ai_models_cache && chmod 777 ai_models_cache

# 5. Mở port 3019 (cổng nội bộ container)
EXPOSE 3019

# 6. Entrypoint Script
# Script này sẽ chạy mỗi khi container khởi động
RUN echo '#!/bin/bash\n\
set -e\n\
echo "=== BDU ChatBot Docker Setup ==="\n\
\n\
echo "⏳ Waiting for Database ($DB_HOST)..."\n\
while ! pg_isready -h $DB_HOST -p 5432 -U postgres; do sleep 1; done\n\
echo "✅ Database connected!"\n\
\n\
echo "📊 Running database migrations..."\n\
python manage.py migrate --noinput\n\
\n\
echo "📦 Collecting static files (WhiteNoise)..."\n\
python manage.py collectstatic --noinput\n\
\n\
echo "👤 Setting up SuperAdmin user..."\n\
python manage.py shell -c "\n\
from django.contrib.auth import get_user_model; \n\
User = get_user_model();\n\
try:\n\
    # Kiểm tra xem user admin đã tồn tại chưa\n\
    if not User.objects.filter(username='\''admin'\'').exists():\n\
        print('\''Creating new admin user...'\'');\n\
        u = User.objects.create_superuser('\''admin'\'', '\''admin@bdu.edu.vn'\'', '\''Fira@2024'\'');\n\
        # 👇 QUAN TRỌNG: Gán faculty_code để vượt qua Custom Auth\n\
        u.faculty_code = '\''admin'\'';\n\
        u.full_name = '\''Administrator'\'';\n\
        u.is_staff = True;\n\
        u.is_superuser = True;\n\
        u.save();\n\
        print('\''✅ Admin user created: admin / Fira@2024'\'');\n\
    else:\n\
        # Nếu đã tồn tại, đảm bảo faculty_code đúng\n\
        print('\''ℹ️ Admin user already exists. Checking faculty_code...'\'');\n\
        u = User.objects.get(username='\''admin'\'');\n\
        if u.faculty_code != '\''admin'\'':\n\
            u.faculty_code = '\''admin'\'';\n\
            u.save();\n\
            print('\''🔧 Fixed faculty_code for existing admin'\'');\n\
except Exception as e:\n\
    print(f'\''❌ Failed to create/update admin: {e}'\'')\n\
" \n\
\n\
echo "🚀 Starting Django server on 0.0.0.0:3019..."\n\
python manage.py runserver 0.0.0.0:3019\n' > /entrypoint.sh

# Cấp quyền thực thi cho script
RUN chmod +x /entrypoint.sh

# Set lệnh chạy mặc định
CMD ["/entrypoint.sh"]