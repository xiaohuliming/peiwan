from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.models.user import User
from app.models.project import ProjectItem
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.finance import WithdrawRequest, CommissionLog, BalanceLog
from app.extensions import db
from app.utils.time_utils import BJ_TZ

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def home():
    """平台默认首页：进入个人中心。"""
    return redirect(url_for('profile.index'))


@dashboard_bp.route('/dashboard')
@login_required
def index():
    def _bj_period_start_utc(period_key: str):
        bj_now = datetime.now(BJ_TZ)
        if period_key == 'week':
            start_day = bj_now.date() - timedelta(days=bj_now.weekday())
        elif period_key == 'month':
            start_day = bj_now.date().replace(day=1)
        else:
            start_day = bj_now.date()
        start_bj = datetime(start_day.year, start_day.month, start_day.day, tzinfo=BJ_TZ)
        return start_bj.astimezone(timezone.utc).replace(tzinfo=None)

    def _calc_growth(current, previous):
        current_val = float(current or 0)
        prev_val = float(previous or 0)
        if prev_val == 0:
            return 100.0 if current_val > 0 else 0.0
        return ((current_val - prev_val) / prev_val) * 100

    def _sum_order_total(start_at, end_at=None, boss_id=None):
        query = db.session.query(func.sum(Order.total_price)).filter(
            Order.status.in_(paid_statuses),
            Order.created_at >= start_at,
        )
        if end_at:
            query = query.filter(Order.created_at < end_at)
        if boss_id:
            query = query.filter(Order.boss_id == boss_id)
        return query.scalar() or Decimal('0.00')

    def _sum_gift_total(start_at, end_at=None, boss_id=None):
        query = db.session.query(func.sum(GiftOrder.total_price)).filter(
            GiftOrder.status == 'paid',
            GiftOrder.created_at >= start_at,
        )
        if end_at:
            query = query.filter(GiftOrder.created_at < end_at)
        if boss_id:
            query = query.filter(GiftOrder.boss_id == boss_id)
        return query.scalar() or Decimal('0.00')

    def _sum_player_income(user_id, start_at, end_at=None):
        query = db.session.query(func.sum(CommissionLog.amount)).filter(
            CommissionLog.user_id == user_id,
            CommissionLog.change_type.in_(['order_income', 'gift_income', 'refund_deduct']),
            CommissionLog.created_at >= start_at,
        )
        if end_at:
            query = query.filter(CommissionLog.created_at < end_at)
        return query.scalar() or Decimal('0.00')

    # Base query filters based on role
    order_base_query = Order.query
    if current_user.is_god:
        order_base_query = order_base_query.filter(Order.boss_id == current_user.id)
    elif current_user.is_player:
        order_base_query = order_base_query.filter(Order.player_id == current_user.id)

    today_start = _bj_period_start_utc('day')  # 北京时间今天00:00 → UTC

    # 1. Today's Stats
    paid_statuses = ['pending_pay', 'paid']

    if current_user.is_player:
        today_revenue = _sum_player_income(current_user.id, today_start)
    elif current_user.is_god:
        today_revenue = _sum_order_total(today_start, boss_id=current_user.id) + _sum_gift_total(today_start, boss_id=current_user.id)
    else:
        today_revenue = _sum_order_total(today_start) + _sum_gift_total(today_start)

    # Yesterday's Stats for comparison
    yesterday_start = today_start - timedelta(days=1)

    if current_user.is_player:
        yesterday_revenue = _sum_player_income(current_user.id, yesterday_start, today_start)
    elif current_user.is_god:
        yesterday_revenue = _sum_order_total(yesterday_start, today_start, current_user.id) + _sum_gift_total(yesterday_start, today_start, current_user.id)
    else:
        yesterday_revenue = _sum_order_total(yesterday_start, today_start) + _sum_gift_total(yesterday_start, today_start)

    revenue_growth = 0
    if yesterday_revenue > 0:
        revenue_growth = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100
        revenue_growth = float(revenue_growth)
    elif today_revenue > 0:
        revenue_growth = 100.0

    # 2. Ongoing Orders
    ongoing_orders_count = order_base_query.filter(
        Order.status.in_(['pending_report', 'pending_confirm'])
    ).count()
    pending_confirm_count = order_base_query.filter(Order.status == 'pending_confirm').count()

    # 3. Active Players / Completed Orders Count
    if current_user.is_staff or current_user.is_admin:
        stat_count = db.session.query(func.count(func.distinct(Order.player_id))).filter(
            Order.created_at >= today_start
        ).scalar() or 0
        yesterday_stat_count = db.session.query(func.count(func.distinct(Order.player_id))).filter(
            Order.created_at >= yesterday_start,
            Order.created_at < today_start
        ).scalar() or 0
        stat_label = "活跃陪玩"
    elif current_user.is_player:
        stat_count = order_base_query.filter(
            Order.created_at >= today_start,
            Order.status == 'paid'
        ).count()
        yesterday_stat_count = order_base_query.filter(
            Order.created_at >= yesterday_start,
            Order.created_at < today_start,
            Order.status == 'paid'
        ).count()
        stat_label = "今日接单"
    else:
        stat_count = order_base_query.filter(
            Order.created_at >= today_start
        ).count()
        yesterday_stat_count = order_base_query.filter(
            Order.created_at >= yesterday_start,
            Order.created_at < today_start
        ).count()
        stat_label = "今日下单"
    stat_growth = _calc_growth(stat_count, yesterday_stat_count)

    # 4. 本周完成单数（真实统计）
    week_start = _bj_period_start_utc('week')  # 北京时间本周一00:00 → UTC
    last_week_start = week_start - timedelta(days=7)
    completed_week = order_base_query.filter(
        Order.created_at >= week_start,
        Order.status == 'paid'
    ).count()
    completed_last_week = order_base_query.filter(
        Order.created_at >= last_week_start,
        Order.created_at < week_start,
        Order.status == 'paid'
    ).count()
    card4_label = "本周完成单数"
    card4_value = completed_week
    card4_growth = _calc_growth(completed_week, completed_last_week)

    # 5. Recent Orders
    recent_orders = order_base_query.order_by(Order.created_at.desc()).limit(5).all()

    # 6. Top Players
    top_players = []
    if current_user.is_staff or current_user.is_god:
        top_players = db.session.query(
            User,
            func.sum(CommissionLog.amount).label('total_income')
        ).join(CommissionLog, User.id == CommissionLog.user_id).filter(
            User.role_filter_expr('player'),
            CommissionLog.change_type.in_(['order_income', 'gift_income', 'refund_deduct']),
            CommissionLog.created_at >= week_start,
        ).group_by(User.id).order_by(func.sum(CommissionLog.amount).desc()).limit(3).all()

    # 7. Chart Data (Last 7 days)
    chart_data = []
    days = []
    bj_today = datetime.now(BJ_TZ).date()
    for i in range(6, -1, -1):
        day_start = today_start - timedelta(days=i)
        day_end = day_start + timedelta(days=1)

        if current_user.is_player:
            daily_rev = _sum_player_income(current_user.id, day_start, day_end)
        elif current_user.is_god:
            daily_rev = _sum_order_total(day_start, day_end, current_user.id) + _sum_gift_total(day_start, day_end, current_user.id)
        else:
            daily_rev = _sum_order_total(day_start, day_end) + _sum_gift_total(day_start, day_end)

        chart_data.append(float(daily_rev))
        bj_day = bj_today - timedelta(days=i)
        days.append(bj_day.strftime('%a'))

    # ====== 管理统计 (仅客服/管理员) ======
    mgmt_stats = None
    todo_stats = None
    staff_perf = None
    current_period = 'day'
    current_perf_period = 'today'

    if current_user.is_staff:
        # --- 管理统计卡片 ---
        current_period = request.args.get('period', 'day')
        start_date = _bj_period_start_utc(current_period)

        period_revenue = _sum_order_total(start_date) + _sum_gift_total(start_date)

        period_order_count = Order.query.filter(
            Order.status.in_(paid_statuses),
            Order.created_at >= start_date
        ).count() + GiftOrder.query.filter(
            GiftOrder.status == 'paid',
            GiftOrder.created_at >= start_date
        ).count()

        total_customers = User.query.filter(User.role == 'god').count()
        total_orders = Order.query.count() + GiftOrder.query.count()
        period_recharge_rows = BalanceLog.query.filter(
            BalanceLog.change_type == 'recharge',
            BalanceLog.amount > 0,
            BalanceLog.operator_id.isnot(None),
            ~func.coalesce(BalanceLog.reason, '').ilike('%赠金%'),
            BalanceLog.created_at >= start_date,
        ).with_entities(
            BalanceLog.id,
            BalanceLog.user_id,
            BalanceLog.operator_id,
            BalanceLog.amount,
            BalanceLog.created_at,
        ).all()

        refunded_recharge_ids = set()
        period_user_ids = {row.user_id for row in period_recharge_rows}
        if period_user_ids:
            from app.views.finance import _build_refunded_recharge_ids

            all_recharge_rows = BalanceLog.query.filter(
                BalanceLog.change_type == 'recharge',
                BalanceLog.amount > 0,
                BalanceLog.operator_id.isnot(None),
                ~func.coalesce(BalanceLog.reason, '').ilike('%赠金%'),
                BalanceLog.user_id.in_(list(period_user_ids)),
            ).with_entities(
                BalanceLog.id,
                BalanceLog.user_id,
                BalanceLog.operator_id,
                BalanceLog.amount,
                BalanceLog.created_at,
            ).all()

            refund_rows = BalanceLog.query.filter(
                BalanceLog.change_type == 'admin_adjust',
                BalanceLog.amount < 0,
                BalanceLog.operator_id.isnot(None),
                BalanceLog.user_id.in_(list(period_user_ids)),
            ).with_entities(
                BalanceLog.id,
                BalanceLog.user_id,
                BalanceLog.operator_id,
                BalanceLog.amount,
                BalanceLog.created_at,
                BalanceLog.reason,
            ).all()

            refunded_recharge_ids = _build_refunded_recharge_ids(all_recharge_rows, refund_rows)

        visible_recharge_rows = [row for row in period_recharge_rows if row.id not in refunded_recharge_ids]
        recharge_total = sum((Decimal(str(row.amount or 0)) for row in visible_recharge_rows), Decimal('0.00'))
        recharge_count = len(visible_recharge_rows)

        mgmt_stats = {
            'revenue': period_revenue,
            'recharge_total': recharge_total or Decimal('0.00'),
            'recharge_count': recharge_count or 0,
            'order_count': period_order_count,
            'customer_count': total_customers,
            'total_orders': total_orders,
        }

        # --- 待办事项 ---
        frozen_orders_count = Order.query.filter(Order.freeze_status == 'frozen').count()
        pending_withdrawals_count = WithdrawRequest.query.filter(WithdrawRequest.status == 'pending').count()

        todo_stats = {
            'frozen_orders': frozen_orders_count,
            'pending_withdrawals': pending_withdrawals_count,
        }

        # --- 客服绩效 ---
        current_perf_period = request.args.get('perf_period', 'today')
        if current_perf_period == 'week':
            perf_start_date = _bj_period_start_utc('week')
        elif current_perf_period == 'month':
            perf_start_date = _bj_period_start_utc('month')
        else:
            perf_start_date = _bj_period_start_utc('day')

        # 客服绩效按结算时间口径统计（优先 pay_time，兼容历史回退 confirm_time/created_at）
        perf_time_expr = func.coalesce(Order.pay_time, Order.confirm_time, Order.created_at)
        # 历史清洗兼容：
        # 早期部分订单 order_type 被错误写为 normal，
        # 这里优先信任 project_item.project_type，避免护航/代练污染客服派单时长。
        project_type_expr = func.lower(func.coalesce(ProjectItem.project_type, ''))
        raw_order_type_expr = func.lower(func.coalesce(Order.order_type, 'normal'))
        order_type_expr = db.case(
            (project_type_expr.in_(('normal', 'escort', 'training')), project_type_expr),
            else_=raw_order_type_expr
        )
        billing_type_expr = func.lower(func.coalesce(ProjectItem.billing_type, 'hour'))

        # 订单绩效：
        # - 所有绩效项仅统计已结算(paid)
        # - 累计订单时长：排除护航/代练订单，仅统计常规陪玩订单
        staff_perf_raw = db.session.query(
            User,
            func.count(Order.id).label('order_count'),
            # 按小时计费的常规订单时长
            func.coalesce(func.sum(
                db.case((
                    db.and_(
                        order_type_expr == 'normal',
                        billing_type_expr == 'hour',
                    ),
                    Order.duration
                ), else_=0)
            ), 0).label('total_hours'),
            # 按局计费的常规订单局数
            func.coalesce(func.sum(
                db.case((
                    db.and_(
                        order_type_expr == 'normal',
                        billing_type_expr == 'round',
                    ),
                    Order.duration
                ), else_=0)
            ), 0).label('total_rounds'),
            # 常规陪玩订单数(1元/单)
            func.coalesce(func.sum(
                db.case((order_type_expr == 'normal', 1), else_=0)
            ), 0).label('normal_count'),
            # 护航订单总额(1%)
            func.coalesce(func.sum(
                db.case((order_type_expr == 'escort', Order.total_price), else_=0)
            ), 0).label('escort_total'),
            # 代练订单总额(1%)
            func.coalesce(func.sum(
                db.case((order_type_expr == 'training', Order.total_price), else_=0)
            ), 0).label('training_total'),
        ).join(Order, User.id == Order.staff_id
        ).outerjoin(ProjectItem, Order.project_item_id == ProjectItem.id
        ).filter(
            perf_time_expr >= perf_start_date,
            Order.status == 'paid',
        ).group_by(User.id).all()

        # 礼物派发绩效：按客服分组
        gift_perf_raw = db.session.query(
            GiftOrder.staff_id,
            func.count(GiftOrder.id).label('gift_count'),
            func.coalesce(func.sum(GiftOrder.total_price), 0).label('gift_total'),
        ).filter(
            GiftOrder.staff_id.isnot(None),
            GiftOrder.status == 'paid',
            GiftOrder.created_at >= perf_start_date,
        ).group_by(GiftOrder.staff_id).all()
        gift_map = {row.staff_id: {'gift_count': row.gift_count, 'gift_total': float(row.gift_total)} for row in gift_perf_raw}

        staff_perf = []
        for staff_user, order_count, total_hours, total_rounds, normal_count, escort_total, training_total in staff_perf_raw:
            gd = gift_map.pop(staff_user.id, {'gift_count': 0, 'gift_total': 0})
            # 提成: 常规1元/单 + 护航/代练1% + 礼物1%
            escort_amount = float(escort_total or 0)
            training_amount = float(training_total or 0)
            commission = float(normal_count or 0) * 1.0 + (escort_amount + training_amount) * 0.01 + gd['gift_total'] * 0.01
            staff_perf.append({
                'user': staff_user,
                'order_count': order_count,
                'total_hours': float(total_hours),
                'total_rounds': float(total_rounds),
                'gift_count': gd['gift_count'],
                'gift_total': round(float(gd['gift_total']), 2),
                'escort_total': round(escort_amount, 2),
                'training_total': round(training_amount, 2),
                'commission': round(commission, 2),
            })

        # 补充只派发了礼物但没有订单的客服
        for staff_id, gd in gift_map.items():
            staff_user = db.session.get(User, staff_id)
            if staff_user:
                commission = gd['gift_total'] * 0.01
                staff_perf.append({
                    'user': staff_user,
                    'order_count': 0,
                    'total_hours': 0,
                    'total_rounds': 0,
                    'gift_count': gd['gift_count'],
                    'gift_total': round(float(gd['gift_total']), 2),
                    'escort_total': 0.0,
                    'training_total': 0.0,
                    'commission': round(commission, 2),
                })

    return render_template('dashboard/index.html',
                           today_revenue=today_revenue,
                           revenue_growth=revenue_growth,
                           stat_count=stat_count,
                           stat_growth=stat_growth,
                           stat_label=stat_label,
                           ongoing_orders_count=ongoing_orders_count,
                           pending_confirm_count=pending_confirm_count,
                           card4_label=card4_label,
                           card4_value=card4_value,
                           card4_growth=card4_growth,
                           recent_orders=recent_orders,
                           top_players=top_players,
                           chart_data=chart_data,
                           days=days,
                           mgmt_stats=mgmt_stats,
                           todo_stats=todo_stats,
                           staff_perf=staff_perf,
                           current_period=current_period,
                           current_perf_period=current_perf_period)
