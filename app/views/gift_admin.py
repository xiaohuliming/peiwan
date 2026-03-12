import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from decimal import Decimal
from sqlalchemy import func, inspect, text

from app.models.gift import Gift, GiftOrder
from app.extensions import db
from app.utils.permissions import admin_required
from app.services import upload_service

gift_admin_bp = Blueprint('gift_admin', __name__)


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _ensure_gift_sort_order_column():
    """
    兼容旧库：若 gifts.sort_order / deleted_at / crown_broadcast_template 缺失则自动补齐。
    避免在新增礼物时直接 500。
    """
    try:
        cols = {c.get('name') for c in inspect(db.engine).get_columns('gifts')}
    except Exception as e:
        return False, f'读取 gifts 表结构失败: {e}'

    need_sort_order = 'sort_order' not in cols
    need_deleted_at = 'deleted_at' not in cols
    need_crown_broadcast_template = 'crown_broadcast_template' not in cols

    if need_deleted_at:
        try:
            db.session.execute(text('ALTER TABLE gifts ADD COLUMN deleted_at DATETIME NULL'))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return False, f'补齐 gifts.deleted_at 字段失败: {e}'

    if need_sort_order:
        try:
            db.session.execute(text('ALTER TABLE gifts ADD COLUMN sort_order INT NOT NULL DEFAULT 0'))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return False, f'补齐 gifts.sort_order 字段失败: {e}'

    if need_crown_broadcast_template:
        try:
            db.session.execute(text('ALTER TABLE gifts ADD COLUMN crown_broadcast_template TEXT NULL'))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return False, f'补齐 gifts.crown_broadcast_template 字段失败: {e}'

    return True, None


@gift_admin_bp.route('/')
@login_required
@admin_required
def index():
    """礼物管理列表"""
    ok, err = _ensure_gift_sort_order_column()
    if not ok:
        flash(err, 'error')
        return render_template('admin/gifts.html', gifts=[])

    _normalize_gift_sort_orders()
    gifts = Gift.query.filter(Gift.deleted_at.is_(None)).order_by(Gift.sort_order.asc(), Gift.id.asc()).all()
    return render_template('admin/gifts.html', gifts=gifts)


@gift_admin_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add():
    """添加礼物"""
    if request.method == 'POST':
        ok, err = _ensure_gift_sort_order_column()
        if not ok:
            flash(err, 'error')
            return render_template('admin/gift_form.html', gift=None)

        name = request.form.get('name', '').strip()
        price = request.form.get('price', '0')
        gift_type = request.form.get('gift_type', 'standard')
        status = request.form.get('status') == 'on'

        if not name:
            flash('请输入礼物名称', 'error')
            return render_template('admin/gift_form.html', gift=None)

        try:
            price = Decimal(price)
        except Exception:
            flash('无效的价格', 'error')
            return render_template('admin/gift_form.html', gift=None)

        image_path, upload_error = _handle_image_upload()
        if upload_error:
            flash(f'图片上传失败: {upload_error}', 'error')
            return render_template('admin/gift_form.html', gift=None)

        # 新增礼物默认置顶：新礼物排序=1，其余礼物整体后移一位
        try:
            Gift.query.filter(Gift.deleted_at.is_(None)).update(
                {Gift.sort_order: Gift.sort_order + 1},
                synchronize_session=False,
            )

            gift = Gift(
                name=name, price=price, gift_type=gift_type,
                status=status, image=image_path,
                sort_order=1,
            )
            db.session.add(gift)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'保存礼物失败: {e}', 'error')
            return render_template('admin/gift_form.html', gift=None)

        flash(f'礼物 "{name}" 添加成功', 'success')
        return redirect(url_for('gift_admin.index'))

    return render_template('admin/gift_form.html', gift=None)


