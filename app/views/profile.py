from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
from app.models.order import Order
from app.models.finance import CommissionLog
from app.extensions import db

profile_bp = Blueprint('profile', __name__)

@profile_bp.route('/')
@login_required
def index():
    current_tab = request.args.get('tab', 'info')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    page = request.args.get('page', 1, type=int)

    orders = None
    earnings = None

    if current_tab == 'orders':
        # 根据主角色查询订单，避免默认身份标签导致错位
        if current_user.role == 'god':
            query = Order.query.filter(Order.boss_id == current_user.id)
        elif current_user.role == 'player':
            query = Order.query.filter(Order.player_id == current_user.id)
        elif current_user.role in ('staff', 'admin', 'superadmin'):
            query = Order.query.filter(Order.staff_id == current_user.id)
        else:
            query = Order.query.filter(
                (Order.boss_id == current_user.id) | (Order.player_id == current_user.id)
            )

        # 日期筛选
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Order.created_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                # 包含结束日期当天
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(Order.created_at <= end_dt)
            except ValueError:
                pass

        orders = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=10, error_out=False)

    elif current_tab == 'earnings' and current_user.is_player:
        query = CommissionLog.query.filter(CommissionLog.user_id == current_user.id)

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(CommissionLog.created_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(CommissionLog.created_at <= end_dt)
            except ValueError:
                pass

        earnings = query.order_by(CommissionLog.created_at.desc()).paginate(page=page, per_page=10, error_out=False)

    return render_template('profile/index.html',
                           current_tab=current_tab,
                           orders=orders,
                           earnings=earnings,
                           start_date=start_date,
                           end_date=end_date)

@profile_bp.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    current_user.anonymous_recharge = request.form.get('anonymous_recharge') == 'on'
    current_user.anonymous_consume = request.form.get('anonymous_consume') == 'on'
    current_user.anonymous_gift_send = request.form.get('anonymous_gift_send') == 'on'
    current_user.anonymous_gift_recv = request.form.get('anonymous_gift_recv') == 'on'

    try:
        db.session.commit()
        flash('设置已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash('设置更新失败', 'error')

    return redirect(url_for('profile.index'))


@profile_bp.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    """编辑个人资料（昵称/陪玩昵称）"""
    nickname = request.form.get('nickname', '').strip()
    player_nickname = request.form.get('player_nickname', '').strip()

    if not nickname:
        flash('客户昵称不能为空', 'error')
        return redirect(url_for('profile.index', tab='info'))

    current_user.nickname = nickname
    if current_user.role == 'player':
        current_user.player_nickname = player_nickname or current_user.player_nickname or nickname

    try:
        db.session.commit()
        flash('资料已更新', 'success')
    except Exception:
        db.session.rollback()
        flash('资料更新失败', 'error')

    return redirect(url_for('profile.index', tab='info'))
