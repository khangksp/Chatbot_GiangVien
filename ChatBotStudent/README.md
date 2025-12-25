# ChatBot GV - AI Assistant cho Giảng viên BDU

## Mô tả
ChatBot GV là một hệ thống AI assistant được thiết kế đặc biệt để hỗ trợ giảng viên tại trường Đại học Bình Dương (BDU). Bot có khả năng:

- Trả lời câu hỏi dựa trên tài liệu và kiến thức về trường
- Xử lý tài liệu PDF và OCR
- Tích hợp với các AI models như Gemini, PhoBERT
- Quản lý conversation memory và context
- Hỗ trợ đa ngôn ngữ (Tiếng Việt)

## Tính năng chính

### 🤖 AI Models
- **Gemini 2.0 Flash**: Model chính để xử lý ngôn ngữ tự nhiên
- **PhoBERT**: Xử lý tiếng Việt và NER
- **Tesseract OCR**: Nhận dạng văn bản từ hình ảnh
- **Poppler**: Xử lý PDF

### 📚 Quản lý Tài liệu
- Upload và xử lý tài liệu PDF
- OCR từ hình ảnh
- Tìm kiếm thông tin trong tài liệu
- Cache câu trả lời để tối ưu hiệu suất

### 💬 Chat System
- Conversation memory
- Context-aware responses
- Personal addressing (xưng hô phù hợp)
- Smart greeting (chào một lần mỗi session)

## Cài đặt

### Yêu cầu hệ thống
- Python 3.8+
- Django 4.0+
- Các dependencies trong `requirements.txt`

### Cài đặt dependencies
```bash
cd backend
pip install -r requirements.txt
```

### Cấu hình
1. Tạo file `.env` với các biến môi trường cần thiết
2. Cấu hình API keys cho Gemini và các services khác
3. Chạy migrations:
```bash
python manage.py migrate
```

### Chạy server
```bash
python manage.py runserver
```

## Cấu trúc dự án

```
chatbotGV/
├── backend/                 # Django backend
│   ├── ai_models/          # AI services và models
│   ├── authentication/     # Xác thực người dùng
│   ├── chat/              # Chat functionality
│   ├── knowledge/          # Quản lý tài liệu
│   └── qa_management/      # Q&A management
├── athenaeum/             # External libraries (Tesseract, Poppler)
└── docker-compose.yml     # Docker configuration
```

## API Endpoints

### Chat
- `POST /api/chat/` - Gửi tin nhắn chat
- `GET /api/chat/history/` - Lấy lịch sử chat

### Tài liệu
- `POST /api/knowledge/upload/` - Upload tài liệu
- `GET /api/knowledge/documents/` - Danh sách tài liệu

### Xác thực
- `POST /api/auth/login/` - Đăng nhập
- `POST /api/auth/register/` - Đăng ký

## Tính năng đặc biệt

### Smart Greeting System
Bot được thiết kế để chỉ chào một lần mỗi session, tránh việc chào lặp đi lặp lại trong cùng một cuộc trò chuyện.

### Context-Aware Responses
Bot có khả năng hiểu context của cuộc trò chuyện và đưa ra câu trả lời phù hợp với ngữ cảnh.

### Personal Addressing
Bot tự động xưng hô phù hợp với từng người dùng dựa trên thông tin profile.

## Đóng góp

1. Fork repository
2. Tạo feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Tạo Pull Request

## License

Dự án này được phát triển cho mục đích học tập và nghiên cứu tại trường Đại học Bình Dương.

## Liên hệ

- Trường Đại học Bình Dương (BDU)
- Email: support@bdu.edu.vn
