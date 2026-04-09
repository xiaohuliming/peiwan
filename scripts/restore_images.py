#!/usr/bin/env python3
"""
恢复脚本: 将 compress_existing_images.py 产生的 .bak 备份恢复为原文件。
用法: python scripts/restore_images.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'static', 'uploads')


def main():
    if not os.path.exists(UPLOAD_ROOT):
        print(f"上传目录不存在: {UPLOAD_ROOT}")
        return

    restored = {}
    for root, dirs, files in os.walk(UPLOAD_ROOT):
        for f in files:
            if not f.endswith('.bak'):
                continue
            bak_path = os.path.join(root, f)
            # original.jpeg.bak → original.jpeg
            original_path = bak_path[:-4]
            # 对应的 .webp 压缩文件
            webp_path = os.path.splitext(original_path)[0] + '.webp'

            # 删除压缩后的 webp
            if os.path.exists(webp_path):
                os.remove(webp_path)
                print(f"  删除压缩文件: {os.path.basename(webp_path)}")

            # 恢复原文件
            os.rename(bak_path, original_path)
            print(f"  ✅ 恢复: {os.path.basename(original_path)}")

            # 记录路径映射 (webp相对路径 → 原图相对路径)
            old_rel = os.path.relpath(webp_path, os.path.join(UPLOAD_ROOT, '..', '..'))
            new_rel = os.path.relpath(original_path, os.path.join(UPLOAD_ROOT, '..', '..'))
            old_rel = old_rel.replace('static/', '', 1) if old_rel.startswith('static/') else old_rel
            new_rel = new_rel.replace('static/', '', 1) if new_rel.startswith('static/') else new_rel
            restored[old_rel] = new_rel

    if not restored:
        print("没有找到 .bak 备份文件，无需恢复")
        return

    # 更新数据库
    print(f"\n恢复数据库中 {len(restored)} 条路径...")
    try:
        from app import create_app
        from app.extensions import db
        from app.models.gift import Gift

        app = create_app()
        with app.app_context():
            for gift in Gift.query.all():
                if gift.image and gift.image in restored:
                    old = gift.image
                    gift.image = restored[gift.image]
                    print(f"  Gift#{gift.id} {gift.name}: {old} → {gift.image}")
            db.session.commit()
            print("✅ 数据库已恢复")
    except Exception as e:
        print(f"⚠️  数据库恢复失败: {e}")
        print("路径映射:")
        for k, v in restored.items():
            print(f"  {k} → {v}")


if __name__ == '__main__':
    main()
