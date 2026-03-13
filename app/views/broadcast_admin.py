from decimal import Decimal
import re
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models.broadcast import BroadcastConfig
from app.models.vip import VipLevel
from app.utils.permissions import admin_required
from app.services.log_service import log_operation
from app.services.kook_service import BROADCAST_TYPES, fetch_kook_role_catalog

broadcast_admin_bp = Blueprint('broadcast_admin', __name__, template_folder='../templates')


def _normalize_schedule_time(raw_value):
    text = (raw_value or '').strip()
    if not text:
        return '12:00'
    m = re.match(r'^(\d{1,2}):(\d{1,2})$', text)
    if not m:
        return '12:00'
    hour = max(0, min(23, int(m.group(1))))
    minute = max(0, min(59, int(m.group(2))))
    return f'{hour:02d}:{minute:02d}'


def _normalize_role_ids(raw_value):
    if not raw_value:
        return ''
    parts = [p.strip() for p in str(raw_value).split(',')]
    cleaned = []
    seen = set()
    for p in parts:
        if not p:
            continue
        if p in seen:
            continue
        cleaned.append(p)
        seen.add(p)
    return ','.join(cleaned)


@broadcast_admin_bp.route('/')
@login_required
@admin_required
def index():
    configs = BroadcastConfig.query.order_by(BroadcastConfig.broadcast_type, BroadcastConfig.threshold).all()
    vip_levels = VipLevel.query.order_by(VipLevel.sort_order).all()
    return render_template(
        'admin/broadcast.html',
        configs=configs,
        broadcast_types=BROADCAST_TYPES,
        vip_levels=vip_levels,
    )


@broadcast_admin_bp.route('/add', methods=['POST'])
@login_required
@admin_required
def add():
    broadcast_type = request.form.get('broadcast_type', 'recharge')

    # 验证类型合法
    if broadcast_type not in BROADCAST_TYPES:
        flash('未知的播报类型', 'error')
        return redirect(url_for('broadcast_admin.index'))

    channel_id = request.form.get('channel_id', '').strip()
    if BROADCAST_TYPES[broadcast_type].get('target') == 'channel' and not channel_id:
        flash('该播报类型需要填写 KOOK 频道ID', 'error')
        return redirect(url_for('broadcast_admin.index'))

    schedule_weekday = None
    schedule_time = None
    mention_role_ids = None
    target_level = None
    if broadcast_type == 'weekly_withdraw_reminder':
        weekday_raw = request.form.get('schedule_weekday', '6')
        try:
            schedule_weekday = int(weekday_raw)
        except Exception:
            schedule_weekday = 6
        schedule_weekday = max(0, min(6, schedule_weekday))
        schedule_time = _normalize_schedule_time(request.form.get('schedule_time', '12:00'))
        mention_role_ids = _normalize_role_ids(request.form.get('mention_role_ids', ''))
    elif broadcast_type == 'upgrade':
        target_level = (request.form.get('target_level') or '').strip() or None
        if target_level and not VipLevel.query.filter_by(name=target_level).first():
            flash('升级播报目标等级无效', 'error')
            return redirect(url_for('broadcast_admin.index'))

    config = BroadcastConfig(
        broadcast_type=broadcast_type,
        threshold=Decimal(request.form.get('threshold', '0') or '0'),
        template=request.form.get('template', ''),
        target_level=target_level,
        channel_id=channel_id,
        image_url=request.form.get('image_url', '').strip() or None,
        schedule_weekday=schedule_weekday,
        schedule_time=schedule_time,
        mention_role_ids=mention_role_ids,
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
    config.target_level = None
    config.channel_id = request.form.get('channel_id', '').strip()
    if BROADCAST_TYPES.get(config.broadcast_type, {}).get('target') == 'channel' and not config.channel_id:
        flash('该播报类型需要填写 KOOK 频道ID', 'error')
        return redirect(url_for('broadcast_admin.index'))
    config.image_url = request.form.get('image_url', '').strip() or None

    if config.broadcast_type == 'weekly_withdraw_reminder':
        weekday_raw = request.form.get('schedule_weekday', '6')
        try:
            config.schedule_weekday = int(weekday_raw)
        except Exception:
            config.schedule_weekday = 6
        config.schedule_weekday = max(0, min(6, config.schedule_weekday))
        config.schedule_time = _normalize_schedule_time(request.form.get('schedule_time', '12:00'))
        config.mention_role_ids = _normalize_role_ids(request.form.get('mention_role_ids', ''))
    else:
        config.schedule_weekday = None
        config.schedule_time = None
        config.mention_role_ids = None
        config.last_sent_at = None

    if config.broadcast_type == 'upgrade':
        target_level = (request.form.get('target_level') or '').strip() or None
        if target_level and not VipLevel.query.filter_by(name=target_level).first():
            flash('升级播报目标等级无效', 'error')
            return redirect(url_for('broadcast_admin.index'))
        config.target_level = target_level

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
