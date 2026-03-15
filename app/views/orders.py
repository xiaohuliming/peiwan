from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from decimal import Decimal

from app.models.order import Order
from app.models.user import User
from app.models.project import Project, ProjectItem
from app.extensions import db
from app.services import order_service
from app.services import kook_service
from app.utils.permissions import staff_required, admin_required

orders_bp = Blueprint('orders', __name__)


@orders_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    subtab = (request.args.get('subtab', 'order') or 'order').strip().lower()
    if subtab not in ('order', 'escort', 'training'):
        subtab = 'order'

    query = Order.query

    # 按“身份标签”聚合可见订单：多身份账号可同时看到各身份对应订单
    tag_set = set(current_user.tag_list or [])
    has_staff_identity = current_user.is_staff or ('客服' in tag_set)
    has_boss_identity = (current_user.role == 'god') or ('老板' in tag_set)
    has_player_identity = (current_user.role == 'player') or ('陪玩' in tag_set)

    if has_staff_identity:
        # 客服/管理可见全量订单
        view_mode = 'staff'
    else:
        own_filters = []
        if has_boss_identity:
            own_filters.append(Order.boss_id == current_user.id)
        if has_player_identity:
            own_filters.append(Order.player_id == current_user.id)

        if own_filters:
            query = query.filter(or_(*own_filters))
        else:
            # 兜底：未知身份只看与自己直接相关订单
            query = query.filter(or_(Order.boss_id == current_user.id, Order.player_id == current_user.id))

        if has_boss_identity and has_player_identity:
            view_mode = 'hybrid'
        elif has_boss_identity:
            view_mode = 'god'
        else:
            view_mode = 'player'

    # 子菜单筛选: 订单(常规) / 护航 / 代练
    if subtab == 'order':
        query = query.filter(or_(Order.order_type == 'normal', Order.order_type.is_(None)))
    else:
        query = query.filter(Order.order_type == subtab)

    # 状态筛选
    if status_filter and status_filter != 'all':
        query = query.filter(Order.status == status_filter)

    # 搜索: 订单号
    q = request.args.get('q', '').strip()
    if q:
        query = query.filter(Order.order_no.ilike(f'%{q}%'))

    # 老板昵称
    boss_name = request.args.get('boss_name', '').strip()
    if boss_name:
        boss_ids = db.session.query(User.id).filter(
            User.role_filter_expr('god'), User.nickname.ilike(f'%{boss_name}%')
        ).subquery()
        query = query.filter(Order.boss_id.in_(boss_ids))

    # 陪玩昵称
    player_name = request.args.get('player_name', '').strip()
    if player_name:
        player_ids = db.session.query(User.id).filter(
            User.role_filter_expr('player'), User.player_nickname.ilike(f'%{player_name}%')
        ).subquery()
        query = query.filter(Order.player_id.in_(player_ids))

    # 派单客服
    staff_name = request.args.get('staff_name', '').strip()
    if staff_name:
        staff_ids = db.session.query(User.id).filter(
            or_(
                User.player_nickname.ilike(f'%{staff_name}%'),
                User.nickname.ilike(f'%{staff_name}%')
            )
        ).subquery()
        query = query.filter(Order.staff_id.in_(staff_ids))

    # 日期范围
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    if date_from:
        query = query.filter(Order.created_at >= date_from)
    if date_to:
        query = query.filter(Order.created_at <= date_to + ' 23:59:59')

    # 统计 (客服/管理可见)
    stats = None
    if has_staff_identity:
        paid_statuses = ['pending_pay', 'paid']
        stats_query = Order.query
        if subtab == 'order':
            stats_query = stats_query.filter(or_(Order.order_type == 'normal', Order.order_type.is_(None)))
        else:
            stats_query = stats_query.filter(Order.order_type == subtab)
        paid_query = stats_query.filter(Order.status.in_(paid_statuses))
        total_amount = paid_query.with_entities(func.sum(Order.total_price)).scalar() or Decimal('0')
        player_wages = paid_query.with_entities(func.sum(Order.player_earning)).scalar() or Decimal('0')
        platform_revenue = paid_query.with_entities(func.sum(Order.shop_earning)).scalar() or Decimal('0')
        stats = {
            'total_amount': total_amount,
            'player_wages': player_wages,
            'platform_revenue': platform_revenue,
        }

    orders = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=15)
    pagination_args = request.args.to_dict(flat=True)
    pagination_args.pop('page', None)

    return render_template(
        'orders/index.html',
        orders=orders,
        stats=stats,
        view_mode=view_mode,
        current_subtab=subtab,
        pagination_args=pagination_args,
    )


