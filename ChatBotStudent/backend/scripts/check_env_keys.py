"""
Script đơn giản để load và verify keys từ file .env
"""
import os
import re

print("="*80)
print("🔍 KIỂM TRA KEYS TRONG FILE .ENV")
print("="*80)
print()

# =====================================
# STEP 1: TÌM VÀ ĐỌC FILE .ENV
# =====================================
print("📂 Bước 1: Tìm file .env")
print("-"*80)

# Các vị trí có thể có file .env
possible_paths = [
    "/mnt/user-data/uploads/_env",  # File user upload
    ".env",
    "../.env",
    "backend/.env",
    "../backend/.env"
]

env_file_path = None
for path in possible_paths:
    if os.path.exists(path):
        env_file_path = path
        print(f"✅ Tìm thấy file .env: {path}")
        break

if not env_file_path:
    print("❌ KHÔNG TÌM THẤY FILE .ENV!")
    print("   Các vị trí đã check:")
    for path in possible_paths:
        print(f"   - {path}")
    exit(1)

print()

# =====================================
# STEP 2: ĐỌC VÀ PARSE KEYS
# =====================================
print("📋 Bước 2: Đọc và parse keys từ file")
print("-"*80)

keys_from_file = {}
try:
    with open(env_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        
        # Skip comments và empty lines
        if not line or line.startswith('#'):
            continue
        
        # Parse GEMINI_API_KEY=xxx (supports numbered variants)
        if line.startswith('GEMINI_API_KEY'):
            match = re.match(r'(GEMINI_API_KEY\d*)=(.+)', line)
            if match:
                key_name = match.group(1)
                key_value = match.group(2).strip().strip('"').strip("'")
                
                if key_value:
                    keys_from_file[key_name] = key_value
                    masked = f"{key_value[:10]}...{key_value[-6:]}" if len(key_value) > 16 else key_value
                    print(f"  ✅ Line {line_num:3d}: {key_name:20s} = {masked}")
                else:
                    print(f"  ⚠️ Line {line_num:3d}: {key_name} có giá trị rỗng")
    
    print()
    print(f"📊 Tổng số keys tìm thấy trong file: {len(keys_from_file)}")
    
except Exception as e:
    print(f"❌ Lỗi khi đọc file: {e}")
    exit(1)

print()

# =====================================
# STEP 3: VERIFY KEYS ORDER
# =====================================
print("📋 Bước 3: Kiểm tra thứ tự keys")
print("-"*80)

expected_order = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY{i}" for i in range(2, 15)]
actual_keys = list(keys_from_file.keys())

print("Thứ tự keys trong file:")
for idx, key_name in enumerate(actual_keys, 1):
    key_value = keys_from_file[key_name]
    masked = f"{key_value[:10]}...{key_value[-6:]}" if len(key_value) > 16 else key_value
    
    # Highlight key đầu tiên
    if idx == 1:
        print(f"  🔑 {idx:2d}. {key_name:20s} = {masked}  ⭐ KEY ĐẦU TIÊN (sẽ được dùng trước)")
    else:
        print(f"     {idx:2d}. {key_name:20s} = {masked}")

print()

# =====================================
# STEP 4: CHECK FIRST KEY STATUS
# =====================================
print("📋 Bước 4: Kiểm tra trạng thái key đầu tiên")
print("-"*80)

if actual_keys:
    first_key_name = actual_keys[0]
    first_key_value = keys_from_file[first_key_name]
    
    print(f"Key đầu tiên: {first_key_name}")
    print(f"Giá trị: {first_key_value[:20]}...{first_key_value[-10:]}")
    print()
    print("❓ Bạn nói đã paste key 'dùng được' vào đây nhưng vẫn bị limit?")
    print()
    print("🔍 Có thể do:")
    print("   1. ❌ Agent KHÔNG ĐỌC TỪ .ENV mà dùng hardcoded key")
    print("   2. ❌ Key_manager không load đúng thứ tự")
    print("   3. ❌ Server chưa restart sau khi sửa .env")
    print("   4. ❌ Key 'dùng được' thực ra cũng đã hết quota")

print()

# =====================================
# STEP 5: SIMULATE KEY_MANAGER LOAD
# =====================================
print("📋 Bước 5: Giả lập cách GeminiApiKeyManager load keys")
print("-"*80)

print("Giả lập load keys theo thứ tự:")

# Cách 1: Load theo thứ tự trong expected_order
simulated_keys_v1 = []
for key_name in expected_order:
    if key_name in keys_from_file:
        simulated_keys_v1.append(keys_from_file[key_name])

print()
print(f"✅ Version 1 (theo thứ tự standard): {len(simulated_keys_v1)} keys")
for idx, key in enumerate(simulated_keys_v1, 1):
    print(f"   {idx}. {key[:10]}...{key[-6:]}")

# Cách 2: Load theo thứ tự xuất hiện trong file
simulated_keys_v2 = list(keys_from_file.values())
print()
print(f"✅ Version 2 (theo thứ tự trong file): {len(simulated_keys_v2)} keys")
for idx, key in enumerate(simulated_keys_v2, 1):
    print(f"   {idx}. {key[:10]}...{key[-6:]}")

if simulated_keys_v1 and simulated_keys_v2 and simulated_keys_v1[0] != simulated_keys_v2[0]:
    print()
    print("⚠️ WARNING: Key đầu tiên KHÁC NHAU giữa 2 cách load!")
    print(f"   Version 1: {simulated_keys_v1[0][:20]}...")
    print(f"   Version 2: {simulated_keys_v2[0][:20]}...")

print()

# =====================================
# RECOMMENDATIONS
# =====================================
print("="*80)
print("💡 HƯỚNG DẪN TROUBLESHOOTING")
print("="*80)
print()

print("🔧 ĐỂ VERIFY KEY_MANAGER ĐANG DÙNG KEY GÌ:")
print()
print("1️⃣ Check logs khi agent khởi động:")
print("   python manage.py runserver")
print("   → Tìm dòng: 'Key Manager initialized with X keys'")
print()
print("2️⃣ Thêm logging vào key_manager:")
print("   # Trong ai_models/gemini/key_manager.py")
print("   logger.info(f'📊 Loaded {len(self.keys)} keys')")
print("   for i, key in enumerate(self.keys):")
print("       logger.info(f'   {i+1}. {key[:10]}...{key[-6:]}')")
print()
print("3️⃣ Test trực tiếp:")
print("   python manage.py shell")
print("   >>> from ai_models.gemini.key_manager import GeminiApiKeyManager")
print("   >>> km = GeminiApiKeyManager()")
print("   >>> print(f'Keys: {len(km.keys)}')")
print("   >>> print(f'First key: {km.keys[0][:20]}')")
print()
print("4️⃣ Verify agent đang dùng key gì:")
print("   # Trong agent_system/core/agent.py")
print("   # Method __init__ dòng ~105")
print("   logger.info(f'🔑 Using API key: {self.gemini_api_key[:20]}...')")
print()
print("5️⃣ Force clear cache:")
print("   # Xóa tất cả cached executors")
print("   # Restart Django server")
print("   # Clear browser cache")
print()
print("="*80)
print("✅ SCRIPT COMPLETED")
print("="*80)
print()
print(f"📊 Kết quả: Tìm thấy {len(keys_from_file)} keys trong file .env")
if actual_keys:
    print(f"🔑 Key đầu tiên (masked): {keys_from_file[actual_keys[0]][:20]}...")
else:
    print("🔑 Key đầu tiên: N/A")
