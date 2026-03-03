from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime, timedelta
from decimal import Decimal
from app.models.user import User
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.finance import WithdrawRequest, CommissionLog
from app.extensions import db

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def index():
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

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

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
    week_start = today_start - timedelta(days=today_start.weekday())
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
        days.append(day_start.strftime('%a'))

    # ====== 管理统计 (仅客服/管理员) ======
    mgmt_stats = None
    todo_stats = None
    staff_perf = None
    current_period = 'day'
    current_perf_period = 'today'

    if current_user.is_staff:
        # --- 管理统计卡片 ---
        current_period = request.args.get('period', 'day')
        if current_period == 'week':
            start_date = today_start - timedelta(days=today_start.weekday())
        elif current_period == 'month':
            start_date = today_start.replace(day=1)
        else:
            start_date = today_start

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

        mgmt_stats = {
            'revenue': period_revenue,
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
            perf_start_date = today_start - timedelta(days=today_start.weekday())
        elif current_perf_period == 'month':
            perf_start_date = today_start.replace(day=1)
        else:
            perf_start_date = today_start

        staff_perf_raw = db.session.query(
            User,
            func.count(Order.id).label('order_count'),
            func.coalesce(func.sum(Order.duration), 0).label('total_duration')
        ).join(Order, User.id == Order.staff_id).filter(
            Order.created_at >= perf_start_date
        ).group_by(User.id).all()

        staff_perf = []
        for staff_user, order_count, total_duration in staff_perf_raw:
            staff_perf.append({
                'user': staff_user,
                'order_count': order_count,
                'total_duration': float(total_duration),
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
