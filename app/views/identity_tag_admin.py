from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user

from app.extensions import db
from app.models.identity_tag import IdentityTag
from app.models.user import User
from app.services.log_service import log_operation
from app.utils.permissions import admin_required


identity_tag_admin_bp = Blueprint('identity_tag_admin', __name__, template_folder='../templates')


def _safe_decimal(text, default='1.00'):
    try:
        return Decimal(str(text or default))
    except Exception:
        return Decimal(default)


def _safe_int(text, default=0):
    try:
        return int(text)
    except Exception:
        return default


@identity_tag_admin_bp.route('/')
@login_required
@admin_required
def index():
    tags = IdentityTag.query.order_by(IdentityTag.updated_at.desc(), IdentityTag.id.desc()).all()
    items = []
    for tag in tags:
        usage_count = User.query.filter(User.tags.ilike(f'%"{tag.name}"%')).count()
        items.append({'tag': tag, 'usage_count': usage_count})
    return render_template('admin/identity_tags.html', items=items)


@identity_tag_admin_bp.route('/add', methods=['POST'])
@login_required
@admin_required
def add():
    name = (request.form.get('name') or '').strip()
    description = (request.form.get('description') or '').strip()
    multiplier = _safe_decimal(request.form.get('exp_multiplier'), '1.00')
    bonus_until = _safe_int(request.form.get('exp_bonus_until'), 0)
    status = ('status' in request.form)

    if not name:
        flash('标签名称不能为空', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if len(name) > 50:
        flash('标签名称最长 50 个字符', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if IdentityTag.query.filter_by(name=name).first():
        flash('标签名称已存在', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if multiplier <= 0:
        flash('经验倍率必须大于 0', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if bonus_until < 0:
        flash('经验阈值不能小于 0', 'error')
        return redirect(url_for('identity_tag_admin.index'))

    tag = IdentityTag(
        name=name,
        description=description or None,
        exp_multiplier=multiplier.quantize(Decimal('0.01')),
        exp_bonus_until=bonus_until or None,
        status=status,
    )
    db.session.add(tag)
    db.session.commit()

    log_operation(current_user.id, 'identity_tag_add', 'identity_tag', tag.id, f'新增身份标签: {tag.name}')
    db.session.commit()
    flash('身份标签已新增', 'success')
    return redirect(url_for('identity_tag_admin.index'))


@identity_tag_admin_bp.route('/<int:tag_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit(tag_id):
    tag = IdentityTag.query.get_or_404(tag_id)

    new_name = (request.form.get('name') or '').strip()
    description = (request.form.get('description') or '').strip()
    multiplier = _safe_decimal(request.form.get('exp_multiplier'), '1.00')
    bonus_until = _safe_int(request.form.get('exp_bonus_until'), 0)
    status = ('status' in request.form)

    if not new_name:
        flash('标签名称不能为空', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if len(new_name) > 50:
        flash('标签名称最长 50 个字符', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if multiplier <= 0:
        flash('经验倍率必须大于 0', 'error')
        return redirect(url_for('identity_tag_admin.index'))
    if bonus_until < 0:
        flash('经验阈值不能小于 0', 'error')
        return redirect(url_for('identity_tag_admin.index'))

    duplicate = IdentityTag.query.filter(IdentityTag.name == new_name, IdentityTag.id != tag.id).first()
    if duplicate:
        flash('标签名称已存在', 'error')
        return redirect(url_for('identity_tag_admin.index'))

    old_name = tag.name
    tag.name = new_name
    tag.description = description or None
    tag.exp_multiplier = multiplier.quantize(Decimal('0.01'))
    tag.exp_bonus_until = bonus_until or None
    tag.status = status
    db.session.commit()

    # 若改名，同步用户 tags 字段中的历史标签名
    if old_name != new_name:
        users = User.query.filter(User.tags.ilike(f'%"{old_name}"%')).all()
        for user in users:
            tags = user.tag_list
            changed = False
            for idx, value in enumerate(tags):
                if value == old_name:
                    tags[idx] = new_name
                    changed = True
            if changed:
                user.tag_list = tags
        db.session.commit()

    log_operation(
        current_user.id,
        'identity_tag_edit',
        'identity_tag',
        tag.id,
        f'编辑身份标签: {old_name} -> {new_name}, 倍率={tag.exp_multiplier}, 阈值={tag.exp_bonus_until or 0}, 启用={tag.status}',
    )
    db.session.commit()
    flash('身份标签已更新', 'success')
    return redirect(url_for('identity_tag_admin.index'))


@identity_tag_admin_bp.route('/<int:tag_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(tag_id):
    tag = IdentityTag.query.get_or_404(tag_id)
    name = tag.name

    # 删除规则时，同步移除用户 tags 中的同名标签
    affected_users = 0
    users = User.query.filter(User.tags.ilike(f'%"{name}"%')).all()
    for user in users:
        old_tags = user.tag_list
        new_tags = [t for t in old_tags if t != name]
        if len(new_tags) != len(old_tags):
            user.tag_list = new_tags
            affected_users += 1

    db.session.delete(tag)
    db.session.commit()

    log_operation(
        current_user.id,
        'identity_tag_delete',
        'identity_tag',
        tag_id,
        f'删除身份标签规则: {name}, 同步移除用户标签 {affected_users} 人',
    )
    db.session.commit()
    flash(f'身份标签规则已删除，并已从 {affected_users} 个用户移除该标签', 'success')
    return redirect(url_for('identity_tag_admin.index'))
