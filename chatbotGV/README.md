
## Mô tả hệ thống

Hệ thống được triển khai bằng **Docker Compose**, gồm **3 container chính**:

### 1. Các dịch vụ và port

| Service                | Container            | Port          | Chức năng                                                 |
| ---------------------- | -------------------- | ------------- | --------------------------------------------------------- |
| **Ollama**             | `bdu_chatbot_ollama` | `11434:11434` | Chạy model LLM local (Qwen2.5-7B), xử lý sinh câu trả lời |
| **Backend Chatbot GV** | `chatbot_be_gv`      | `8019:3019`   | Django backend: API chatbot, RAG, Speech, OCR             |
| **Database**           | `chatbot_db_gv`      | `5432:5432`   | PostgreSQL lưu dữ liệu giảng viên và tri thức             |

---

### Phân bổ tài nguyên

* **GPU (VRAM):**
  Chỉ dùng cho **Ollama (Qwen2.5-7B)** để sinh văn bản nhanh, tránh tranh chấp bộ nhớ.

* **CPU / RAM:**
  Dùng cho **Django Backend**, bao gồm:

  * RAG (Sentence-Transformers)
  * Speech-to-Text (Whisper qua Transformers)
  * OCR (Tesseract)

### Công nghệ chính sử dụng

* **LLM:** Qwen2.5-7B-Instruct (quantized int4/int8, chạy offline)
* **Backend:** Django
* **RAG:** Semantic Search + Keyword
* **Speech-to-Text:** `openai/whisper-large-v3`
* **OCR:** Tesseract
* **Database:** PostgreSQL
* **Triển khai:** Docker Compose

---

### Truy cập quản trị

* **Admin URL:**
  `http://<IP_Server>/bdu_chatbot/admin/`

* **Tài khoản mặc định:**

  * User: `admin`
  * Password: `Fira@2024`

---

### Khởi chạy hệ thống

```bash
1. docker-compose up -d --build hoặc chỉ muốn build riêng chatbot_gv: docker-compose up -d chatbot_gv
Sau đó chạy lệnh để pull llm qwen về container:
2. docker exec -it bdu_chatbot_ollama ollama run qwen2.5:7b
```

