import csv
import io
import time
from datetime import datetime
from django.conf import settings
from django.utils import timezone
import logging
import pandas as pd
from django.db import transaction
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials
from django.db.models.signals import post_save, post_delete
from .signals import qa_entry_post_save_handler, qa_entry_post_delete_handler
from collections import defaultdict

from .models import QAEntry, QASyncLog

logger = logging.getLogger(__name__)

class GoogleDriveService:
    def __init__(self):
        self.service = None
        # Đọc toàn bộ config từ settings.py
        drive_config = getattr(settings, 'GOOGLE_DRIVE', {})
        
        self.drive_id = drive_config.get('DRIVE_ID') # ID của Shared Drive
        self.folder_id = drive_config.get('FOLDER_ID') # ID của thư mục bên trong
        self.csv_filename = drive_config.get('CSV_FILENAME', 'QA.csv')
        self.service_account_file = drive_config.get('SERVICE_ACCOUNT_FILE')
        self.scopes = drive_config.get('SCOPES', ['https://www.googleapis.com/auth/drive'])
        
        self._authenticate()
        logger.info(f"🚀 GoogleDriveService initialized. Shared Drive ID: {self.drive_id}")

    def _authenticate(self):
        try:
            if not self.service_account_file or not self.service_account_file.exists():
                logger.error(f"❌ Service account file not found: {self.service_account_file}")
                return False
            
            credentials = Credentials.from_service_account_file(
                str(self.service_account_file), scopes=self.scopes
            )
            self.service = build('drive', 'v3', credentials=credentials)
            logger.info("✅ Google Drive authentication successful (with write permissions)")
            return True
        except Exception as e:
            logger.error(f"❌ Google Drive authentication failed: {str(e)}")
            self.service = None
            return False

    def _find_csv_file(self, filename=None):
        if not self.service:
            return None
        
        target_filename = filename if filename else self.csv_filename
        
        try:
            query = f"name='{target_filename}' and parents in '{self.folder_id}' and trashed=false"
            
            list_params = {
                'q': query,
                'fields': "files(id, name, modifiedTime, size)",
                'supportsAllDrives': True,
                'includeItemsFromAllDrives': True,
            }
            if self.drive_id:
                list_params['driveId'] = self.drive_id
                list_params['corpora'] = 'drive'

            results = self.service.files().list(**list_params).execute()
            files = results.get('files', [])
            
            if files:
                logger.info(f"📁 Found file: {files[0]['name']} (ID: {files[0]['id']})")
                return files[0]
            else:
                logger.warning(f"⚠️ File '{target_filename}' not found in folder '{self.folder_id}'")
                return None
        except Exception as e:
            logger.error(f"❌ Error finding file '{target_filename}': {str(e)}")
            return None

    def get_specific_csv_content(self, filename: str) -> str | None:
        try:
            logger.info(f"🔄 Attempting to get content for '{filename}' from Drive...")
            file_info = self._find_csv_file(filename=filename)
            if not file_info: return None
            return self._download_csv_content(file_info['id'])
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return None
    
    def _download_csv_content(self, file_id):
        try:
            file_content = self.service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
            return file_content.decode('utf-8')
        except Exception as e:
            logger.error(f"❌ Error downloading: {str(e)}")
            return None

    def _upload_csv_content(self, csv_content, file_id=None):
        try:
            media_body = MediaIoBaseUpload(io.BytesIO(csv_content.encode('utf-8')), mimetype='text/csv', resumable=True)
            if file_id:
                return self.service.files().update(fileId=file_id, media_body=media_body, supportsAllDrives=True).execute()
            else:
                meta = {'name': self.csv_filename, 'parents': [self.folder_id]}
                return self.service.files().create(body=meta, media_body=media_body, fields='id,name', supportsAllDrives=True).execute()
        except Exception as e:
            logger.error(f"❌ Error uploading: {str(e)}")
            return None

    def _csv_to_database_format(self, csv_content):
        try:
            if not csv_content or len(csv_content.strip()) < 10: return []
            df = pd.read_csv(io.StringIO(csv_content), dtype=str)
            if df.empty: return []
            df.columns = df.columns.str.strip()
            required = ['STT', 'question', 'answer']
            if not all(col in df.columns for col in required): return []
            df = df.fillna('')
            df = df[(df['STT'].str.strip() != '') | (df['question'].str.strip() != '')]
            entries = []
            for _, row in df.iterrows():
                entries.append({
                    'STT': str(row['STT']).strip(),
                    'question': str(row['question']).strip(),
                    'answer': str(row['answer']).strip(),
                    'category': str(row.get('category', 'Giảng viên')).strip()
                })
            return entries
        except Exception as e:
            logger.error(f"❌ Error parsing: {str(e)}")
            return []

    def sync_batch_entries(self, entries_list):
        try:
            entries = list(entries_list) if hasattr(entries_list, '__iter__') else [entries_list]
            count = len(entries)
            logger.info(f"🔄 Starting batch sync for {count} entries...")

            # 1. Tìm và tải file hiện tại
            file_info = self._find_csv_file()
            existing_entries = []
            file_id = None

            if file_info:
                file_id = file_info['id']
                content = self._download_csv_content(file_id)
                if content:
                    existing_entries = self._csv_to_database_format(content)
            
            # 2. Backup nếu dữ liệu bất thường (optional logic)
            if len(existing_entries) > 100 and len(existing_entries) > count * 10:
                 pass

            # 3. Tạo Map để tra cứu nhanh.
            # ⚠️ QUAN TRỌNG: Dùng (STT + Question) làm key để phân biệt các câu hỏi khác nhau trong cùng 1 STT
            entry_map = {}
            for i, item in enumerate(existing_entries):
                # Tạo composite key: (STT chuẩn hóa, Câu hỏi chuẩn hóa)
                key = (str(item['STT']).strip(), str(item['question']).strip())
                entry_map[key] = i
            
            merged_entries = existing_entries.copy()
            
            # 4. Cập nhật hoặc thêm mới
            for entry in entries:
                entry_stt = str(entry.stt).strip()
                entry_question = str(entry.question).strip()
                
                # Key để tìm kiếm
                key = (entry_stt, entry_question)
                
                new_data = {
                    'STT': entry_stt,
                    'question': entry_question,
                    'answer': entry.answer,
                    'category': getattr(entry, 'category', 'Giảng viên'),
                }

                if key in entry_map:
                    # ✅ Case 1: Trùng cả STT và Câu hỏi -> Cập nhật (Sửa câu trả lời)
                    idx = entry_map[key]
                    merged_entries[idx] = new_data
                    logger.info(f"✏️ Updated existing entry: {entry_stt} - {entry_question[:20]}...")
                else:
                    # ✅ Case 2: Cùng STT nhưng Câu hỏi khác (hoặc STT mới) -> Thêm mới (Append)
                    merged_entries.append(new_data)
                    # Update map luôn để nếu trong batch có 2 câu giống hệt nhau thì câu sau đè câu trước
                    entry_map[key] = len(merged_entries) - 1
                    logger.info(f"➕ Appended new entry: {entry_stt} - {entry_question[:20]}...")
            
            # 5. Tạo nội dung CSV mới
            merged_csv_content = self._create_csv_from_entries(merged_entries)

            # 6. Upload lên Drive
            result_file = self._upload_csv_content(merged_csv_content, file_id)
            
            if result_file:
                # Cập nhật trạng thái DB
                now = timezone.now()
                QAEntry.objects.filter(pk__in=[e.pk for e in entries]).update(
                    sync_status='synced',
                    last_synced_to_drive=now
                )
                logger.info(f"✅ Batch sync completed. Total entries on Drive: {len(merged_entries)}")
                return {'success': True, 'count': len(entries)}
            else:
                raise Exception("Failed to upload merged CSV content")

        except Exception as e:
            logger.error(f"❌ Batch sync failed: {str(e)}")
            if isinstance(entries_list, (list, tuple)) or hasattr(entries_list, 'update'):
                 QAEntry.objects.filter(pk__in=[e.pk for e in entries]).update(sync_status='error')
            return {'success': False, 'error': str(e)}

    def sync_single_entry(self, entry):
        try:
            result = self.sync_batch_entries([entry])
            return result['success']
        except: return False

    def get_drive_status(self):
        try:
            if not self.service: return {'connected': False}
            info = self._find_csv_file()
            if info: return {'connected': True, 'file_exists': True, 'file_name': info['name']}
            return {'connected': True, 'file_exists': False}
        except Exception as e: return {'connected': False, 'error': str(e)}

    def _download_and_parse(self):
        info = self._find_csv_file()
        if not info: return []
        content = self._download_csv_content(info['id'])
        return self._csv_to_database_format(content) if content else []

    def _load_fallback_csv(self):
        try:
            path = settings.BASE_DIR / 'data' / 'QA.csv'
            if path.exists():
                df = pd.read_csv(path, encoding='utf-8', dtype=str).fillna('')
                if 'category' not in df.columns: df['category'] = 'Giảng viên'
                return df.to_dict('records')
            return []
        except: return []

    def get_csv_data(self, force_refresh=False):
        try:
            info = self._find_csv_file()
            if not info: return self._load_fallback_csv()
            content = self._download_csv_content(info['id'])
            return self._csv_to_database_format(content) if content else self._load_fallback_csv()
        except: return self._load_fallback_csv()

    def _create_csv_from_entries(self, entries_dicts):
        """Helper method to create CSV content from list of dicts"""
        output = io.StringIO()
        writer = csv.writer(output)
        # Header chuẩn
        writer.writerow(['STT', 'question', 'answer', 'category'])
        
        for entry in entries_dicts:
            writer.writerow([
                entry.get('STT', ''), # Chú ý key map 'STT' viết hoa
                entry.get('question', ''),
                entry.get('answer', ''),
                entry.get('category', 'Giảng viên')
            ])
        
        csv_content = output.getvalue()
        output.close()
        logger.info(f"🔄 Created CSV content with {len(entries_dicts)} entries")
        return csv_content
    
    def _create_csv_from_entries(self, entries):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['STT', 'question', 'answer', 'category'])
        for e in entries:
            writer.writerow([e.get('STT',''), e.get('question',''), e.get('answer',''), e.get('category','Giảng viên')])
        return out.getvalue()
    
    def _database_to_csv_format(self, entries=None):
        if entries is None: entries = QAEntry.objects.filter(is_active=True).order_by('stt')
        return self._create_csv_from_entries([{'STT':str(e.stt), 'question':e.question, 'answer':e.answer, 'category':getattr(e,'category','Giảng viên')} for e in entries])

    def import_from_drive(self):
        sync_log = QASyncLog.objects.create(operation='import_from_drive', status='partial')
        
        # 🛑 1. Ngắt tín hiệu để tránh bão log
        post_save.disconnect(qa_entry_post_save_handler, sender=QAEntry)
        post_delete.disconnect(qa_entry_post_delete_handler, sender=QAEntry)
        
        try:
            logger.info("🔄 Importing data from Google Drive (Smart Sync Mode)...")
            drive_data = self._download_and_parse()
            
            if not drive_data:
                raise Exception("No valid data found in Drive CSV")
            db_map = defaultdict(list)
            all_db_entries = QAEntry.objects.all()
            for entry in all_db_entries:
                # Key chuẩn hóa: xóa khoảng trắng thừa
                key = (entry.question.strip(), entry.answer.strip())
                db_map[key].append(entry)
            
            initial_count = len(all_db_entries)
            to_create = []
            to_update = []
            reused_ids = set() # Những ID được giữ lại
            now = timezone.now()

            for item in drive_data:
                q_raw = str(item.get('question', '')).strip()
                a_raw = str(item.get('answer', '')).strip()
                stt_raw = str(item.get('STT', '')).strip()
                cat_raw = item.get('category', 'Giảng viên')
                
                if not q_raw or not a_raw: continue

                key = (q_raw, a_raw)
                
                if db_map[key]:
                    # ✅ TÌM THẤY: Tái sử dụng entry cũ
                    entry = db_map[key].pop(0) # Lấy ra và xóa khỏi list chờ để không dùng lại cho dòng khác
                    reused_ids.add(entry.id)
                    
                    # Kiểm tra xem có cần update thông tin phụ (STT, Category) không
                    if entry.stt != stt_raw or entry.category != cat_raw:
                        entry.stt = stt_raw
                        entry.category = cat_raw
                        entry.sync_status = 'synced'
                        entry.last_synced_to_drive = now
                        to_update.append(entry)
                    else:
                        # Nếu y hệt 100% thì chỉ cần update timestamp sync (hoặc bỏ qua để tối ưu)
                        pass 
                else:
                    # 🆕 KHÔNG THẤY: Tạo mới
                    to_create.append(QAEntry(
                        stt=stt_raw,
                        question=q_raw,
                        answer=a_raw,
                        category=cat_raw,
                        sync_status='synced',
                        last_synced_to_drive=now,
                        is_active=True
                    ))
            
            # Những entry còn sót lại trong db_map là những cái không có trong Drive -> Cần Xóa
            to_delete_ids = []
            for key, entries in db_map.items():
                for entry in entries:
                    to_delete_ids.append(entry.id)

            # --- GIAI ĐOẠN 3: Thực thi Database ---
            with transaction.atomic():
                # 1. Xóa thừa
                if to_delete_ids:
                    QAEntry.objects.filter(id__in=to_delete_ids).delete()
                    logger.info(f"🗑️ Smart delete: {len(to_delete_ids)} old entries removed.")
                
                # 2. Thêm mới
                if to_create:
                    QAEntry.objects.bulk_create(to_create, batch_size=1000)
                    logger.info(f"✨ Smart create: {len(to_create)} new entries added.")
                
                # 3. Cập nhật (những cái đổi STT/Category)
                if to_update:
                    QAEntry.objects.bulk_update(
                        to_update, 
                        ['stt', 'category', 'sync_status', 'last_synced_to_drive'],
                        batch_size=1000
                    )
                    logger.info(f"📝 Smart update: {len(to_update)} entries metadata updated.")

            # Kết quả
            final_count = len(reused_ids) + len(to_create)
            sync_log.status = 'success'
            sync_log.entries_processed = len(drive_data)
            sync_log.entries_success = final_count
            
            msg = f"Đồng bộ xong: {len(to_create)} mới, {len(to_update)} cập nhật, {len(to_delete_ids)} xóa. (Tổng: {final_count})"
            logger.info(f"✅ {msg}")
            
            return {
                'success': True, 
                'imported': len(to_create), 
                'updated': len(to_update),
                'deleted': len(to_delete_ids),
                'message': msg
            }

        except Exception as e:
            sync_log.status = 'failed'
            sync_log.error_message = str(e)
            logger.error(f"❌ Import failed: {str(e)}")
            return {'success': False, 'error': str(e)}
        finally:
            # 🔌 Bật lại tín hiệu
            post_save.connect(qa_entry_post_save_handler, sender=QAEntry)
            post_delete.connect(qa_entry_post_delete_handler, sender=QAEntry)
            
            sync_log.completed_at = timezone.now()
            sync_log.save()

    def export_all_to_drive(self):
        sync_log = QASyncLog.objects.create(operation='export_to_drive', status='partial')
        try:
            entries = QAEntry.objects.filter(is_active=True).order_by('stt')
            if not entries.exists():
                raise Exception('No active entries to export')
            csv_content = self._database_to_csv_format(entries)
            file_info = self._find_csv_file()
            file_id = file_info['id'] if file_info else None
            
            upload_result = self._upload_csv_content(csv_content, file_id)
            if not upload_result:
                raise Exception('Failed to upload CSV to Drive')

            updated_count = entries.update(sync_status='synced', last_synced_to_drive=timezone.now())
            sync_log.status = 'success'
            sync_log.entries_success = updated_count
            logger.info(f"✅ Export completed: {updated_count} entries synced to Drive")
            return {'success': True, 'total_entries': updated_count}

        except Exception as e:
            sync_log.status = 'failed'
            sync_log.error_message = str(e)
            logger.error(f"❌ Export failed: {str(e)}")
            return {'success': False, 'error': str(e)}
        finally:
            sync_log.completed_at = timezone.now()
            sync_log.save()

    def backup_current_data(self):
        try:
            entries = QAEntry.objects.filter(is_active=True).order_by('stt')
            csv_content = self._database_to_csv_format(entries)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"QA_backup_{timestamp}.csv"
            
            media_body = MediaIoBaseUpload(io.BytesIO(csv_content.encode('utf-8')), mimetype='text/csv', resumable=True)
            file_metadata = {'name': backup_filename, 'parents': [self.folder_id]}
            
            backup_file = self.service.files().create(
                body=file_metadata, 
                media_body=media_body, 
                fields='id,name',
                supportsAllDrives=True
            ).execute()
            
            logger.info(f"✅ Backup created: {backup_filename}")
            return {'success': True, 'backup_filename': backup_filename}
        except Exception as e:
            logger.error(f"❌ Error creating backup: {str(e)}")
            return {'success': False, 'error': str(e)}

    def clear_cache(self):
        try:
            if hasattr(self, '_cached_data'):
                self._cached_data = None
            if hasattr(self, '_cache_timestamp'):
                self._cache_timestamp = 0
            logger.info("🗑️ Google Drive service cache cleared")
        except Exception as e:
            logger.error(f"❌ Error clearing cache: {str(e)}")
    
    def get_system_status(self):
        return {
            'service_name': 'GoogleDriveService',
            'authenticated': self.service is not None,
            'shared_drive_id': self.drive_id
        }
    
drive_service = GoogleDriveService()