import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app


def _get_ext(filename):
    """安全提取扩展名（不含点），避免 rsplit 越界。"""
    ext = os.path.splitext(str(filename or ''))[1].lower().lstrip('.')
    return ext


def allowed_file(filename):
    ext = _get_ext(filename)
    return bool(ext) and ext in current_app.config.get('ALLOWED_EXTENSIONS', set())

def save_file(file, subfolder=''):
    """
    保存上传文件
    :param file: 文件对象
    :param subfolder: 子目录 (e.g. 'avatars', 'gifts')
    :return: 相对路径 URL, 错误信息
    """
    if file.filename == '':
        return None, '没有选择文件'
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # 生成唯一文件名
        ext = _get_ext(file.filename) or _get_ext(filename)
        if not ext:
            return None, '文件扩展名无效'
        unique_filename = f"{uuid.uuid4().hex}.{ext}"
        
        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        # 返回相对路径供前端访问
        relative_path = f"uploads/{subfolder}/{unique_filename}" if subfolder else f"uploads/{unique_filename}"
        return relative_path, None
    
    return None, '文件类型不支持'
