from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime, timedelta
from app.models.clock import ClockRecord
from app.models.user import User
from app.extensions import db

clock_bp = Blueprint('clock', __name__)
BJ_OFFSET = timedelta(hours=8)


def _utc_now():
    """统一使用 UTC 存储和计算时间。"""
    return datetime.utcnow()


def _beijing_day_range_utc(date_str=None):
    """返回北京时间某日对应的 UTC 起止区间 [start, end)。"""
    if date_str:
        day = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        day = (_utc_now() + BJ_OFFSET).date()
    start_utc = datetime(day.year, day.month, day.day) - BJ_OFFSET
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc


def can_clock():
    """拥有客服身份（主角色或标签）的账号可打卡。"""
    return current_user.has_role('staff')


def _clock_user_query():
    """可参与打卡的账号：拥有客服身份（主角色或标签）。"""
    return User.query.filter(User.role_filter_expr('staff'))


def _repair_legacy_local_clock_records(user=None):
    """
    修复历史错误时区数据（幂等）：
    - 旧版本曾把 clock_in/clock_out 直接按北京时间写入（naive）；
    - created_at 一直是 UTC。
    因此可用 (clock_in - created_at) 约等于 +8h 识别旧数据，并回拨 8h。
    """
    query = ClockRecord.query.filter(ClockRecord.clock_in.isnot(None))
    if user:
        query = query.filter(ClockRecord.user_id == user.id)

    dirty_records = query.order_by(ClockRecord.id.desc()).limit(500).all()
    changed = False

    for record in dirty_records:
        if not record.clock_in:
            continue

        row_changed = False
        diff_in_hours = None
        if record.created_at:
            diff_in_hours = (record.clock_in - record.created_at).total_seconds() / 3600.0

        # 旧数据：clock_in 比 created_at 大约 8 小时
        is_legacy_local = diff_in_hours is not None and 6.0 <= diff_in_hours <= 10.0

        if is_legacy_local:
            # 若已出现 out < in，说明 out 可能已被回拨过，仅回拨 in
            if record.clock_out and record.clock_out < record.clock_in:
                record.clock_in = record.clock_in - BJ_OFFSET
            else:
                record.clock_in = record.clock_in - BJ_OFFSET
                if record.clock_out:
                    record.clock_out = record.clock_out - BJ_OFFSET
            row_changed = True
        elif record.clock_out and record.clock_out < record.clock_in:
            # 兜底修复：处理“上班晚于下班”的异常脏数据（常见于误回拨一半）
            record.clock_in = record.clock_in - BJ_OFFSET
            row_changed = True

        # 已下班记录修正后重算时长，避免出现负值
        if row_changed and record.status != 'clocked_in' and record.clock_out and record.clock_in:
            minutes = int((record.clock_out - record.clock_in).total_seconds() / 60)
            record.duration_minutes = max(0, minutes)

        if row_changed:
            changed = True

    if changed:
        db.session.commit()


def auto_timeout_check(user=None):
    """检查并自动超时超过4小时的打卡记录。user=None 时检查所有人"""
    _repair_legacy_local_clock_records(user)

    now = _utc_now()
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
    # 权限检查：客服身份可打卡；管理员可查看管理页
    if not (can_clock() or current_user.is_admin):
        flash('您没有权限访问此页面', 'error')
        return redirect(url_for('dashboard.index'))

    mode = (request.args.get('mode') or '').strip().lower()

    # 管理员 + 客服身份：可在管理页与个人打卡页切换
    if current_user.is_admin and can_clock():
        if mode == 'mine':
            return _worker_view()
        return _admin_view()

    # 纯管理员：仅管理视图
    if current_user.is_admin:
        return _admin_view()

    # 客服视图（含带客服标签的其他主角色）— 自己的打卡
    return _worker_view()


def _admin_view():
    """管理员查看客服打卡数据"""
    # 自动超时：检查所有人
    auto_timeout_check()

    today_start, _ = _beijing_day_range_utc()
    filter_date = request.args.get('date', '')
    filter_user = request.args.get('user_id', '', type=str)
    page = request.args.get('page', 1, type=int)

    # 统计：当前在班人数（客服身份，含身份标签）
    online_count = db.session.query(func.count(ClockRecord.id)).join(
        User, ClockRecord.user_id == User.id
    ).filter(
        ClockRecord.status == 'clocked_in',
        User.role_filter_expr('staff')
    ).scalar() or 0

    # 统计：今日打卡人数（客服身份，含身份标签）
    today_clocked_count = db.session.query(func.count(func.distinct(ClockRecord.user_id))).join(
        User, ClockRecord.user_id == User.id
    ).filter(
        ClockRecord.clock_in >= today_start,
        User.role_filter_expr('staff')
    ).scalar() or 0

    # 统计：今日总工时（客服身份，含身份标签）
    today_total = db.session.query(func.sum(ClockRecord.duration_minutes)).join(
        User, ClockRecord.user_id == User.id
    ).filter(
        ClockRecord.clock_in >= today_start,
        ClockRecord.status != 'clocked_in',
        User.role_filter_expr('staff')
    ).scalar() or 0

    # 历史记录查询（客服身份，含身份标签）
    history_query = ClockRecord.query.join(User, ClockRecord.user_id == User.id).filter(
        User.role_filter_expr('staff')
    ).order_by(ClockRecord.clock_in.desc())

    if filter_date:
        try:
            date_obj, date_end = _beijing_day_range_utc(filter_date)
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
        User.role_filter_expr('staff')
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
    today_start, _ = _beijing_day_range_utc()
    today_records = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id,
        ClockRecord.clock_in >= today_start
    ).all()

    today_clock_count = len(today_records)
    today_total_minutes = sum(r.duration_minutes for r in today_records if r.status != 'clocked_in')
    if active_clock:
        elapsed = (_utc_now() - active_clock.clock_in).total_seconds() / 60
        today_total_minutes += int(elapsed)

    # 历史记录（支持日期筛选）
    filter_date = request.args.get('date', '')
    history_query = ClockRecord.query.filter(
        ClockRecord.user_id == current_user.id
    ).order_by(ClockRecord.clock_in.desc())

    if filter_date:
        try:
            date_obj, date_end = _beijing_day_range_utc(filter_date)
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
        clock_in=_utc_now(),
        status='clocked_in'
    )
    db.session.add(record)
    db.session.commit()

    flash('上班打卡成功！', 'success')
    if current_user.is_admin:
        return redirect(url_for('clock.index', mode='mine'))
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
        if current_user.is_admin:
            return redirect(url_for('clock.index', mode='mine'))
        return redirect(url_for('clock.index'))

    now = _utc_now()
    record.clock_out = now
    record.duration_minutes = int((now - record.clock_in).total_seconds() / 60)
    record.status = 'clocked_out'
    db.session.commit()

    flash(f'下班打卡成功！本次工时 {record.duration_display}', 'success')
    if current_user.is_admin:
        return redirect(url_for('clock.index', mode='mine'))
    return redirect(url_for('clock.index'))
