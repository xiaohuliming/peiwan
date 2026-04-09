import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app


def _get_ext(filename):
    """安全提取扩展名（不含点），避免 rsplit 越界。"""
    ext = os.path.splitext(str(filename or ''))[1].lower().lstrip('.')
    return ext


IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'}
MAX_IMAGE_SIZE = 512  # 最大边长 (px)，兼顾页面显示和 KOOK 播报清晰度


def allowed_file(filename):
    ext = _get_ext(filename)
    return bool(ext) and ext in current_app.config.get('ALLOWED_EXTENSIONS', set())


def _compress_image(file_obj, output_path, max_size=MAX_IMAGE_SIZE, quality=85):
    """将上传的图片压缩/缩放后保存为 WebP。
    返回实际保存的文件路径（可能改变扩展名为 .webp）。
    """
    try:
        from PIL import Image
        img = Image.open(file_obj)
        # 转换 RGBA/P 模式到 RGB（WebP 不支持所有模式）
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 缩放到 max_size
        img.thumbnail((max_size, max_size), Image.LANCZOS)

        # 保存为 WebP
        webp_path = os.path.splitext(output_path)[0] + '.webp'
        img.save(webp_path, format='WEBP', quality=quality, optimize=True)
        return webp_path
    except ImportError:
        # Pillow 未安装，回退到原样保存
        file_obj.seek(0)
        file_obj.save(output_path)
        return output_path
    except Exception:
        # 任何处理异常都回退
        file_obj.seek(0)
        file_obj.save(output_path)
        return output_path


def save_file(file, subfolder=''):
    """
    保存上传文件。图片类型会自动压缩为 WebP 缩略图。
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
        unique_name = uuid.uuid4().hex
        unique_filename = f"{unique_name}.{ext}"

        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        file_path = os.path.join(upload_folder, unique_filename)

        # 图片类文件 → 压缩后保存
        if ext in IMAGE_EXTENSIONS:
            actual_path = _compress_image(file, file_path)
            actual_name = os.path.basename(actual_path)
        else:
            file.save(file_path)
            actual_name = unique_filename

        # 返回相对路径供前端访问
        relative_path = f"uploads/{subfolder}/{actual_name}" if subfolder else f"uploads/{actual_name}"
        return relative_path, None

    return None, '文件类型不支持'