chatbot_gv:
D:\Github\CHUYEN-DOI-SO\chatbotGV\chatbotGV\backend>tree /F
Folder PATH listing for volume DATA
Volume serial number is 90B0-5A90
D:.
│   .env
│   db.sqlite3
│   Dockerfile
│   manage.py
│   requirements.txt
│   thinking-armor-463404-n1-d7bcb4ffcaf5.json
│   __init__.py
│
├───ai_models
│   │   admin.py
│   │   apps.py
│   │   external_api_service.py
│   │   gemini_service.py
│   │   interaction_logger_service.py
│   │   models.py
│   │   ner_service.py
│   │   ocr_service.py
│   │   phobert_service.py
│   │   query_response_cache.py
│   │   services.py
│   │   speech_service.py
│   │   tests.py
│   │   urls.py
│   │   vietnamese_normalizer.py
│   │   views.py
│   │   __init__.py
│   │
│   ├───gemini
│   │   │   confidence_manager.py
│   │   │   core.py
│   │   │   key_manager.py
│   │   │   memory.py
│   │   │   token_manager.py
│   │   │   utils.py
│   │   │   __init__.py
│   │   │
│   │   └───__pycache__
│   │           confidence_manager.cpython-310.pyc
│   │           core.cpython-310.pyc
│   │           key_manager.cpython-310.pyc
│   │           memory.cpython-310.pyc
│   │           token_manager.cpython-310.pyc
│   │           utils.cpython-310.pyc
│   │           __init__.cpython-310.pyc
│   │
│   ├───management
│   │       build_faiss_index.py
│   │
│   ├───migrations
│   │   │   __init__.py
│   │   │
│   │   └───__pycache__
│   │           __init__.cpython-310.pyc
│   │
│   └───__pycache__
│           admin.cpython-310.pyc
│           apps.cpython-310.pyc
│           external_api_service.cpython-310.pyc
│           gemini_service.cpython-310.pyc
│           google_drive_service.cpython-310.pyc
│           interaction_logger_service.cpython-310.pyc
│           models.cpython-310.pyc
│           ner_service.cpython-310.pyc
│           ocr_service.cpython-310.pyc
│           phobert_service.cpython-310.pyc
│           query_response_cache.cpython-310.pyc
│           services.cpython-310.pyc
│           speech_service.cpython-310.pyc
│           train_retriever.cpython-310.pyc
│           vietnamese_normalizer.cpython-310.pyc
│           vit5_service.cpython-310.pyc
│           __init__.cpython-310.pyc
│
├───authentication
│   │   admin.py
│   │   apps.py
│   │   models.py
│   │   serializers.py
│   │   tests.py
│   │   urls.py
│   │   views.py
│   │   __init__.py
│   │
│   ├───migrations
│   │   │   0001_initial.py
│   │   │   __init__.py
│   │   │
│   │   └───__pycache__
│   │           0001_initial.cpython-310.pyc
│   │           __init__.cpython-310.pyc
│   │
│   └───__pycache__
│           admin.cpython-310.pyc
│           apps.cpython-310.pyc
│           models.cpython-310.pyc
│           serializers.cpython-310.pyc
│           urls.cpython-310.pyc
│           views.cpython-310.pyc
│           __init__.cpython-310.pyc
│
├───backend
│   │   asgi.py
│   │   middleware.py
│   │   settings.py
│   │   urls.py
│   │   wsgi.py
│   │   __init__.py
│   │
│   └───__pycache__
│           middleware.cpython-310.pyc
│           settings.cpython-310.pyc
│           urls.cpython-310.pyc
│           wsgi.cpython-310.pyc
│           __init__.cpython-310.pyc
│
├───chat
│   │   admin.py
│   │   apps.py
│   │   models.py
│   │   tests.py
│   │   urls.py
│   │   views.py
│   │   __init__.py
│   │
│   ├───migrations
│   │   │   __init__.py
│   │   │
│   │   └───__pycache__
│   │           __init__.cpython-310.pyc
│   │
│   └───__pycache__
│           admin.cpython-310.pyc
│           apps.cpython-310.pyc
│           models.cpython-310.pyc
│           urls.cpython-310.pyc
│           views.cpython-310.pyc
│           __init__.cpython-310.pyc
│
├───data
│       link.csv
│       QA.csv
│       test_csv.py
│
├───knowledge
│   │   admin.py
│   │   apps.py
│   │   models.py
│   │   serializers.py
│   │   tests.py
│   │   urls.py
│   │   views.py
│   │   __init__.py
│   │
│   ├───migrations
│   │   │   0001_initial.py
│   │   │   __init__.py
│   │   │
│   │   └───__pycache__
│   │           0001_initial.cpython-310.pyc
│   │           __init__.cpython-310.pyc
│   │
│   └───__pycache__
│           admin.cpython-310.pyc
│           apps.cpython-310.pyc
│           models.cpython-310.pyc
│           serializers.cpython-310.pyc
│           urls.cpython-310.pyc
│           views.cpython-310.pyc
│           __init__.cpython-310.pyc
│
├───logs
│       failed_interactions.csv
│
├───media
├───models_cache
│   └───whisper
│       ├───.locks
│       │   ├───models--Systran--faster-whisper-large-v3
│       │   ├───models--Systran--faster-whisper-medium
│       │   └───models--Systran--faster-whisper-small
│       ├───models--Systran--faster-whisper-large-v3
│       │   ├───blobs
│       │   ├───refs
│       │   └───snapshots
│       │       └───edaa852ec7e145841d8ffdb056a99866b5f0a478
│       │               config.json
│       │               preprocessor_config.json
│       │               tokenizer.json
│       │               vocabulary.json
│       │
│       ├───models--Systran--faster-whisper-medium
│       │   ├───blobs
│       │   ├───refs
│       │   └───snapshots
│       │       └───08e178d48790749d25932bbc082711ddcfdfbc4f
│       │               config.json
│       │               tokenizer.json
│       │
│       └───models--Systran--faster-whisper-small
│           ├───blobs
│           ├───refs
│           └───snapshots
│               └───536b0662742c02347bc0e980a01041f333bce120
│                       config.json
│                       tokenizer.json
│
├───qa_management
│   │   admin.py
│   │   apps.py
│   │   models.py
│   │   services.py
│   │   signals.py
│   │   tests.py
│   │   urls.py
│   │   views.py
│   │   __init__.py
│   │
│   ├───management
│   │   └───commands
│   │           rebuild_faiss_index.py
│   │
│   ├───migrations
│   │   │   0001_initial.py
│   │   │   __init__.py
│   │   │
│   │   └───__pycache__
│   │           0001_initial.cpython-310.pyc
│   │           __init__.cpython-310.pyc
│   │
│   ├───templates
│   │   └───admin
│   │       └───qa_management
│   │               bulk_import.html
│   │               change_list.html
│   │               export_to_drive.html
│   │               import_from_drive.html
│   │               sync_status.html
│   │               tools.html
│   │
│   └───__pycache__
│           admin.cpython-310.pyc
│           apps.cpython-310.pyc
│           models.cpython-310.pyc
│           services.cpython-310.pyc
│           signals.cpython-310.pyc
│           urls.cpython-310.pyc
│           views.cpython-310.pyc
│           __init__.cpython-310.pyc
│
├───static
├───staticfiles
└───__pycache__
