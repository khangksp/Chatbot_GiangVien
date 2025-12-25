import csv
import io
import time
from datetime import datetime
from django.conf import settings
from django.utils import timezone
import logging
import pandas as pd

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials

# Import models ở đây để tránh circular import trong các hàm
from .models import QAEntry, QASyncLog

logger = logging.getLogger(__name__)

# Helper function to safely log messages with emoji support
def safe_log(level, message, *args, **kwargs):
    """Safely log messages, handling encoding errors for emoji"""
    try:
        getattr(logger, level)(message, *args, **kwargs)
    except (UnicodeEncodeError, UnicodeError):
        # Fallback: remove emoji and log plain text
        import re
        # Remove common emoji patterns
        plain_message = re.sub(r'[🚀✅📁📥❌⚠️📋📢📝📊🗑️]', '', message)
        getattr(logger, level)(plain_message, *args, **kwargs)

class GoogleDriveService:
    """
    Service hợp nhất để tương tác với Google Drive,
    hỗ trợ cả "My Drive" và "Shared Drives" (Bộ nhớ dùng chung).
    FIXED VERSION - Proper Shared Drive support
    """

    def __init__(self):
        self.service = None
        # ✅ HỢP NHẤT LOGIC: Đọc toàn bộ config từ settings.py
        drive_config = getattr(settings, 'GOOGLE_DRIVE', {})
        
        self.drive_id = drive_config.get('DRIVE_ID') # ID của Shared Drive
        self.folder_id = drive_config.get('FOLDER_ID') # ID của thư mục bên trong
        self.csv_filename = drive_config.get('CSV_FILENAME', 'QA.csv')
        self.service_account_file = drive_config.get('SERVICE_ACCOUNT_FILE')
        self.scopes = drive_config.get('SCOPES', ['https://www.googleapis.com/auth/drive'])
        
        self._authenticate()
        logger.info(f"GoogleDriveService initialized. Shared Drive ID: {self.drive_id}")

    def _authenticate(self):
        """Xác thực với Google Drive API với quyền đọc và ghi."""
        try:
            if not self.service_account_file or not self.service_account_file.exists():
                logger.error(f"Service account file not found: {self.service_account_file}")
                return False
            
            credentials = Credentials.from_service_account_file(
                str(self.service_account_file), scopes=self.scopes
            )
            self.service = build('drive', 'v3', credentials=credentials)
            logger.info("Google Drive authentication successful (with write permissions)")
            return True
        except Exception as e:
            logger.error(f"Google Drive authentication failed: {str(e)}")
            self.service = None
            return False

    def _find_csv_file(self, filename=None): # ✅ NÂNG CẤP: Thêm tham số filename
        """Tìm file CSV, hỗ trợ cả Shared Drive. Giờ sẽ tìm file được chỉ định."""
        if not self.service:
            return None
        
        # Dùng filename được truyền vào, nếu không thì mặc định là QA.csv
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
                logger.info(f"Found file: {files[0]['name']} (ID: {files[0]['id']})")
                return files[0]
            else:
                logger.warning(f"File '{target_filename}' not found in folder '{self.folder_id}'")
                return None
        except Exception as e:
            logger.error(f"Error finding file '{target_filename}': {str(e)}")
            return None

    def get_specific_csv_content(self, filename: str) -> str | None:
        """
        Tải và trả về nội dung text của một file CSV cụ thể từ Drive.
        """
        try:
            logger.info(f"🔄 Attempting to get content for '{filename}' from Drive...")
            file_info = self._find_csv_file(filename=filename)
            if not file_info:
                return None
            
            return self._download_csv_content(file_info['id'])
        except Exception as e:
            logger.error(f"❌ Critical error in get_specific_csv_content for '{filename}': {str(e)}")
            return None
    
    def _download_csv_content(self, file_id):
        """Tải nội dung CSV từ Google Drive."""
        try:
            # ✅ FIX: Add supportsAllDrives for download as well
            file_content = self.service.files().get_media(
                fileId=file_id,
                supportsAllDrives=True
            ).execute()
            csv_content = file_content.decode('utf-8')
            logger.info(f"Downloaded CSV content ({len(csv_content)} chars)")
            return csv_content
        except Exception as e:
            logger.error(f"❌ Error downloading CSV: {str(e)}")
            return None

    def _upload_csv_content(self, csv_content, file_id=None):
        """
        Tải nội dung CSV lên Google Drive.
        ✅ FIXED: Add supportsAllDrives=True for Shared Drive support
        """
        try:
            media_body = MediaIoBaseUpload(
                io.BytesIO(csv_content.encode('utf-8')),
                mimetype='text/csv',
                resumable=True
            )
            
            if file_id:
                # ✅ CRITICAL FIX: Add supportsAllDrives=True
                updated_file = self.service.files().update(
                    fileId=file_id, 
                    media_body=media_body,
                    supportsAllDrives=True  # ✅ This was missing!
                ).execute()
                logger.info(f"✅ Updated existing file: {updated_file.get('name')} (ID: {file_id})")
                return updated_file
            else:
                file_metadata = {'name': self.csv_filename, 'parents': [self.folder_id]}
                # ✅ CRITICAL FIX: Add supportsAllDrives=True
                new_file = self.service.files().create(
                    body=file_metadata, 
                    media_body=media_body, 
                    fields='id,name',
                    supportsAllDrives=True  # ✅ This was missing!
                ).execute()
                logger.info(f"✅ Created new file: {new_file.get('name')} (ID: {new_file.get('id')})")
                return new_file
        except Exception as e:
            logger.error(f"❌ Error uploading CSV: {str(e)}")
            return None

    def _csv_to_database_format(self, csv_content):
        """Phân tích CSV và trả về dữ liệu có cấu trúc."""
        try:
            if not csv_content or len(csv_content.strip()) < 10:
                logger.error("❌ CSV content is empty or too short")
                return []

            df = pd.read_csv(io.StringIO(csv_content))
            if df.empty:
                logger.error("❌ Parsed DataFrame is empty")
                return []

            required_columns = ['STT', 'question', 'answer']
            if not all(col in df.columns for col in required_columns):
                logger.error(f"❌ Missing required columns. Found: {list(df.columns)}")
                return []

            df = df.fillna('')
            df['STT'] = df['STT'].astype(str).str.strip()
            df['question'] = df['question'].astype(str).str.strip()
            df['answer'] = df['answer'].astype(str).str.strip()
            
            df = df[(df['STT'] != '') & (df['question'] != '') & (df['answer'] != '')]
            if df.empty:
                logger.error("❌ No valid rows found after filtering")
                return []

            entries = []
            for _, row in df.iterrows():
                entries.append({
                    'STT': row['STT'],
                    'question': row['question'],
                    'answer': row['answer'],
                    'category': 'Giảng viên'
                })
            
            logger.info(f"✅ Successfully parsed {len(entries)} valid entries from CSV")
            return entries
        except Exception as e:
            logger.error(f"❌ Error parsing CSV to database format: {str(e)}")
            return []

    def sync_single_entry(self, entry):
        """Đồng bộ một entry duy nhất lên Drive một cách an toàn."""
        try:
            logger.info(f"🔄 Syncing entry {entry.stt} to Drive...")
            file_info = self._find_csv_file()
            if not file_info:
                raise Exception("CSV file not found on Drive")

            existing_csv_content = self._download_csv_content(file_info['id'])
            if not existing_csv_content:
                raise Exception("Could not download existing CSV content")

            existing_entries = self._csv_to_database_format(existing_csv_content)
            if not existing_entries:
                raise Exception("Critical: Failed to parse existing CSV or CSV is empty!")

            new_entry_data = {
                'stt': entry.stt,
                'question': entry.question,
                'answer': entry.answer,
                'category': getattr(entry, 'category', 'Giảng viên'),
            }
            
            merged_entries = existing_entries.copy()
            existing_index = next((i for i, item in enumerate(merged_entries) if item.get('stt') == entry.stt), None)

            if existing_index is not None:
                merged_entries[existing_index] = new_entry_data
            else:
                merged_entries.append(new_entry_data)
            
            if len(merged_entries) < len(existing_entries):
                raise Exception("Critical: Data loss detected during merge!")

            merged_csv_content = self._create_csv_from_entries(merged_entries)

            if self._upload_csv_content(merged_csv_content, file_info['id']):
                entry.sync_status = 'synced'
                entry.last_synced_to_drive = timezone.now()
                entry.save(update_fields=['sync_status', 'last_synced_to_drive'])
                logger.info(f"✅ Successfully synced entry {entry.stt}")
                return True
            else:
                raise Exception("Failed to upload merged CSV")

        except Exception as e:
            logger.error(f"❌ Error syncing entry {entry.stt}: {str(e)}")
            entry.sync_status = 'error'
            entry.save(update_fields=['sync_status'])
            return False

    def get_drive_status(self):
        """Lấy trạng thái kết nối và file trên Google Drive."""
        try:
            if not self.service:
                return {'connected': False, 'error': 'Not authenticated'}
            
            file_info = self._find_csv_file()
            if file_info:
                return {
                    'connected': True,
                    'file_exists': True,
                    'file_id': file_info['id'],
                    'file_name': file_info['name'],
                    'file_size': int(file_info.get('size', 0)),
                    'modified_time': file_info.get('modifiedTime'),
                }
            else:
                return {'connected': True, 'file_exists': False}
        except Exception as e:
            logger.error(f"❌ Error getting Drive status: {str(e)}")
            return {'connected': False, 'error': str(e)}

    def _download_and_parse(self):
        """Tải và phân tích cú pháp CSV từ Google Drive."""
        try:
            file_info = self._find_csv_file()
            if not file_info:
                return []
            
            csv_content = self._download_csv_content(file_info['id'])
            if not csv_content:
                return []
            
            return self._csv_to_database_format(csv_content)
        except Exception as e:
            logger.error(f"❌ Error during download and parse: {str(e)}")
            return []

    def _load_fallback_csv(self):
        """Tải file CSV dự phòng từ local."""
        try:
            local_fallback_path = settings.BASE_DIR / 'data' / 'QA.csv'
            if local_fallback_path.exists():
                df = pd.read_csv(local_fallback_path, encoding='utf-8')
                if 'question' in df.columns and 'answer' in df.columns:
                    df = df.fillna('')
                    if 'category' not in df.columns:
                        df['category'] = 'Giảng viên'
                    data = df.to_dict('records')
                    logger.info(f"🔄 Loaded {len(data)} records from fallback CSV")
                    return data
            logger.warning("⚠️ No fallback data available")
            return []
        except Exception as e:
            logger.error(f"❌ Error loading fallback CSV: {str(e)}")
            return []

    def get_csv_data(self, force_refresh=False):
        """
        Lấy dữ liệu CSV với cơ chế cache thông minh.
        Đây là hàm chính để các service khác gọi vào lấy dữ liệu.
        """
        try:
            logger.info("🔄 Attempting to get QA.csv data from Drive...")
            # Sửa lại để đảm bảo hàm này chỉ gọi file QA.csv mặc định
            file_info = self._find_csv_file() # Không truyền filename để dùng mặc định
            if not file_info:
                 logger.warning("⚠️ QA.csv not found on Drive, trying fallback...")
                 return self._load_fallback_csv()

            csv_content = self._download_csv_content(file_info['id'])
            if not csv_content:
                logger.warning("⚠️ Failed to download QA.csv, trying fallback...")
                return self._load_fallback_csv()
                
            parsed_data = self._csv_to_database_format(csv_content)
            
            if parsed_data:
                logger.info(f"✅ Successfully loaded {len(parsed_data)} records from QA.csv on Drive")
                return parsed_data
            else:
                logger.warning("⚠️ No data from QA.csv on Drive, trying fallback...")
                return self._load_fallback_csv()
                
        except Exception as e:
            logger.error(f"❌ Critical error in get_csv_data: {str(e)}")
            return self._load_fallback_csv()

    def _create_csv_from_entries(self, entries):
        """Helper method to create CSV content from entry list"""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['STT', 'question', 'answer', '', ''])
        for entry in entries:
            writer.writerow([
                entry.get('stt', ''),
                entry.get('question', ''),
                entry.get('answer', ''),
                '',
                ''
            ])
        csv_content = output.getvalue()
        output.close()
        logger.info(f"🔄 Created CSV content with {len(entries)} entries")
        return csv_content

    def _database_to_csv_format(self, entries=None):
        """Convert database entries to CSV format matching Drive structure"""
        if entries is None:
            entries = QAEntry.objects.filter(is_active=True).order_by('stt')
        
        # Convert QAEntry objects to dict format for _create_csv_from_entries
        entry_dicts = []
        for entry in entries:
            entry_dicts.append({
                'stt': entry.stt,
                'question': entry.question,
                'answer': entry.answer,
                'category': getattr(entry, 'category', 'Giảng viên')
            })
        
        return self._create_csv_from_entries(entry_dicts)

    def import_from_drive(self):
        """Import Q&A entries from Google Drive to database"""
        sync_log = QASyncLog.objects.create(operation='import_from_drive', status='partial')
        try:
            logger.info("🔄 Importing data from Google Drive...")
            drive_data = self._download_and_parse()
            
            if not drive_data:
                raise Exception("No valid data found in Drive CSV or failed to download/parse.")
                
            imported_count = 0
            updated_count = 0
            
            for item in drive_data:
                entry, created = QAEntry.objects.update_or_create(
                    stt=item.get('stt'),
                    defaults={
                        'question': item.get('question'),
                        'answer': item.get('answer'),
                        'category': item.get('category', 'Giảng viên'),
                        'sync_status': 'synced',
                        'last_synced_to_drive': timezone.now()
                    }
                )
                if created:
                    imported_count += 1
                else:
                    updated_count += 1
            
            sync_log.status = 'success'
            sync_log.entries_processed = len(drive_data)
            sync_log.entries_success = imported_count + updated_count
            logger.info(f"✅ Import completed: {imported_count} new, {updated_count} updated.")
            return {'success': True, 'imported': imported_count, 'updated': updated_count}

        except Exception as e:
            sync_log.status = 'failed'
            sync_log.error_message = str(e)
            logger.error(f"❌ Import from Drive failed: {str(e)}")
            return {'success': False, 'error': str(e)}
        finally:
            sync_log.completed_at = timezone.now()
            sync_log.save()

    def export_all_to_drive(self):
        """Export all Q&A entries from database to Google Drive"""
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
        """Create a backup of current data before major operations"""
        try:
            entries = QAEntry.objects.filter(is_active=True).order_by('stt')
            csv_content = self._database_to_csv_format(entries)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"QA_backup_{timestamp}.csv"
            
            media_body = MediaIoBaseUpload(io.BytesIO(csv_content.encode('utf-8')), mimetype='text/csv', resumable=True)
            file_metadata = {'name': backup_filename, 'parents': [self.folder_id]}
            
            # ✅ FIX: Add supportsAllDrives for backup creation
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
        """Clear any cached data (for signal integration)"""
        try:
            # Clear internal caches if any
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