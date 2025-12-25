"""
News Tool - Student News API
Tool để lấy tin tức mới nhất từ BDU Student Portal
Hỗ trợ: List tin, extract links, format đẹp, ưu tiên tin ghim
"""
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base_tool import BDUBaseTool

logger = logging.getLogger(__name__)


class StudentNewsTool(BDUBaseTool):
    """
    Tool to get latest student news from BDU Portal
    Lấy tin tức mới nhất cho sinh viên
    """
    
    name: str = "get_student_news"
    description: str = """Lấy tin tức và thông báo mới nhất từ Trường Đại học Bình Dương.
    
    Sử dụng tool này khi sinh viên hỏi:
    - "Tin tức mới nhất"
    - "Có thông báo gì không?"
    - "Tin tức trường"
    - "Thông báo từ nhà trường"
    - "Có gì mới không?"
    - "Tin tức về [chủ đề]"
    
    Tool này sẽ:
    - Hiển thị 5-10 tin mới nhất
    - Ưu tiên tin ghim (quan trọng) lên đầu
    - Hiển thị theo danh mục (Đào tạo, Thông báo, Sự kiện...)
    - Tự động extract links đính kèm
    - Format dễ đọc với emoji
    
    Input: Câu hỏi (có thể chứa từ khóa hoặc không)
    Output: Danh sách tin tức với tóm tắt và links
    
    Ví dụ:
    - "Tin tức mới nhất" → Hiển thị 5 tin mới nhất
    - "Thông báo về đào tạo" → Hiển thị tin trong category "Đào tạo"
    - "Có tin gì về điểm rèn luyện không?" → Tìm tin liên quan
    """
    
    category: str = "student_api"
    requires_auth: bool = False  # Tin tức là public
    
    # Injected dependencies
    api_service: Optional[Any] = None
    
    # Configuration
    default_limit: int = 5  # Số tin mặc định
    max_limit: int = 10     # Số tin tối đa
    
    class Config:
        arbitrary_types_allowed = True
    
    def execute(self, query: str = "") -> str:
        """
        Execute news fetching
        
        Args:
            query: User's question (có thể chứa keywords)
            
        Returns:
            Formatted news list
        """
        if not self.api_service:
            return "❌ API service not initialized"
        
        try:
            logger.info(f"📰 Fetching student news (query: '{query}')")
            
            # Determine how many news to fetch
            limit = self._determine_limit(query)
            
            # Call API - FIX: Sử dụng đúng parameters
            result = self.api_service.get_student_news(
                jwt_token=self.jwt_token or "",  # Token có thể None nếu public
                page=1,
                page_size=limit,
                category=None  # TODO: Extract category from query if needed
            )
            
            if not result or not result.get("ok"):
                reason = result.get("error", "Unknown") if result else "No response"
                logger.error(f"❌ News API failed: {reason}")
                return f"❌ Không thể lấy tin tức. Lý do: {reason}"
            
            news_list = result.get("data", [])
            
            if not news_list:
                return "📰 Hiện tại chưa có tin tức mới nào."
            
            logger.info(f"✅ Fetched {len(news_list)} news items")
            
            # Filter by keyword if query contains specific terms
            filtered_news = self._filter_news_by_query(news_list, query)
            
            # Format response
            response = self._format_news_list(filtered_news, query)
            
            return response
            
        except Exception as e:
            logger.error(f"❌ News Tool error: {str(e)}", exc_info=True)
            return f"Đã xảy ra lỗi khi lấy tin tức: {str(e)}"
    
    def _determine_limit(self, query: str) -> int:
        """
        Determine how many news items to fetch based on query
        
        Args:
            query: User query
            
        Returns:
            Number of items to fetch
        """
        query_lower = query.lower()
        
        # If user asks for "all" or "tất cả"
        if any(word in query_lower for word in ["tất cả", "tat ca", "all", "hết", "het"]):
            return self.max_limit
        
        # If user asks for specific number (e.g., "5 tin", "10 bài")
        number_match = re.search(r'(\d+)\s*(?:tin|bài|thông báo)', query_lower)
        if number_match:
            num = int(number_match.group(1))
            return min(num, self.max_limit)
        
        # Default
        return self.default_limit
    
    def _filter_news_by_query(self, news_list: List[Dict], query: str) -> List[Dict]:
        """
        Filter news by query keywords
        
        Args:
            news_list: List of news items
            query: User query
            
        Returns:
            Filtered news list (or original if no specific filter)
        """
        if not query or len(query.strip()) < 3:
            return news_list
        
        query_lower = query.lower()
        
        # Keywords to ignore (generic words)
        ignore_words = {
            "tin", "tức", "thông", "báo", "mới", "nhất", "có", "gì", "không",
            "hỏi", "xem", "cho", "tôi", "mình", "em", "của", "về", "trường"
        }
        
        # Extract meaningful keywords
        keywords = []
        for word in query_lower.split():
            word_clean = re.sub(r'[^\w\s]', '', word)
            if len(word_clean) > 2 and word_clean not in ignore_words:
                keywords.append(word_clean)
        
        # If no meaningful keywords, return all
        if not keywords:
            return news_list
        
        logger.info(f"🔍 Filtering news by keywords: {keywords}")
        
        # Filter news containing keywords in title or plain text
        filtered = []
        for news in news_list:
            title = (news.get('title', '') or '').lower()
            plain = (news.get('plain', '') or '').lower()
            category = (news.get('category', '') or '').lower()
            
            # Check if any keyword matches
            if any(kw in title or kw in plain or kw in category for kw in keywords):
                filtered.append(news)
        
        # If filter too strict (no results), return all
        if not filtered:
            logger.info("ℹ️ No filtered results, returning all news")
            return news_list
        
        logger.info(f"✅ Filtered to {len(filtered)} relevant news")
        return filtered
    
    def _format_news_list(self, news_list: List[Dict], query: str = "") -> str:
        """
        Format news list for display
        
        Args:
            news_list: List of news items (already sorted by API)
            query: Original query for context
            
        Returns:
            Formatted string
        """
        response = "📰 **Tin tức mới nhất - Trường Đại học Bình Dương**\n\n"
        
        # Separate pinned and normal news
        pinned_news = [n for n in news_list if n.get('is_pinned', False)]
        normal_news = [n for n in news_list if not n.get('is_pinned', False)]
        
        # Display pinned news first
        for idx, news in enumerate(pinned_news, 1):
            response += self._format_single_news(news, is_pinned=True, index=idx)
        
        # Display normal news
        start_idx = len(pinned_news) + 1
        for idx, news in enumerate(normal_news, start_idx):
            response += self._format_single_news(news, is_pinned=False, index=idx)
        
        # Footer
        total_count = len(news_list)
        if query and len(query.strip()) > 3:
            response += f"\n💡 Tìm thấy {total_count} tin tức liên quan đến '{query}'."
        else:
            response += f"\n💡 Hiển thị {total_count} tin tức mới nhất."
        
        response += "\n📌 Tin có biểu tượng ghim là tin quan trọng từ nhà trường."
        
        return response
    
    def _format_single_news(self, news: Dict, is_pinned: bool = False, index: int = 1) -> str:
        """
        Format a single news item
        
        Args:
            news: News item dict
            is_pinned: Whether this is a pinned news
            index: Display index
            
        Returns:
            Formatted string
        """
        # Extract data
        title = news.get('title', 'Không có tiêu đề')
        category = news.get('category', '')
        date_str = news.get('date', '')
        time_str = news.get('time', '')
        plain_text = news.get('plain', '')
        html_content = news.get('html', '')
        
        # Format date
        date_display = self._format_date(date_str, time_str)
        
        # Category emoji
        category_emoji = self._get_category_emoji(category)
        
        # Pin indicator
        pin_indicator = "📌 " if is_pinned else "🔔 "
        
        # Build response
        response = f"{pin_indicator}**{index}. [{category}] {title}**\n"
        response += f"   📅 {date_display}\n"
        
        # Add summary (plain text - already cleaned by API)
        if plain_text:
            # Truncate if too long
            summary = plain_text[:200].strip()
            if len(plain_text) > 200:
                summary += "..."
            response += f"   💬 {summary}\n"
        
        # Extract and display links
        links = self._extract_links(html_content)
        if links:
            response += f"   🔗 Links:\n"
            for link in links[:3]:  # Max 3 links
                link_title = link.get('title', 'Link')
                link_url = link.get('url', '')
                response += f"      • {link_title}: {link_url}\n"
        
        response += "\n"
        
        return response
    
    def _format_date(self, date_str: str, time_str: str) -> str:
        """
        Format date and time to Vietnamese format
        
        Args:
            date_str: Date string (YYYY-MM-DD)
            time_str: Time string (HH:MM)
            
        Returns:
            Formatted date string
        """
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            
            # Vietnamese weekdays
            weekdays = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật']
            weekday = weekdays[date_obj.weekday()]
            
            # Format: "Thứ 2, 15/11/2025 lúc 07:00"
            date_formatted = f"{weekday}, {date_obj.strftime('%d/%m/%Y')}"
            
            if time_str and time_str != "00:00":
                date_formatted += f" lúc {time_str}"
            
            return date_formatted
            
        except Exception as e:
            logger.warning(f"Date formatting error: {e}")
            return f"{date_str} {time_str}"
    
    def _get_category_emoji(self, category: str) -> str:
        """
        Get emoji for category
        
        Args:
            category: News category
            
        Returns:
            Emoji string
        """
        category_lower = category.lower()
        
        emoji_map = {
            'đào tạo': '📚',
            'dao tao': '📚',
            'thông báo': '📢',
            'thong bao': '📢',
            'sự kiện': '🎉',
            'su kien': '🎉',
            'event': '🎉',
            'tuyển sinh': '🎓',
            'tuyen sinh': '🎓',
            'học phí': '💰',
            'hoc phi': '💰',
            'khen thưởng': '🏆',
            'khen thuong': '🏆',
            'scholarship': '🏆',
        }
        
        for key, emoji in emoji_map.items():
            if key in category_lower:
                return emoji
        
        return '📰'  # Default
    
    def _extract_links(self, html: str) -> List[Dict[str, str]]:
        """
        Extract links from HTML content
        
        Args:
            html: HTML content
            
        Returns:
            List of links with title and url
        """
        if not html:
            return []
        
        links = []
        
        # Pattern: <a href="URL" ...>TITLE</a>
        # Pattern for links: href="..." and title in text
        link_pattern = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        
        matches = re.finditer(link_pattern, html, re.IGNORECASE | re.DOTALL)
        
        for match in matches:
            url = match.group(1).strip()
            title_html = match.group(2).strip()
            
            # Clean title (remove HTML tags)
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            
            # Skip empty or invalid
            if not url or url.startswith('#') or url == '':
                continue
            
            # Clean title
            if not title or title == '':
                # Try to infer from URL
                if 'drive.google.com' in url:
                    title = "Xem tài liệu"
                elif '.pdf' in url.lower():
                    title = "Tải file PDF"
                elif '.xlsx' in url.lower() or '.xls' in url.lower():
                    title = "Tải file Excel"
                elif '.docx' in url.lower() or '.doc' in url.lower():
                    title = "Tải file Word"
                else:
                    title = "Link đính kèm"
            
            links.append({
                'title': title,
                'url': url
            })
        
        return links
    
    def set_api_service(self, service):
        """Set API service instance"""
        self.api_service = service


class StudentNewsDetailTool(BDUBaseTool):
    """
    Tool to get detailed news content by ID
    [RESERVED FOR FUTURE - Phase 2]
    """
    
    name: str = "get_news_detail"
    description: str = """[COMING SOON] Xem chi tiết nội dung đầy đủ của một tin tức."""
    
    category: str = "student_api"
    requires_auth: bool = True
    
    def execute(self, query: str = "") -> str:
        return "⚠️ Tính năng này đang được phát triển."
    
    class Config:
        arbitrary_types_allowed = True