"""语音(挂机)统计服务

数据流:
  bot.on_joined_channel  → open_session()    写入 active VoiceSession
  bot.on_exited_channel  → close_session()   把 active 的 close 掉,聚合到 VoiceDailyStat
  scheduler.truncate_orphan_sessions(每5分钟) 把 active 但超过 truncate_hours 的强制截断
  scheduler.split_cross_day_sessions(每日 BJ 00:01) 把跨日 active session 在 23:59:59 截断,然后从 00:00:00 接续

时间约定: joined_at / left_at 用 UTC datetime;stat_date 用北京时间自然日。
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import desc, func

try:
    import pytz
except ImportError:
    pytz = None

from app.extensions import db
from app.models.user import User
from app.models.voice import VoiceDailyStat, VoiceSession, VoiceStatConfig


BJ_TZ = pytz.timezone('Asia/Shanghai') if pytz else timezone(timedelta(hours=8), name='Asia/Shanghai')
UTC = pytz.utc if pytz else timezone.utc


# ============================ 时间工具 ============================

def bj_now():
    return datetime.now(BJ_TZ)


def bj_today():
    return bj_now().date()


def to_bj(value):
    """UTC datetime → 北京时间 datetime(带 tz)"""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(BJ_TZ)
    return value


def to_bj_date(value=None):
    if value is None:
        return bj_today()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return to_bj(value).date()
    return bj_today()


def bj_day_start_utc(day):
    """北京时间某天 00:00:00 对应的 UTC datetime(naive)"""
    if isinstance(day, datetime):
        day = to_bj(day).date()
    naive_bj = datetime.combine(day, datetime.min.time())
    if pytz:
        aware_bj = BJ_TZ.localize(naive_bj)
    else:
        aware_bj = naive_bj.replace(tzinfo=BJ_TZ)
    return aware_bj.astimezone(UTC).replace(tzinfo=None)


def bj_day_end_utc(day):
    """北京时间某天 23:59:59.999999 对应的 UTC datetime(naive)"""
    if isinstance(day, datetime):
        day = to_bj(day).date()
    naive_bj = datetime.combine(day, datetime.max.time())
    if pytz:
        aware_bj = BJ_TZ.localize(naive_bj)
    else:
        aware_bj = naive_bj.replace(tzinfo=BJ_TZ)
    return aware_bj.astimezone(UTC).replace(tzinfo=None)


def parse_id_lines(raw_value):
    import re
    text = str(raw_value or '').strip()
    if not text:
        return []
    parts = re.split(r'[\s,，;；]+', text)
    cleaned = []
    seen = set()
    for part in parts:
        item = part.strip()
        if not item or item in seen:
            continue
        cleaned.append(item)
        seen.add(item)
    return cleaned


def join_id_lines(items):
    return '\n'.join([str(item).strip() for item in items or [] if str(item).strip()])


# ============================ 配置 ============================

def get_config(create=True):
    cfg = VoiceStatConfig.query.order_by(VoiceStatConfig.id.asc()).first()
    if cfg or not create:
        return cfg
    cfg = VoiceStatConfig(
        enabled=True,
        min_session_seconds=30,
        truncate_hours=12,
    )
    cfg.whitelist_channel_id_list = []
    cfg.blacklist_channel_id_list = []
    cfg.whitelist_kook_id_list = []
    db.session.add(cfg)
    db.session.flush()
    return cfg


def _bounded_int(raw, default, min_v, max_v):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, n))


def update_config_from_form(form):
    cfg = get_config(create=True)
    cfg.enabled = form.get('enabled') == 'on'
    cfg.min_session_seconds = _bounded_int(form.get('min_session_seconds'), 30, 0, 3600)
    cfg.truncate_hours = _bounded_int(form.get('truncate_hours'), 12, 1, 72)
    cfg.whitelist_channel_id_list = parse_id_lines(form.get('whitelist_channel_ids', ''))
    cfg.blacklist_channel_id_list = parse_id_lines(form.get('blacklist_channel_ids', ''))
    cfg.whitelist_kook_id_list = parse_id_lines(form.get('whitelist_kook_ids', ''))
    db.session.commit()
    return cfg


def is_channel_tracked(cfg, channel_id):
    """白名单非空时仅统计白名单频道;黑名单永远排除。"""
    if not cfg or not cfg.enabled:
        return False
    cid = str(channel_id or '').strip()
    if not cid:
        return False
    if cid in cfg.blacklist_channel_id_list:
        return False
    whitelist = cfg.whitelist_channel_id_list
    if whitelist and cid not in whitelist:
        return False
    return True


def is_kook_excluded(cfg, kook_id):
    """白名单非空时仅统计白名单 KOOK 用户。"""
    if not cfg:
        return True
    whitelist = cfg.whitelist_kook_id_list
    if whitelist and str(kook_id or '').strip() not in whitelist:
        return True
    return False


# ============================ 会话管理 ============================

def _resolve_user(kook_id):
    if not kook_id:
        return None
    return User.query.filter_by(kook_id=str(kook_id)).first()


def open_session(kook_id, channel_id, kook_username=None, channel_name=None, occurred_at=None):
    """开始一段挂机会话。
    - 如果同 kook_id 已有 active session(无论是不是同频道),先把它 close 掉(KOOK 偶尔丢事件 / 跳频道)
    - 返回新建的 VoiceSession;若不在统计范围则返回 None
    """
    kid = str(kook_id or '').strip()
    cid = str(channel_id or '').strip()
    if not kid or not cid:
        return None

    cfg = get_config(create=True)
    if not is_channel_tracked(cfg, cid):
        return None
    if is_kook_excluded(cfg, kid):
        return None

    now_utc = occurred_at or datetime.utcnow()

    # 兜底:有任何 active session 先 close(可能是上一次的丢事件)
    existing = VoiceSession.query.filter_by(kook_id=kid, status='active').all()
    for old in existing:
        _close_session_record(old, left_at=now_utc, status='closed', note='auto-closed-on-rejoin')

    user = _resolve_user(kid)
    session = VoiceSession(
        kook_id=kid,
        user_id=user.id if user else None,
        kook_username=kook_username,
        channel_id=cid,
        channel_name=channel_name,
        joined_at=now_utc,
        status='active',
    )
    db.session.add(session)
    db.session.commit()
    return session


def close_session(kook_id, channel_id=None, occurred_at=None):
    """结束一段挂机会话。
    - 如果有 active session,优先匹配同 channel;否则关闭最近一个
    - 时长不足 min_session_seconds 也写入 session(标记 status='closed'),但**不计入** VoiceDailyStat
    """
    kid = str(kook_id or '').strip()
    if not kid:
        return None
    now_utc = occurred_at or datetime.utcnow()

    q = VoiceSession.query.filter_by(kook_id=kid, status='active')
    if channel_id:
        same_channel = q.filter_by(channel_id=str(channel_id).strip()).order_by(desc(VoiceSession.joined_at)).first()
        if same_channel:
            return _close_session_record(same_channel, left_at=now_utc, status='closed')
    session = q.order_by(desc(VoiceSession.joined_at)).first()
    if not session:
        return None
    return _close_session_record(session, left_at=now_utc, status='closed')


def _close_session_record(session, left_at, status='closed', note=None):
    if not session or session.status != 'active':
        return session
    if left_at < session.joined_at:
        left_at = session.joined_at
    duration = int((left_at - session.joined_at).total_seconds())
    session.left_at = left_at
    session.duration_seconds = duration
    session.status = status
    session.stat_date = to_bj_date(session.joined_at)
    if note:
        session.note = note
    db.session.flush()
    _apply_to_daily(session)
    db.session.commit()
    return session


def _apply_to_daily(session):
    cfg = get_config(create=False)
    threshold = int(cfg.min_session_seconds) if cfg else 30
    if (session.duration_seconds or 0) < threshold:
        return None

    stat_date = session.stat_date or to_bj_date(session.joined_at)
    row = VoiceDailyStat.query.filter_by(
        stat_date=stat_date,
        channel_id=session.channel_id,
        kook_id=session.kook_id,
    ).first()
    if not row:
        row = VoiceDailyStat(
            stat_date=stat_date,
            channel_id=session.channel_id,
            kook_id=session.kook_id,
            user_id=session.user_id,
            kook_username=session.kook_username,
            sessions_count=0,
            total_seconds=0,
        )
        db.session.add(row)

    row.sessions_count = int(row.sessions_count or 0) + 1
    row.total_seconds = int(row.total_seconds or 0) + int(session.duration_seconds or 0)
    row.last_left_at = session.left_at
    if not row.user_id and session.user_id:
        row.user_id = session.user_id
    if session.kook_username and row.kook_username != session.kook_username:
        row.kook_username = session.kook_username
    return row


# ============================ 兜底任务 ============================

def truncate_orphan_sessions(now=None):
    """超过 truncate_hours 仍是 active 的会话强制截断(防止 bot 重启 / 离开事件丢失)"""
    cfg = get_config(create=True)
    hours = max(1, int(cfg.truncate_hours or 12))
    now_utc = now or datetime.utcnow()
    cutoff = now_utc - timedelta(hours=hours)
    rows = VoiceSession.query.filter(
        VoiceSession.status == 'active',
        VoiceSession.joined_at <= cutoff,
    ).all()
    count = 0
    for s in rows:
        forced_end = min(now_utc, s.joined_at + timedelta(hours=hours))
        _close_session_record(s, left_at=forced_end, status='truncated', note=f'truncated-{hours}h')
        count += 1
    return count


def split_cross_day_sessions(now=None):
    """对每个仍 active 的会话,如果 joined_at 在北京时间昨天或更早,把它在昨日 23:59:59 截断,
    然后从今日 00:00:00 起开新 active session 接续。"""
    now_utc = now or datetime.utcnow()
    today_bj = to_bj_date(now_utc)
    rows = VoiceSession.query.filter(VoiceSession.status == 'active').all()
    splits = 0
    for s in rows:
        joined_bj_date = to_bj_date(s.joined_at)
        if joined_bj_date >= today_bj:
            continue
        # 截断到 joined_bj_date 当天 23:59:59 UTC
        end_of_join_day = bj_day_end_utc(joined_bj_date)
        if end_of_join_day <= s.joined_at:
            continue
        _close_session_record(s, left_at=end_of_join_day, status='cross_day', note='split-cross-day')
        # 新开一个从次日 00:00:00 起的 active session
        next_day_start = bj_day_start_utc(joined_bj_date + timedelta(days=1))
        if next_day_start >= now_utc:
            continue
        new_session = VoiceSession(
            kook_id=s.kook_id,
            user_id=s.user_id,
            kook_username=s.kook_username,
            channel_id=s.channel_id,
            channel_name=s.channel_name,
            joined_at=next_day_start,
            status='active',
            note='cross-day-continuation',
        )
        db.session.add(new_session)
        splits += 1
    if splits:
        db.session.commit()
    return splits


# ============================ 查询 ============================

def list_active_sessions(limit=50):
    """当前在线列表(按已挂时长倒序)。"""
    rows = (
        VoiceSession.query
        .filter_by(status='active')
        .order_by(VoiceSession.joined_at.asc())
        .limit(limit)
        .all()
    )
    now_utc = datetime.utcnow()
    items = []
    for s in rows:
        elapsed = int((now_utc - s.joined_at).total_seconds())
        items.append({
            'session': s,
            'kook_id': s.kook_id,
            'user': s.user,
            'display_name': s.display_name,
            'channel_id': s.channel_id,
            'channel_name': s.channel_name or s.channel_id,
            'joined_at': s.joined_at,
            'elapsed_seconds': max(0, elapsed),
        })
    return items


def list_daily_leaderboard(target_date=None, limit=20):
    """指定日期(默认北京时间今天)的总挂机时长排行(按 kook_id 跨频道求和)。"""
    day = to_bj_date(target_date)
    q = (
        db.session.query(
            VoiceDailyStat.kook_id.label('kook_id'),
            func.sum(VoiceDailyStat.total_seconds).label('total_seconds'),
            func.sum(VoiceDailyStat.sessions_count).label('sessions'),
            func.max(VoiceDailyStat.user_id).label('user_id'),
            func.max(VoiceDailyStat.kook_username).label('kook_username'),
            func.max(VoiceDailyStat.last_left_at).label('last_left_at'),
        )
        .filter(VoiceDailyStat.stat_date == day)
        .group_by(VoiceDailyStat.kook_id)
        .order_by(func.sum(VoiceDailyStat.total_seconds).desc())
        .limit(limit)
    )
    rows = q.all()
    user_map = _user_map_for(rows)
    items = []
    for rank, row in enumerate(rows, start=1):
        u = user_map.get(row.kook_id)
        items.append({
            'rank': rank,
            'kook_id': row.kook_id,
            'user': u,
            'display_name': _display_for(u) or row.kook_username or row.kook_id,
            'total_seconds': int(row.total_seconds or 0),
            'sessions': int(row.sessions or 0),
            'last_left_at': row.last_left_at,
        })
    return day, items


def list_window_leaderboard(days=7, limit=20):
    """近 N 天总挂机时长排行(基于 BJ 日)。"""
    today = bj_today()
    start = today - timedelta(days=days - 1)
    q = (
        db.session.query(
            VoiceDailyStat.kook_id.label('kook_id'),
            func.sum(VoiceDailyStat.total_seconds).label('total_seconds'),
            func.sum(VoiceDailyStat.sessions_count).label('sessions'),
            func.count(func.distinct(VoiceDailyStat.stat_date)).label('active_days'),
            func.max(VoiceDailyStat.user_id).label('user_id'),
            func.max(VoiceDailyStat.kook_username).label('kook_username'),
            func.max(VoiceDailyStat.last_left_at).label('last_left_at'),
        )
        .filter(VoiceDailyStat.stat_date >= start, VoiceDailyStat.stat_date <= today)
        .group_by(VoiceDailyStat.kook_id)
        .order_by(func.sum(VoiceDailyStat.total_seconds).desc())
        .limit(limit)
    )
    rows = q.all()
    user_map = _user_map_for(rows)
    items = []
    for rank, row in enumerate(rows, start=1):
        u = user_map.get(row.kook_id)
        items.append({
            'rank': rank,
            'kook_id': row.kook_id,
            'user': u,
            'display_name': _display_for(u) or row.kook_username or row.kook_id,
            'total_seconds': int(row.total_seconds or 0),
            'sessions': int(row.sessions or 0),
            'active_days': int(row.active_days or 0),
            'last_left_at': row.last_left_at,
        })
    return start, today, items


def list_channel_distribution(days=7, limit=20):
    today = bj_today()
    start = today - timedelta(days=days - 1)
    rows = (
        db.session.query(
            VoiceDailyStat.channel_id.label('channel_id'),
            func.sum(VoiceDailyStat.total_seconds).label('total_seconds'),
            func.sum(VoiceDailyStat.sessions_count).label('sessions'),
            func.count(func.distinct(VoiceDailyStat.kook_id)).label('uniques'),
        )
        .filter(VoiceDailyStat.stat_date >= start, VoiceDailyStat.stat_date <= today)
        .group_by(VoiceDailyStat.channel_id)
        .order_by(func.sum(VoiceDailyStat.total_seconds).desc())
        .limit(limit)
    ).all()

    # 用最近一次 session 上的 channel_name 作为展示名
    channel_ids = [r.channel_id for r in rows]
    name_map = {}
    if channel_ids:
        name_rows = (
            db.session.query(VoiceSession.channel_id, VoiceSession.channel_name)
            .filter(VoiceSession.channel_id.in_(channel_ids))
            .filter(VoiceSession.channel_name.isnot(None))
            .order_by(VoiceSession.id.desc())
        ).all()
        for cid, cname in name_rows:
            if cid in name_map:
                continue
            name_map[cid] = cname

    items = []
    for rank, row in enumerate(rows, start=1):
        items.append({
            'rank': rank,
            'channel_id': row.channel_id,
            'channel_name': name_map.get(row.channel_id) or row.channel_id,
            'total_seconds': int(row.total_seconds or 0),
            'sessions': int(row.sessions or 0),
            'uniques': int(row.uniques or 0),
        })
    return start, today, items


def list_recent_sessions(limit=50, channel_id=None, kook_id=None, status=None):
    q = VoiceSession.query
    if channel_id:
        q = q.filter(VoiceSession.channel_id == str(channel_id).strip())
    if kook_id:
        q = q.filter(VoiceSession.kook_id == str(kook_id).strip())
    if status:
        q = q.filter(VoiceSession.status == status)
    rows = q.order_by(VoiceSession.id.desc()).limit(limit).all()
    items = []
    for s in rows:
        items.append({
            'id': s.id,
            'kook_id': s.kook_id,
            'user': s.user,
            'display_name': s.display_name,
            'channel_id': s.channel_id,
            'channel_name': s.channel_name or s.channel_id,
            'joined_at': s.joined_at,
            'left_at': s.left_at,
            'duration_seconds': int(s.duration_seconds or 0) if s.left_at else None,
            'status': s.status,
            'note': s.note or '',
        })
    return items


def stats_overview(window_days=7):
    """KPI 概况"""
    today = bj_today()
    start = today - timedelta(days=window_days - 1)

    today_total_seconds = int(
        db.session.query(func.coalesce(func.sum(VoiceDailyStat.total_seconds), 0))
        .filter(VoiceDailyStat.stat_date == today).scalar() or 0
    )
    today_unique = int(
        db.session.query(func.count(func.distinct(VoiceDailyStat.kook_id)))
        .filter(VoiceDailyStat.stat_date == today).scalar() or 0
    )
    today_sessions = int(
        db.session.query(func.coalesce(func.sum(VoiceDailyStat.sessions_count), 0))
        .filter(VoiceDailyStat.stat_date == today).scalar() or 0
    )
    window_total_seconds = int(
        db.session.query(func.coalesce(func.sum(VoiceDailyStat.total_seconds), 0))
        .filter(VoiceDailyStat.stat_date >= start, VoiceDailyStat.stat_date <= today).scalar() or 0
    )
    window_unique = int(
        db.session.query(func.count(func.distinct(VoiceDailyStat.kook_id)))
        .filter(VoiceDailyStat.stat_date >= start, VoiceDailyStat.stat_date <= today).scalar() or 0
    )
    active_now = int(VoiceSession.query.filter_by(status='active').count())

    return {
        'today': today,
        'window_start': start,
        'window_days': window_days,
        'today_total_seconds': today_total_seconds,
        'today_sessions': today_sessions,
        'today_unique': today_unique,
        'window_total_seconds': window_total_seconds,
        'window_unique': window_unique,
        'active_now': active_now,
    }


# ============================ 显示工具 ============================

def format_duration(seconds):
    s = int(max(0, seconds or 0))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f'{h}小时{m:02d}分'
    if m:
        return f'{m}分{sec:02d}秒'
    return f'{sec}秒'


# ============================ 内部工具 ============================

def _user_map_for(rows):
    kids = {str(r.kook_id) for r in rows if r.kook_id}
    if not kids:
        return {}
    users = User.query.filter(User.kook_id.in_(kids)).all()
    return {u.kook_id: u for u in users}


def _display_for(user):
    if not user:
        return ''
    return user.player_nickname or user.kook_username or user.nickname or user.username or ''
