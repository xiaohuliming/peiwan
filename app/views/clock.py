from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime, timedelta
from app.models.clock import ClockRecord
from app.models.user import User
from app.extensions import db

clock_bp = Blueprint('clock', __name__)


def can_clock():
    """仅客服身份可打卡；管理员仅可查看，不参与打卡。"""
    return current_user.has_role('staff') and not current_user.is_admin


def _clock_user_query():
    """可参与打卡的账号：客服身份，且非管理员账号。"""
    return User.query.filter(
        User.role_filter_expr('staff'),
        ~User.role.in_(['admin', 'superadmin'])
    )


def auto_timeout_check(user=None):
    """检查并自动超时超过4小时的打卡记录。user=None 时检查所有人"""
    now = datetime.now()
    timeout_threshold = now - timedelta(hours=4)

    query = ClockRecord.query.filter(
        ClockRecord.status == 'clocked_in',
        ClockRecord.clock_in < timeout_threshold
    )
    if user:
        query = query.filter(ClockRecord.user_id == user.id)

    expired_records = query.all()

    for record in expired_records:
        record.clock_out = record.clock_in + timedelta(hours=4)
        record.duration_minutes = 240
        record.status = 'auto_timeout'

    if expired_records:
        db.session.commit()


@clock_bp.route('/')
@login_required
def index():
    # 权限检查：仅客服可打卡；管理员可查看
    if not (can_clock() or current_user.is_admin):
        flash('您没有权限访问此页面', 'error')
        return redirect(url_for('dashboard.index'))

    # 管理员视图 — 查看客服打卡数据
    if current_user.is_admin:
        return _admin_view()

    # 客服视图 — 自己的打卡
    return _worker_view()


def _admin_view():
    """管理员查看客服打卡数据"""
    # 自动超时：检查所有人
    auto_timeout_check()

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    filter_date = request.args.get('date', '')
    filter_user = request.args.get('user_id', '', type=str)
    page = request.args.get('page', 1, type=int)

    # 统计：当前在班人数（仅客服）
    online_count = db.session.query(func.count(ClockRecord.id)).join(
        User, ClockRecord.user_id == User.id
    ).filter(
        ClockRecord.status == 'clocked_in',
        User.role_filter_expr('staff'),
        ~User.role.in_(['admin', 'superadmin'])
    ).scalar() or 0

    # 统计：今日打卡人数（仅客服）
    today_clocked_count = db.session.query(func.count(func.distinct(ClockRecord.user_id))).join(
        User, ClockRecord.user_id == User.id
    ).filter(
        ClockRecord.clock_in >= today_start,
        User.role_filter_expr('staff'),
        ~User.role.in_(['admin', 'superadmin'])
    ).scalar() or 0

    # 统计：今日总工时（仅客服）
    today_total = db.session.query(func.sum(ClockRecord.duration_minutes)).join(
        User, ClockRecord.user_id == User.id
    ).filter(
        ClockRecord.clock_in >= today_start,
        ClockRecord.status != 'clocked_in',
        User.role_filter_expr('staff'),
        ~User.role.in_(['admin', 'superadmin'])
    ).scalar() or 0

    # 历史记录查询（仅客服）
    history_query = ClockRecord.query.join(User, ClockRecord.user_id == User.id).filter(
        User.role_filter_expr('staff'),
        ~User.role.in_(['admin', 'superadmin'])
    ).order_by(ClockRecord.clock_in.desc())

    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d')
            date_end = date_obj + timedelta(days=1)
            history_query = history_query.filter(
                ClockRecord.clock_in >= date_obj,
                ClockRecord.clock_in < date_end
            )
        except ValueError:
            pass

    if filter_user:
        try:
            history_query = history_query.filter(ClockRecord.user_id == int(filter_user))
        except ValueError:
            pass

    history = history_query.paginate(page=page, per_page=15, error_out=False)

    # 当前在班人员列表
    online_records = ClockRecord.query.join(User, ClockRecord.user_id == User.id).filter(
        ClockRecord.status == 'clocked_in',
        User.role_filter_expr('staff'),
        ~User.role.in_(['admin', 'superadmin'])
    ).order_by(ClockRecord.clock_in.asc()).all()

    # 可筛选的员工列表
    workers = _clock_user_query().order_by(User.role, User.nickname).all()

    return render_template('clock/index.html',
                           is_admin_view=True,
                           online_count=online_count,
                           today_clocked_count=today_clocked_count,
                           today_total_minutes=today_total,
                           online_records=online_records,
                           history=history,
                           filter_date=filter_date,
                           filter_user=filter_user,
                           workers=workers)


def _worker_view():
    """客服自己的打卡视图"""
    # 自动超时检查
    auto_timeout_check(current_user)

    # 当前打卡状态
    active_clock = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id,
        ClockRecord.status == 'clocked_in'
    ).first()

    # 今日统计
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_records = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id,
        ClockRecord.clock_in >= today_start
    ).all()

    today_clock_count = len(today_records)
    today_total_minutes = sum(r.duration_minutes for r in today_records if r.status != 'clocked_in')
    if active_clock:
        elapsed = (datetime.now() - active_clock.clock_in).total_seconds() / 60
        today_total_minutes += int(elapsed)

    # 历史记录（支持日期筛选）
    filter_date = request.args.get('date', '')
    history_query = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id
    ).order_by(ClockRecord.clock_in.desc())

    if filter_date:
        try:
            date_obj = datetime.strptime(filter_date, '%Y-%m-%d')
            date_end = date_obj + timedelta(days=1)
            history_query = history_query.filter(
                ClockRecord.clock_in >= date_obj,
                ClockRecord.clock_in < date_end
            )
        except ValueError:
            pass

    page = request.args.get('page', 1, type=int)
    history = history_query.paginate(page=page, per_page=10, error_out=False)

    return render_template('clock/index.html',
                           is_admin_view=False,
                           active_clock=active_clock,
                           today_clock_count=today_clock_count,
                           today_total_minutes=today_total_minutes,
                           history=history,
                           filter_date=filter_date)


@clock_bp.route('/in', methods=['POST'])
@login_required
def clock_in():
    if not can_clock():
        flash('您没有权限执行此操作', 'error')
        return redirect(url_for('dashboard.index'))

    existing = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id,
        ClockRecord.status == 'clocked_in'
    ).first()

    if existing:
        flash('您已经在打卡状态中，请先下班打卡', 'error')
        return redirect(url_for('clock.index'))

    record = ClockRecord(
        user_id=current_user.id,
        clock_in=datetime.now(),
        status='clocked_in'
    )
    db.session.add(record)
    db.session.commit()

    flash('上班打卡成功！', 'success')
    return redirect(url_for('clock.index'))


@clock_bp.route('/out', methods=['POST'])
@login_required
def clock_out():
    if not can_clock():
        flash('您没有权限执行此操作', 'error')
        return redirect(url_for('dashboard.index'))

    record = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id,
        ClockRecord.status == 'clocked_in'
    ).first()

    if not record:
        flash('当前没有进行中的打卡记录', 'error')
        return redirect(url_for('clock.index'))

    now = datetime.now()
    record.clock_out = now
    record.duration_minutes = int((now - record.clock_in).total_seconds() / 60)
    record.status = 'clocked_out'
    db.session.commit()

    flash(f'下班打卡成功！本次工时 {record.duration_display}', 'success')
    return redirect(url_for('clock.index'))