@orders_bp.route('/dispatch', methods=['GET', 'POST'])
@login_required
def dispatch():
    """派单页面 (仅客服+)"""
    if not current_user.is_staff:
        flash('无权限', 'error')
        return redirect(url_for('orders.index'))

    if request.method == 'POST':
        project_item_id = request.form.get('project_item_id', type=int)
        price_tier = request.form.get('price_tier', 'casual')
        boss_id = request.form.get('boss_id', type=int)
        player_id = request.form.get('player_id', type=int)
        extra_price = request.form.get('extra_price', 0, type=float)
        addon_desc = request.form.get('addon_desc', '').strip()
        addon_price = request.form.get('addon_price', 0, type=float)
        duration = request.form.get('duration', 0, type=float)
        remark = request.form.get('remark', '').strip()

        # 验证
        if not project_item_id or not boss_id or not player_id:
            flash('请填写完整信息', 'error')
            return redirect(url_for('orders.dispatch'))

        project_item = ProjectItem.query.get(project_item_id)
        boss = User.query.get(boss_id)
        player = User.query.get(player_id)

        if not project_item or not boss or not player:
            flash('数据不存在', 'error')
            return redirect(url_for('orders.dispatch'))

        if not boss.is_god:
            flash('老板角色错误', 'error')
            return redirect(url_for('orders.dispatch'))
        if not player.is_player:
            flash('陪玩角色错误', 'error')
            return redirect(url_for('orders.dispatch'))

        # 根据项目类型创建订单
        if project_item.project_type in ('escort', 'training'):
            if duration <= 0:
                flash('护航/代肝订单需要填写时长', 'error')
                return redirect(url_for('orders.dispatch'))
            order, error = order_service.create_escort_order(
                boss=boss, player=player, project_item=project_item,
                price_tier=price_tier, staff=current_user,
                duration=duration, extra_price=extra_price,
                addon_desc=addon_desc or None, addon_price=addon_price,
                remark=remark or None,
            )
            if error:
                flash(error, 'error')
                return redirect(url_for('orders.dispatch'))
            db.session.commit()
            # KOOK 推送: 护航/代练派单通知（不再推送老板建单私信）
            kook_service.push_escort_dispatch(order)
            flash(f'护航/代肝订单已创建并自动结算冻结: {order.order_no}', 'success')
            target_subtab = 'escort' if project_item.project_type == 'escort' else 'training'
        else:
            order, error = order_service.create_normal_order(
                boss=boss, player=player, project_item=project_item,
                price_tier=price_tier, staff=current_user,
                extra_price=extra_price,
                addon_desc=addon_desc or None, addon_price=addon_price,
                remark=remark or None,
            )
            if error:
                flash(error, 'error')
                return redirect(url_for('orders.dispatch'))
            db.session.commit()
            # KOOK 推送: 常规派单通知 (含结单申报链接，不再推送老板建单私信)
            site_url = current_app.config.get('SITE_URL', '')
            kook_service.push_order_dispatch(order, site_url=site_url)
            flash(f'订单已派发: {order.order_no}', 'success')
            target_subtab = 'order'

        return redirect(url_for('orders.index', subtab=target_subtab))

    return render_template('orders/dispatch.html')


@orders_bp.route('/<int:order_id>/report', methods=['GET', 'POST'])
@login_required
def report(order_id):
    """陪玩申报"""
    order = Order.query.get(order_id)
    if not order:
        flash('订单不存在或已删除', 'error')
        return redirect(url_for('orders.index'))

    return _handle_report(order)


@orders_bp.route('/report/<order_no>', methods=['GET', 'POST'])
@login_required
def report_by_no(order_no):
    """按订单号申报（供私信按钮跳转，避免旧消息 ID 失效）"""
    order = Order.query.filter_by(order_no=order_no).first()
    if not order:
        flash('订单不存在或已删除', 'error')
        return redirect(url_for('orders.index'))

    return _handle_report(order)


@orders_bp.route('/confirm/<order_no>', methods=['GET'])
@login_required
def confirm_by_no(order_no):
    """按订单号进入确认页面（供老板私信按钮直达）"""
    order = Order.query.filter_by(order_no=order_no).first()
    if not order:
        flash('订单不存在或已删除', 'error')
        return redirect(url_for('orders.index'))

    if order.boss_id != current_user.id and not current_user.is_staff:
        flash('无权限查看该订单', 'error')
        return redirect(url_for('orders.index'))

    return render_template('orders/confirm.html', order=order)


