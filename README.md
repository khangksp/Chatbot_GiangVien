**Chatbot GV:** Port 8019, 5432 (DB)
**Chatbot Sinh Viên:** Port 8020, 5433 (DB)

**trong settings.py của file GV đang để:**

FORCE_SCRIPT_NAME = '/bdu_chatbot_gv'
STATIC_URL = '/bdu_chatbot_gv/static/'

**trong settings.py của file GV đang để:**

FORCE_SCRIPT_NAME = '/bdu_chatbot_sv'
STATIC_URL = '/bdu_chatbot_sv/static/'

**mật khẩu khi đăng nhập vào trang admin là:** admin/Fira@2024