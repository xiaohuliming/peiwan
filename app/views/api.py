from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from decimal import Decimal

from app.models.project import Project, ProjectItem
from app.models.user import User
from app.models.order import Order
from app.models.finance import BalanceLog, CommissionLog
from app.extensions import db
from app.utils.time_utils import fmt_dt

api_bp = Blueprint('api', __name__)


@api_bp.route('/projects/cascade')
@login_required
def projects_cascade():
    """返回 游戏→子项目→定价 的级联JSON (客服+派单用)"""
    if not current_user.is_staff:
        return jsonify({'error': '无权限'}), 403

    projects = Project.query.filter_by(status=True).order_by(Project.sort_order).all()
    result = []
    for p in projects:
        items = []
        for item in p.items.filter_by(status=True).order_by(ProjectItem.sort_order).all():
            items.append({
                'id': item.id,
                'name': item.name,
                'billing_type': item.billing_type,
                'project_type': item.project_type,
                'commission_rate': float(item.commission_rate),
                'prices': item.tier_prices,
            })
        result.append({
            'id': p.id,
            'name': p.name,
            'items': items,
        })
    return jsonify(result)


@api_bp.route('/users/search')
@login_required
def users_search():
    """模糊搜索用户 (仅客服+可用, 派单时搜索老板/陪玩)"""
    if not current_user.is_staff:
        return jsonify({'error': '无权限'}), 403

    q = request.args.get('q', '').strip()
    role = request.args.get('role', '')

    if not q or len(q) < 1:
        return jsonify([])

    query = User.query.filter(User.status == True)

    # 通用搜索条件: 用户名、昵称、KOOK名称、KOOK ID、用户编码
    search_filter = or_(
        User.username.ilike(f'%{q}%'),
        User.nickname.ilike(f'%{q}%'),
        User.player_nickname.ilike(f'%{q}%'),
        User.kook_username.ilike(f'%{q}%'),
        User.kook_id.ilike(f'%{q}%'),
        User.user_code.ilike(f'%{q}%'),
    )

    if role == 'boss':
        query = query.filter(User.role_filter_expr('god'))
    elif role == 'player':
        query = query.filter(User.role_filter_expr('player'))
    elif role == 'gift_receiver':
        query = query.filter(or_(
            User.role_filter_expr('player'),
            User.role_filter_expr('god'),
        ))

    query = query.filter(search_filter)

    users = query.limit(10).all()
    result = []
    for u in users:
        player_name = (u.player_nickname or '').strip()
        boss_name = (u.nickname or '').strip()
        item = {
            'id': u.id,
            'user_code': u.user_code,
            'role': u.role,
            'avatar': u.avatar_url,
            'player_name': player_name,
            'boss_name': boss_name,
        }
        # 显示名称按“搜索场景角色”优先，避免多身份用户被默认老板标签覆盖
        if role == 'boss':
            item['display'] = boss_name or u.username
        elif role == 'player':
            # 陪玩搜索统一展示陪玩昵称；未设置时给出明确占位，避免显示客户昵称
            item['display'] = player_name or '未设置陪玩昵称'
        elif role == 'gift_receiver':
            # 礼物收礼人支持“陪玩/老板”，优先陪玩昵称，其次客户昵称
            item['display'] = player_name or boss_name or u.username
        else:
            if u.role == 'player':
                item['display'] = player_name or boss_name or u.username
            elif u.role == 'god':
                item['display'] = boss_name or u.username
            else:
                item['display'] = boss_name or player_name or u.username
        item['kook'] = u.kook_username or ''

        result.append(item)
    return jsonify(result)


@api_bp.route('/kook/user')
@login_required
def kook_user_lookup():
    """通过 KOOK ID 查询 KOOK 用户名"""
    if not current_user.is_staff:
        return jsonify({'error': '无权限'}), 403

    kook_id = request.args.get('kook_id', '').strip()
    if not kook_id:
        return jsonify({'error': 'KOOK ID 不能为空'}), 400

    from app.services.kook_service import fetch_kook_user
    kook_username, avatar_url, error = fetch_kook_user(kook_id)

    if error:
        return jsonify({'error': error}), 400

    return jsonify({'kook_username': kook_username, 'avatar_url': avatar_url})


@api_bp.route('/kook/search')
@login_required
def kook_user_search():
    """通过 KOOK 名称 (abc#1234) 搜索用户"""
    if not current_user.is_staff:
        return jsonify({'error': '无权限'}), 403

    kook_name = request.args.get('kook_name', '').strip()
    if not kook_name:
        return jsonify({'error': 'KOOK 名称不能为空'}), 400

    from app.services.kook_service import search_kook_user_by_name
    kook_id, kook_username, avatar_url, error = search_kook_user_by_name(kook_name)

    if error:
        return jsonify({'error': error}), 400

    return jsonify({
        'kook_id': kook_id,
        'kook_username': kook_username,
        'avatar_url': avatar_url,
    })


@api_bp.route('/kook/sync-avatars', methods=['POST'])
@login_required
def sync_kook_avatars():
    """批量同步所有已绑定 KOOK 用户的头像"""
    if not current_user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403

    from app.services.kook_service import fetch_kook_user
    users = User.query.filter(
        User.kook_id.isnot(None),
        User.kook_bound == True,
    ).all()

    updated = 0
    for user in users:
        try:
            _, avatar_url, err = fetch_kook_user(user.kook_id)
            if not err and avatar_url:
                user.avatar = avatar_url
                updated += 1
        except Exception:
            continue

    db.session.commit()
    return jsonify({'updated': updated, 'total': len(users)})