def _handle_report(order):
    """申报处理逻辑：陪玩本人或客服及以上可操作"""
    if order.order_type in ('escort', 'training'):
        flash('护航/代肝订单无需报单，创建后已自动结算并冻结', 'info')
        return redirect(url_for('orders.index'))

    can_report = (order.player_id == current_user.id) or current_user.is_staff
    if not can_report:
        flash('仅陪玩本人或客服及以上可申报该订单', 'error')
        return redirect(url_for('orders.index'))

    if order.status not in ('pending_report', 'pending_confirm'):
        flash('该订单当前不可申报', 'error')
        return redirect(url_for('orders.index'))

    if request.method == 'POST':
        was_pending_confirm = (order.status == 'pending_confirm')
        duration_raw = (request.form.get('duration') or '').strip()
        if not duration_raw:
            flash('请填写申报时长', 'error')
            return redirect(url_for('orders.report_by_no', order_no=order.order_no))

        success, error = order_service.report_order(order, duration_raw)
        if not success:
            flash(error, 'error')
            return redirect(url_for('orders.report_by_no', order_no=order.order_no))

        db.session.commit()
        # KOOK 推送: 申报通知给老板
        site_url = current_app.config.get('SITE_URL', '')
        kook_service.push_order_report(order, site_url=site_url)
        if current_user.is_staff and order.player_id != current_user.id:
            flash('代报单成功，已冻结老板余额，等待老板确认支付', 'success')
        elif was_pending_confirm:
            flash('申报已更新，冻结金额已同步调整，等待老板确认支付', 'success')
        else:
            flash('申报成功，已冻结老板余额，等待老板确认支付', 'success')
        return redirect(url_for('orders.index'))

    return render_template('orders/report.html', order=order)


@orders_bp.route('/<int:order_id>/confirm', methods=['POST'])
@login_required
def confirm(order_id):
    """老板确认"""
    order = Order.query.get_or_404(order_id)

    if order.boss_id != current_user.id and not current_user.is_staff:
        flash('无权限确认该订单', 'error')
        return redirect(url_for('orders.index'))

    success, error = order_service.confirm_order(order)
    if not success:
        flash(error, 'error')
    else:
        db.session.commit()
        # KOOK 推送: 确认通知给陪玩
        kook_service.push_order_confirm(order)
        flash('订单已确认，佣金已到账', 'success')

    return redirect(request.referrer or url_for('orders.index'))


@orders_bp.route('/<int:order_id>/action/<action>', methods=['POST'])
@login_required
def order_action(order_id, action):
    """冻结/解冻/退款: 客服+"""
    order = Order.query.get_or_404(order_id)

    if action == 'freeze':
        if not current_user.is_staff:
            flash('需要客服及以上权限', 'error')
            return redirect(url_for('orders.index'))
        success, error = order_service.freeze_order(order)
        if success:
            db.session.commit()
            flash('订单已冻结', 'success')
        else:
            flash(error, 'error')

    elif action == 'unfreeze':
        if not current_user.is_staff:
            flash('需要客服及以上权限', 'error')
            return redirect(url_for('orders.index'))
        success, error = order_service.unfreeze_order(order)
        if success:
            db.session.commit()
            if order.status == 'paid':
                flash('订单已解冻，佣金已发放', 'success')
            else:
                flash('订单已解冻', 'success')
        else:
            flash(error, 'error')

    elif action == 'settle':
        flash('护航/代肝订单无需手动结算：创建后已自动结算并冻结', 'info')

    elif action == 'refund':
        if not current_user.is_staff:
            flash('退款操作需要客服及以上权限', 'error')
            return redirect(url_for('orders.index'))
        notify_operator = current_user.staff_display_name
        success, error = order_service.refund_order(order)
        if success:
            db.session.commit()
            # KOOK 推送: 订单退款后私信老板和陪玩
            kook_service.push_order_refund_notice(order, operator=notify_operator)
            flash('退款成功', 'success')
        else:
            flash(error, 'error')

    else:
        flash('未知操作', 'error')

    return redirect(request.referrer or url_for('orders.index'))


@orders_bp.route('/<int:order_id>/delete', methods=['POST'])
@login_required
def delete(order_id):
    """删除订单: 客服/管理员"""
    if not current_user.is_staff:
        flash('需要客服及以上权限', 'error')
        return redirect(url_for('orders.index'))

    order = Order.query.get_or_404(order_id)
    # 先缓存通知所需信息（订单删除后对象会失效）
    notify_boss = order.boss
    notify_player = order.player
    notify_order_no = order.order_no
    notify_game = order.project_display
    notify_operator = current_user.staff_display_name
    success, error = order_service.delete_order(order, current_user.id)
    if success:
        db.session.commit()
        # KOOK 推送: 订单删除后私信老板和陪玩
        kook_service.push_order_delete_notice(
            notify_order_no,
            boss=notify_boss,
            player=notify_player,
            game=notify_game,
            operator=notify_operator,
        )
        flash('订单已删除', 'success')
    else:
        db.session.rollback()
        flash(error, 'error')

    return redirect(request.referrer or url_for('orders.index'))
