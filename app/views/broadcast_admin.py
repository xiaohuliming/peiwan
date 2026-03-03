from decimal import Decimal
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models.broadcast import BroadcastConfig
from app.utils.permissions import admin_required
from app.services.log_service import log_operation
from app.services.kook_service import BROADCAST_TYPES, fetch_kook_role_catalog

broadcast_admin_bp = Blueprint('broadcast_admin', __name__, template_folder='../templates')


@broadcast_admin_bp.route('/')
@login_required
@admin_required
def index():
    configs = BroadcastConfig.query.order_by(BroadcastConfig.broadcast_type, BroadcastConfig.threshold).all()
    return render_template('admin/broadcast.html', configs=configs, broadcast_types=BROADCAST_TYPES)


@broadcast_admin_bp.route('/add', methods=['POST'])
@login_required
@admin_required
def add():
    broadcast_type = request.form.get('broadcast_type', 'recharge')

    # 验证类型合法
    if broadcast_type not in BROADCAST_TYPES:
        flash('未知的播报类型', 'error')
        return redirect(url_for('broadcast_admin.index'))

    config = BroadcastConfig(
        broadcast_type=broadcast_type,
        threshold=Decimal(request.form.get('threshold', '0') or '0'),
        template=request.form.get('template', ''),
        channel_id=request.form.get('channel_id', ''),
        image_url=request.form.get('image_url', '').strip() or None,
        status=True,
    )
    db.session.add(config)
    db.session.commit()

    type_label = BROADCAST_TYPES[broadcast_type]['label']
    log_operation(current_user.id, 'broadcast_add', 'broadcast', config.id,
                  f'添加播报配置: {type_label}')
    db.session.commit()

    flash(f'播报配置已添加: {type_label}', 'success')
    return redirect(url_for('broadcast_admin.index'))


@broadcast_admin_bp.route('/<int:config_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit(config_id):
    config = BroadcastConfig.query.get_or_404(config_id)
    config.broadcast_type = request.form.get('broadcast_type', config.broadcast_type)
    config.threshold = Decimal(request.form.get('threshold', '0') or '0')
    config.template = request.form.get('template', '')
    config.channel_id = request.form.get('channel_id', '')
    config.image_url = request.form.get('image_url', '').strip() or None
    config.status = 'status' in request.form
    db.session.commit()

    log_operation(current_user.id, 'broadcast_edit', 'broadcast', config.id, f'编辑播报配置')
    db.session.commit()

    flash('播报配置已更新', 'success')
    return redirect(url_for('broadcast_admin.index'))


@broadcast_admin_bp.route('/<int:config_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(config_id):
    config = BroadcastConfig.query.get_or_404(config_id)
    db.session.delete(config)
    db.session.commit()

    log_operation(current_user.id, 'broadcast_delete', 'broadcast', config_id, '删除播报配置')
    db.session.commit()

    flash('播报配置已删除', 'success')
    return redirect(url_for('broadcast_admin.index'))


@broadcast_admin_bp.route('/types')
@login_required
@admin_required
def types_api():
    """返回播报类型元数据 JSON（供前端动态渲染）"""
    result = {}
    for key, meta in BROADCAST_TYPES.items():
        result[key] = {
            'label': meta['label'],
            'group': meta['group'],
            'target': meta['target'],
            'variables': meta['variables'],
            'default_template': meta['default_template'],
            'hint': meta.get('hint', ''),
        }
    return jsonify(result)


@broadcast_admin_bp.route('/kook/roles')
@login_required
@admin_required
def kook_roles_api():
    """获取 KOOK 服务器角色列表（支持按频道ID自动定位服务器）。"""
    guild_id = (request.args.get('guild_id') or '').strip() or None
    channel_id = (request.args.get('channel_id') or '').strip() or None

    result, err = fetch_kook_role_catalog(guild_id=guild_id, channel_id=channel_id)
    if err:
        return jsonify({'ok': False, 'error': err, 'roles': []}), 400

    return jsonify({
        'ok': True,
        'error': '',
        'resolved_guild_id': result.get('resolved_guild_id', ''),
        'resolved_guild_name': result.get('resolved_guild_name', ''),
        'guilds': result.get('guilds', []),
        'roles': result.get('roles', []),
    })