@api_bp.route('/orders/<int:order_id>/detail')
@login_required
def order_detail(order_id):
    """返回订单详情JSON - 仅可查看自己相关的订单或客服+可查看所有"""
    order = Order.query.get_or_404(order_id)

    # 权限检查: 非客服仅可查看自己参与的订单（老板单或陪玩单）
    if not current_user.is_staff:
        if order.boss_id != current_user.id and order.player_id != current_user.id:
            return jsonify({'error': '无权限查看该订单'}), 403

    # 对非客服角色隐藏敏感财务信息
    show_financials = current_user.is_staff

    result = {
        'id': order.id,
        'order_no': order.order_no,
        'boss': order.boss.nickname if order.boss else '',
        'boss_kook': order.boss.kook_username if order.boss else '',
        'player': order.player.player_nickname if order.player else '',
        'staff': order.staff.staff_display_name if order.staff else '',
        'game': order.game_name,
        'item': order.item_name,
        'price_tier': order.price_tier or '',
        'base_price': float(order.base_price or 0),
        'extra_price': float(order.extra_price or 0),
        'addon_desc': order.addon_desc or '',
        'addon_price': float(order.addon_price or 0),
        'total_price': float(order.total_price or 0),
        'boss_discount': float(order.boss_discount or 100),
        'duration': float(order.duration or 0),
        'order_type': order.order_type or 'normal',
        'status': order.status,
        'status_label': order.status_label,
        'freeze_status': order.freeze_status,
        'remark': order.remark or '',
        'created_at': fmt_dt(order.created_at, '%Y-%m-%d %H:%M'),
        'report_time': fmt_dt(order.report_time, '%Y-%m-%d %H:%M'),
        'confirm_time': fmt_dt(order.confirm_time, '%Y-%m-%d %H:%M'),
        'pay_time': fmt_dt(order.pay_time, '%Y-%m-%d %H:%M'),
        'refund_time': fmt_dt(order.refund_time, '%Y-%m-%d %H:%M'),
    }

    # 订单资金明细（用于详情展示，退款后需可追踪）
    consume_log = BalanceLog.query.filter(
        BalanceLog.user_id == order.boss_id,
        BalanceLog.change_type == 'consume',
        BalanceLog.reason.ilike(f'%{order.order_no}%')
    ).order_by(BalanceLog.created_at.desc()).first()

    refund_log = BalanceLog.query.filter(
        BalanceLog.user_id == order.boss_id,
        BalanceLog.change_type == 'refund',
        BalanceLog.reason.ilike(f'%{order.order_no}%')
    ).order_by(BalanceLog.created_at.desc()).first()

    player_refund_deduct_log = CommissionLog.query.filter_by(
        order_id=order.id,
        change_type='refund_deduct'
    ).order_by(CommissionLog.created_at.desc()).first()

    result['consume_amount'] = float(abs(consume_log.amount)) if consume_log else 0
    result['consume_time'] = fmt_dt(consume_log.created_at, '%Y-%m-%d %H:%M') if consume_log else ''
    result['refund_amount'] = float(refund_log.amount) if refund_log else 0
    result['refund_balance_time'] = fmt_dt(refund_log.created_at, '%Y-%m-%d %H:%M') if refund_log else ''
    result['refund_reason'] = refund_log.reason if refund_log else ''
    result['player_refund_deduct'] = float(abs(player_refund_deduct_log.amount)) if player_refund_deduct_log else 0
    result['player_refund_deduct_time'] = (
        fmt_dt(player_refund_deduct_log.created_at, '%Y-%m-%d %H:%M') if player_refund_deduct_log else ''
    )

    # 客服+可见完整财务数据
    if show_financials:
        result['commission_rate'] = float(order.commission_rate or 0)
        result['player_earning'] = float(order.player_earning or 0)
        result['shop_earning'] = float(order.shop_earning or 0)
    elif order.player_id == current_user.id:
        # 陪玩可以看自己的收益
        result['commission_rate'] = float(order.commission_rate or 0)
        result['player_earning'] = float(order.player_earning or 0)
        result['shop_earning'] = 0
    else:
        # 老板只看到总价
        result['commission_rate'] = 0
        result['player_earning'] = 0
        result['shop_earning'] = 0

    return jsonify(result)


@api_bp.route('/orders/stats')
@login_required
def order_stats():
    """返回订单统计 (客服+可见)"""
    if not current_user.is_staff:
        return jsonify({'error': '无权限'}), 403

    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    paid_statuses = ['pending_pay', 'paid']
    base_filter = Order.status.in_(paid_statuses)

    q = db.session.query(
        func.sum(Order.total_price),
        func.sum(Order.player_earning),
        func.sum(Order.shop_earning),
    ).filter(base_filter)

    if date_from:
        q = q.filter(Order.created_at >= date_from)
    if date_to:
        q = q.filter(Order.created_at <= date_to + ' 23:59:59')

    row = q.one()

    return jsonify({
        'total_amount': float(row[0] or 0),
        'player_wages': float(row[1] or 0),
        'platform_revenue': float(row[2] or 0),
    })
