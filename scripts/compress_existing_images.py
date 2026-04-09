#!/usr/bin/env python3
"""
一次性脚本: 压缩 static/uploads/ 下的所有已有图片为 WebP 缩略图。
用法: python scripts/compress_existing_images.py

- 将大图缩放到 256x256 以内
- 转换为 WebP 格式 (质量 85)
- 原文件重命名为 .bak 备份
- 更新数据库中引用的路径 (Gift.image)
"""
import os
import sys

# 让脚本可以在项目根目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'static', 'uploads')
MAX_SIZE = 512
QUALITY = 85
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}


def compress_image(src_path):
    """压缩单张图片, 返回新路径或 None"""
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in IMAGE_EXTS:
        return None
    if ext == '.webp':
        # 已经是 webp, 检查尺寸
        img = Image.open(src_path)
        if max(img.size) <= MAX_SIZE:
            print(f"  跳过 (已是小尺寸 WebP): {src_path}")
            return None

    try:
        img = Image.open(src_path)
        original_size = os.path.getsize(src_path)

        # 模式转换
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 缩放
        img.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)

        # 保存为 webp
        webp_path = os.path.splitext(src_path)[0] + '.webp'
        img.save(webp_path, format='WEBP', quality=QUALITY, optimize=True)
        new_size = os.path.getsize(webp_path)

        # 备份原文件
        if webp_path != src_path:
            bak_path = src_path + '.bak'
            os.rename(src_path, bak_path)

        ratio = (1 - new_size / original_size) * 100
        print(f"  ✅ {os.path.basename(src_path)} → {os.path.basename(webp_path)}  "
              f"({original_size // 1024}KB → {new_size // 1024}KB, -{ratio:.0f}%)")
        return webp_path
    except Exception as e:
        print(f"  ❌ 失败 {src_path}: {e}")
        return None


def main():
    if not os.path.exists(UPLOAD_ROOT):
        print(f"上传目录不存在: {UPLOAD_ROOT}")
        return

    # 收集所有图片
    all_images = []
    for root, dirs, files in os.walk(UPLOAD_ROOT):
        for f in files:
            fp = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            if ext in IMAGE_EXTS and not f.endswith('.bak'):
                all_images.append(fp)

    print(f"找到 {len(all_images)} 张图片待处理\n")

    converted = {}
    for fp in all_images:
        new_path = compress_image(fp)
        if new_path and new_path != fp:
            # 记录 old_relative → new_relative 的映射
            old_rel = os.path.relpath(fp, os.path.join(UPLOAD_ROOT, '..', '..'))
            new_rel = os.path.relpath(new_path, os.path.join(UPLOAD_ROOT, '..', '..'))
            # 把 static/ 前缀去掉, 因为数据库存的是 uploads/gifts/xxx
            old_rel = old_rel.replace('static/', '', 1) if old_rel.startswith('static/') else old_rel
            new_rel = new_rel.replace('static/', '', 1) if new_rel.startswith('static/') else new_rel
            converted[old_rel] = new_rel

    if not converted:
        print("\n没有需要更新的数据库记录")
        return

    # 更新数据库
    print(f"\n更新数据库中 {len(converted)} 条礼物图片路径...")
    try:
        from app import create_app
        from app.extensions import db
        from app.models.gift import Gift

        app = create_app()
        with app.app_context():
            for gift in Gift.query.all():
                if gift.image and gift.image in converted:
                    old = gift.image
                    gift.image = converted[gift.image]
                    print(f"  Gift#{gift.id} {gift.name}: {old} → {gift.image}")
            db.session.commit()
            print("✅ 数据库已更新")
    except Exception as e:
        print(f"⚠️  数据库更新失败 (可手动更新): {e}")


if __name__ == '__main__':
    main()
