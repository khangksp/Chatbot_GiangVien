#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script để tạo cây thư mục của dự án ChatBotStudent
Bỏ qua node_modules, .venv, __pycache__, athenaeum
"""
import os
from pathlib import Path

def should_skip(path):
    """Kiểm tra xem có nên bỏ qua thư mục này không"""
    skip_patterns = [
        'node_modules',
        '.venv',
        '__pycache__',
        '.git',
        'athenaeum',
        '.pytest_cache',
        'venv',
        'env',
        'dist',
        'build',
        '.next',
        '.cache'
    ]
    path_str = str(path).replace('\\', '/')
    for pattern in skip_patterns:
        if pattern in path_str:
            return True
    return False

def print_tree(root_path, prefix="", is_last=True, max_depth=4, current_depth=0, output_lines=None):
    """In cây thư mục"""
    if output_lines is None:
        output_lines = []
    
    if current_depth > max_depth:
        return output_lines
    
    root = Path(root_path)
    if not root.exists():
        return output_lines
    
    # Lấy tên thư mục/file
    name = root.name if root.name else str(root)
    
    # Bỏ qua các thư mục cần skip
    if should_skip(root):
        return output_lines
    
    # Vẽ cây
    connector = "└── " if is_last else "├── "
    line = prefix + connector + name
    output_lines.append(line)
    
    # Nếu là file hoặc đã đạt max_depth thì dừng
    if root.is_file() or current_depth >= max_depth:
        return output_lines
    
    # Lấy danh sách con, sắp xếp và lọc
    try:
        children = sorted([p for p in root.iterdir() if not should_skip(p)])
        if not children:
            return output_lines
        
        # Loại bỏ các file không quan trọng ở level đầu
        if current_depth == 0:
            important_dirs = ['backend', 'frontend', 'api_list.txt', 'README.md', 
                            'STUDENT_INTEGRATION_SUMMARY.md', 'docker-compose.yml']
            children = [p for p in children if p.name in important_dirs or p.is_dir()]
        
        for i, child in enumerate(children):
            is_last_child = (i == len(children) - 1)
            extension = "    " if is_last else "│   "
            new_prefix = prefix + extension
            print_tree(child, new_prefix, is_last_child, max_depth, current_depth + 1, output_lines)
    except PermissionError:
        pass
    
    return output_lines

if __name__ == "__main__":
    import sys
    
    project_root = Path(__file__).parent
    
    # Tạo cây thư mục
    tree_lines = print_tree(project_root, max_depth=6)
    
    # Tạo nội dung đầy đủ
    content = []
    content.append("Cau truc du an ChatBotStudent")
    content.append("")
    content.append("=" * 60)
    content.extend(tree_lines)
    content.append("=" * 60)
    content.append("")
    content.append("Luu y: Da bo qua node_modules, .venv, __pycache__, athenaeum")
    
    # In ra console với encoding UTF-8
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    for line in content:
        print(line)
    
    # Ghi vào file với encoding UTF-8
    output_file = project_root / "PROJECT_TREE.txt"
    try:
        with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(content))
        print(f"\n✅ Đã lưu cây thư mục vào: {output_file}")
    except Exception as e:
        print(f"\n❌ Lỗi khi ghi file: {e}")