@gift_admin_bp.route('/<int:gift_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(gift_id):
    """编辑礼物"""
    ok, err = _ensure_gift_sort_order_column()
    if not ok:
        flash(err, 'error')
        return redirect(url_for('gift_admin.index'))

    gift = Gift.query.filter(
        Gift.id == gift_id,
        Gift.deleted_at.is_(None),
    ).first_or_404()

    if request.method == 'POST':
        gift.name = request.form.get('name', '').strip()
        price = request.form.get('price', '0')
        try:
            gift.price = Decimal(price)
        except Exception:
            flash('无效的价格', 'error')
            return render_template('admin/gift_form.html', gift=gift)

        gift.gift_type = request.form.get('gift_type', 'standard')
        gift.status = request.form.get('status') == 'on'

        image_path, upload_error = _handle_image_upload()
        if upload_error:
            flash(f'图片上传失败: {upload_error}', 'error')
            return render_template('admin/gift_form.html', gift=gift)

        if image_path:
            gift.image = image_path

        db.session.commit()
        flash(f'礼物 "{gift.name}" 已更新', 'success')
        return redirect(url_for('gift_admin.index'))

    return render_template('admin/gift_form.html', gift=gift)


@gift_admin_bp.route('/<int:gift_id>/broadcast', methods=['POST'])
@login_required
@admin_required
def edit_broadcast(gift_id):
    """编辑礼物播报模板"""
    gift = Gift.query.filter(
        Gift.id == gift_id,
        Gift.deleted_at.is_(None),
    ).first_or_404()
    gift.broadcast_template = request.form.get('broadcast_template', '')
    gift.crown_broadcast_template = request.form.get('crown_broadcast_template', '')
    db.session.commit()
    flash(f'"{gift.name}" 播报模板已更新', 'success')
    return redirect(url_for('gift_admin.index'))


@gift_admin_bp.route('/<int:gift_id>/move/<string:direction>', methods=['POST'])
@login_required
@admin_required
def move(gift_id, direction):
    """礼物排序移动（上移/下移）"""
    ok, err = _ensure_gift_sort_order_column()
    if not ok:
        flash(err, 'error')
        return redirect(url_for('gift_admin.index'))

    if direction not in ('up', 'down'):
        flash('无效的移动方向', 'error')
        return redirect(url_for('gift_admin.index'))

    _normalize_gift_sort_orders()
    gifts = Gift.query.filter(Gift.deleted_at.is_(None)).order_by(Gift.sort_order.asc(), Gift.id.asc()).all()
    current_idx = next((i for i, g in enumerate(gifts) if g.id == gift_id), None)
    if current_idx is None:
        flash('礼物不存在', 'error')
        return redirect(url_for('gift_admin.index'))

    if direction == 'up':
        if current_idx == 0:
            return redirect(url_for('gift_admin.index'))
        target_idx = current_idx - 1
    else:
        if current_idx >= len(gifts) - 1:
            return redirect(url_for('gift_admin.index'))
        target_idx = current_idx + 1

    current_gift = gifts[current_idx]
    target_gift = gifts[target_idx]
    current_gift.sort_order, target_gift.sort_order = target_gift.sort_order, current_gift.sort_order
    db.session.commit()
    return redirect(url_for('gift_admin.index'))


@gift_admin_bp.route('/reorder', methods=['POST'])
@login_required
@admin_required
def reorder():
    """批量保存礼物排序（前端本地拖动/上下移动后一次提交）。"""
    ok, err = _ensure_gift_sort_order_column()
    if not ok:
        return jsonify({'ok': False, 'error': err}), 500

    payload = request.get_json(silent=True) or {}
    order_ids = payload.get('order_ids')
    if not isinstance(order_ids, list) or not order_ids:
        return jsonify({'ok': False, 'error': '排序数据不能为空'}), 400

    clean_ids = []
    seen = set()
    for item in order_ids:
        try:
            gid = int(item)
        except Exception:
            continue
        if gid in seen:
            continue
        seen.add(gid)
        clean_ids.append(gid)

    if not clean_ids:
        return jsonify({'ok': False, 'error': '排序数据无效'}), 400

    gifts = Gift.query.filter(
        Gift.deleted_at.is_(None),
        Gift.id.in_(clean_ids),
    ).all()
    gift_map = {g.id: g for g in gifts}
    if len(gift_map) != len(clean_ids):
        return jsonify({'ok': False, 'error': '存在无效礼物ID，请刷新页面后重试'}), 400

    for idx, gid in enumerate(clean_ids, start=1):
        gift_map[gid].sort_order = idx

    db.session.commit()
    return jsonify({'ok': True})


@gift_admin_bp.route('/<int:gift_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(gift_id):
    """删除礼物配置（软删除：保留历史赠礼记录）"""
    ok, err = _ensure_gift_sort_order_column()
    if not ok:
        flash(err, 'error')
        return redirect(url_for('gift_admin.index'))

    gift = Gift.query.filter(
        Gift.id == gift_id,
        Gift.deleted_at.is_(None),
    ).first_or_404()

    used_count = GiftOrder.query.filter_by(gift_id=gift.id).count()
    gift.status = False
    gift.deleted_at = gift.deleted_at or datetime.utcnow()
    db.session.commit()
    if used_count > 0:
        flash(f'礼物“{gift.name}”已删除（保留 {used_count} 条赠送记录）', 'success')
    else:
        flash(f'礼物“{gift.name}”已删除', 'success')
    return redirect(url_for('gift_admin.index'))


def _normalize_gift_sort_orders():
    """保证礼物 sort_order 连续且唯一"""
    gifts = Gift.query.filter(Gift.deleted_at.is_(None)).order_by(Gift.sort_order.asc(), Gift.id.asc()).all()
    changed = False
    for idx, gift in enumerate(gifts, start=1):
        if gift.sort_order != idx:
            gift.sort_order = idx
            changed = True
    if changed:
        db.session.commit()


def _handle_image_upload():
    """处理礼物图片上传, 返回 (相对路径或None, 错误信息或None)"""
    if 'image' not in request.files:
        return None, None
    file = request.files['image']
    if not file or file.filename == '':
        return None, None

    try:
        path, error = upload_service.save_file(file, 'gifts')
        if error:
            return None, error
        return path, None
    except Exception as e:
        return None, str(e)
