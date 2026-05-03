import hashlib
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import desc, func

try:
    import pytz
except ImportError:
    pytz = None

from app.extensions import db
from app.models.chat_stats import (
    DEFAULT_MILESTONE_REWARDS,
    ChatBotProfile,
    ChatCheckinRecord,
    ChatDailyContentStat,
    ChatDailyUserStat,
    ChatRankSettlement,
    ChatStatConfig,
)
from app.models.user import User


BJ_TZ = pytz.timezone('Asia/Shanghai') if pytz else timezone(timedelta(hours=8), name='Asia/Shanghai')
UTC = pytz.utc if pytz else timezone.utc


def bj_today():
    return datetime.now(BJ_TZ).date()


def to_bj_date(value=None):
    if value is None:
        return bj_today()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(BJ_TZ).date()
    if isinstance(value, str):
        return datetime.strptime(value[:10], '%Y-%m-%d').date()
    return bj_today()


def parse_id_lines(raw_value):
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


def get_config(create=True):
    cfg = ChatStatConfig.query.order_by(ChatStatConfig.id.asc()).first()
    if cfg or not create:
        return cfg
    cfg = ChatStatConfig(
        enabled=True,
        duplicate_limit=2,
        rank_limit=10,
        daily_title='话痨',
        weekly_title='本周话痨',
        rank_broadcast_enabled=True,
        checkin_broadcast_enabled=True,
    )
    cfg.channel_id_list = []
    cfg.whitelist_kook_id_list = []
    cfg.set_milestone_rewards(DEFAULT_MILESTONE_REWARDS)
    db.session.add(cfg)
    db.session.flush()
    return cfg


def update_config_from_form(form):
    cfg = get_config(create=True)
    cfg.enabled = form.get('enabled') == 'on'
    cfg.channel_id_list = parse_id_lines(form.get('channel_ids', ''))
    cfg.whitelist_kook_id_list = parse_id_lines(form.get('whitelist_kook_ids', ''))
    cfg.daily_broadcast_channel_id = (form.get('daily_broadcast_channel_id') or '').strip() or None
    cfg.weekly_broadcast_channel_id = (form.get('weekly_broadcast_channel_id') or '').strip() or None
    cfg.checkin_broadcast_channel_id = (form.get('checkin_broadcast_channel_id') or '').strip() or None
    cfg.rank_broadcast_enabled = form.get('rank_broadcast_enabled') == 'on'
    cfg.checkin_broadcast_enabled = form.get('checkin_broadcast_enabled') == 'on'
    cfg.daily_title = (form.get('daily_title') or '话痨').strip() or '话痨'
    cfg.weekly_title = (form.get('weekly_title') or '本周话痨').strip() or '本周话痨'
    cfg.duplicate_limit = _bounded_int(form.get('duplicate_limit'), 2, 0, 20)
    cfg.rank_limit = _bounded_int(form.get('rank_limit'), 10, 1, 50)

    rewards = {}
    for day in (10, 30, 60, 100):
        rewards[day] = {
            'title': (form.get(f'milestone_{day}_title') or '').strip(),
            'badge': (form.get(f'milestone_{day}_badge') or '').strip(),
        }
    cfg.set_milestone_rewards(rewards)
    return cfg


def _bounded_int(raw_value, default, min_value, max_value):
    try:
        value = int(str(raw_value).strip())
    except Exception:
        value = default
    return max(min_value, min(max_value, value))


def resolve_bound_user(kook_id, user_id=None):
    if user_id:
        user = db.session.get(User, int(user_id))
        if user:
            return user
    if not kook_id:
        return None
    return (
        User.query
        .filter_by(kook_id=str(kook_id))
        .order_by(User.kook_bound.desc(), User.id.asc())
        .first()
    )


def is_internal_user(user):
    if not user:
        return False
    return bool(user.is_admin or user.has_role('staff') or user.role in ('staff', 'admin', 'superadmin'))


def is_whitelisted(kook_id, user=None, cfg=None):
    cfg = cfg or get_config(create=True)
    if str(kook_id or '').strip() in set(cfg.whitelist_kook_id_list):
        return True
    return is_internal_user(user)


def display_name_for(user=None, kook_username=None, kook_id=None):
    if user:
        for candidate in (user.player_nickname, user.kook_username, user.nickname, user.username):
            if candidate:
                return candidate
    return kook_username or str(kook_id or '')


def get_or_create_profile(kook_id, user=None, kook_username=None):
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return None
    profile = ChatBotProfile.query.filter_by(kook_id=kook_id).first()
    name = display_name_for(user, kook_username, kook_id)
    if profile:
        changed = False
        if user and profile.user_id != user.id:
            profile.user_id = user.id
            changed = True
        if name and profile.display_name != name:
            profile.display_name = name
            changed = True
        if changed:
            db.session.flush()
        return profile
    profile = ChatBotProfile(
        kook_id=kook_id,
        user_id=user.id if user else None,
        display_name=name,
    )
    db.session.add(profile)
    db.session.flush()
    return profile


def normalize_message_content(content):
    text = str(content or '').strip()
    text = re.sub(r'\(met\)\d+\(met\)', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()


def is_meaningless_content(normalized_content):
    text = re.sub(r'\s+', '', str(normalized_content or ''))
    if not text:
        return True
    if len(text) >= 4 and re.fullmatch(r'(.)\1+', text, flags=re.DOTALL):
        return True
    if len(text) >= 6 and re.fullmatch(r'[\W_]+', text, flags=re.DOTALL):
        return True
    return False


def _content_hash(normalized_content):
    return hashlib.sha256(str(normalized_content or '').encode('utf-8')).hexdigest()


def record_message(channel_id, kook_id, kook_username=None, content='', user_id=None, occurred_at=None):
    """记录 KOOK 普通发言，返回记录结果字典。"""
    cfg = get_config(create=True)
    channel_id = str(channel_id or '').strip()
    kook_id = str(kook_id or '').strip()
    if not cfg.enabled:
        return {'status': 'ignored', 'reason': 'disabled'}
    if not channel_id or channel_id not in set(cfg.channel_id_list):
        return {'status': 'ignored', 'reason': 'channel'}
    if not kook_id:
        return {'status': 'ignored', 'reason': 'missing_kook_id'}

    user = resolve_bound_user(kook_id, user_id=user_id)
    if is_whitelisted(kook_id, user=user, cfg=cfg):
        return {'status': 'ignored', 'reason': 'whitelist'}

    now = occurred_at if isinstance(occurred_at, datetime) else datetime.utcnow()
    stat_date = to_bj_date(now)
    get_or_create_profile(kook_id, user=user, kook_username=kook_username)

    stat = (
        ChatDailyUserStat.query
        .filter_by(stat_date=stat_date, channel_id=channel_id, kook_id=kook_id)
        .first()
    )
    if not stat:
        stat = ChatDailyUserStat(
            stat_date=stat_date,
            channel_id=channel_id,
            kook_id=kook_id,
            user_id=user.id if user else None,
            kook_username=kook_username or None,
        )
        db.session.add(stat)

    stat.total_count = int(stat.total_count or 0) + 1
    stat.last_message_at = now
    if user and stat.user_id != user.id:
        stat.user_id = user.id
    if kook_username and stat.kook_username != kook_username:
        stat.kook_username = kook_username
    normalized = normalize_message_content(content)
    if is_meaningless_content(normalized):
        stat.filtered_count = int(stat.filtered_count or 0) + 1
        stat.meaningless_filtered_count = int(stat.meaningless_filtered_count or 0) + 1
        db.session.commit()
        return {'status': 'filtered', 'reason': 'meaningless', 'stat_date': stat_date}

    h = _content_hash(normalized)
    content_stat = (
        ChatDailyContentStat.query
        .filter_by(stat_date=stat_date, channel_id=channel_id, kook_id=kook_id, content_hash=h)
        .first()
    )
    if not content_stat:
        content_stat = ChatDailyContentStat(
            stat_date=stat_date,
            channel_id=channel_id,
            kook_id=kook_id,
            content_hash=h,
            content_sample=normalized[:200],
            count=0,
        )
        db.session.add(content_stat)
    content_stat.count = int(content_stat.count or 0) + 1

    if int(content_stat.count or 0) > int(cfg.duplicate_limit or 2):
        stat.filtered_count = int(stat.filtered_count or 0) + 1
        stat.duplicate_filtered_count = int(stat.duplicate_filtered_count or 0) + 1
        db.session.commit()
        return {'status': 'filtered', 'reason': 'duplicate', 'stat_date': stat_date}

    stat.valid_count = int(stat.valid_count or 0) + 1
    db.session.commit()
    return {'status': 'counted', 'stat_date': stat_date, 'valid_count': stat.valid_count}


def get_daily_ranking(stat_date=None, limit=None):
    target_date = to_bj_date(stat_date)
    cfg = get_config(create=True)
    limit = limit or int(cfg.rank_limit or 10)
    return _ranking_between(target_date, target_date, limit)


def week_range(anchor_date=None):
    anchor = to_bj_date(anchor_date)
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def get_weekly_ranking(anchor_date=None, limit=None):
    start, end = week_range(anchor_date)
    cfg = get_config(create=True)
    limit = limit or int(cfg.rank_limit or 10)
    return _ranking_between(start, end, limit)


def _ranking_between(start_date, end_date, limit):
    count_expr = func.sum(ChatDailyUserStat.valid_count).label('valid_count')
    rows = (
        db.session.query(
            ChatDailyUserStat.kook_id.label('kook_id'),
            func.max(ChatDailyUserStat.user_id).label('user_id'),
            func.max(ChatDailyUserStat.kook_username).label('kook_username'),
            count_expr,
        )
        .filter(ChatDailyUserStat.stat_date >= start_date)
        .filter(ChatDailyUserStat.stat_date <= end_date)
        .group_by(ChatDailyUserStat.kook_id)
        .having(count_expr > 0)
        .order_by(desc(count_expr), ChatDailyUserStat.kook_id.asc())
        .limit(int(limit or 10))
        .all()
    )

    user_ids = [int(row.user_id) for row in rows if row.user_id]
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    profiles = {
        p.kook_id: p for p in ChatBotProfile.query.filter(
            ChatBotProfile.kook_id.in_([row.kook_id for row in rows])
        ).all()
    } if rows else {}

    ranking = []
    for idx, row in enumerate(rows, start=1):
        user = users.get(int(row.user_id)) if row.user_id else None
        profile = profiles.get(str(row.kook_id))
        name = display_name_for(user, row.kook_username, row.kook_id)
        if profile and profile.display_name and not user:
            name = profile.display_name
        ranking.append({
            'rank_no': idx,
            'kook_id': str(row.kook_id),
            'user_id': int(row.user_id) if row.user_id else None,
            'kook_username': row.kook_username,
            'display_name': name,
            'valid_count': int(row.valid_count or 0),
            'title': profile.title if profile else '',
            'badge': profile.badge if profile else '',
        })
    return ranking


def settle_daily(target_date=None, force=False):
    day = to_bj_date(target_date or (bj_today() - timedelta(days=1)))
    return settle_rankings('daily', day, day, force=force)


def settle_weekly(anchor_date=None, force=False):
    anchor = to_bj_date(anchor_date or (bj_today() - timedelta(days=1)))
    start, end = week_range(anchor)
    return settle_rankings('weekly', start, end, force=force)


def settle_rankings(period_type, period_start, period_end, force=False):
    cfg = get_config(create=True)
    period_type = 'weekly' if period_type == 'weekly' else 'daily'
    period_start = to_bj_date(period_start)
    period_end = to_bj_date(period_end)

    existing = ChatRankSettlement.query.filter_by(
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
    ).order_by(ChatRankSettlement.rank_no.asc()).all()
    if existing and not force:
        return 0, existing
    if existing and force:
        for row in existing:
            db.session.delete(row)
        db.session.flush()

    ranking = _ranking_between(period_start, period_end, int(cfg.rank_limit or 10))
    title_base = cfg.weekly_title if period_type == 'weekly' else cfg.daily_title
    period_label = '每周' if period_type == 'weekly' else '每日'
    rows = []
    for item in ranking:
        title = f'{title_base}王' if item['rank_no'] == 1 and not str(title_base).endswith('王') else title_base
        badge = f'{period_label}发言TOP{item["rank_no"]}'
        row = ChatRankSettlement(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            rank_no=item['rank_no'],
            kook_id=item['kook_id'],
            user_id=item['user_id'],
            kook_username=item['kook_username'],
            valid_count=item['valid_count'],
            title=title,
            badge=badge,
        )
        db.session.add(row)
        rows.append(row)
        profile = get_or_create_profile(item['kook_id'], user=resolve_bound_user(item['kook_id'], item['user_id']), kook_username=item['kook_username'])
        if profile:
            profile.title = title
            profile.badge = badge

    db.session.commit()

    if rows and cfg.rank_broadcast_enabled:
        channel_id = cfg.weekly_broadcast_channel_id if period_type == 'weekly' else cfg.daily_broadcast_channel_id
        if channel_id:
            _broadcast_rankings(channel_id, period_type, period_start, period_end, rows)
    return len(rows), rows


def _broadcast_rankings(channel_id, period_type, start_date, end_date, rows):
    try:
        from app.services.kook_service import _send_channel_msg
        title = '本周发言排行榜' if period_type == 'weekly' else '昨日发言排行榜'
        date_text = f'{start_date:%Y-%m-%d} ~ {end_date:%Y-%m-%d}' if start_date != end_date else f'{start_date:%Y-%m-%d}'
        lines = [f'**{title}**', f'统计周期: `{date_text}`', '---']
        for row in rows:
            mention = f'(met){row.kook_id}(met)' if row.kook_id else (row.kook_username or '-')
            reward = row.title or row.badge or '上榜'
            lines.append(f'`#{row.rank_no}` {mention}  **{row.valid_count}** 条  ·  {reward}')
        _send_channel_msg(channel_id, '\n'.join(lines))
    except Exception:
        return False
    return True


def perform_checkin(channel_id, kook_id, kook_username=None, user_id=None, occurred_at=None):
    cfg = get_config(create=True)
    if not cfg.enabled:
        return {'ok': False, 'message': '签到功能暂未开启。'}

    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return {'ok': False, 'message': '未获取到你的 KOOK 身份，请稍后重试。'}

    checkin_date = to_bj_date(occurred_at)
    existing = ChatCheckinRecord.query.filter_by(checkin_date=checkin_date, kook_id=kook_id).first()
    if existing:
        return {
            'ok': False,
            'message': f'今天已经打过卡啦，当前连续打卡 **{existing.streak_after}** 天。',
            'record': existing,
        }

    user = resolve_bound_user(kook_id, user_id=user_id)
    profile = get_or_create_profile(kook_id, user=user, kook_username=kook_username)
    yesterday = checkin_date - timedelta(days=1)
    if profile and profile.last_checkin_date == yesterday:
        streak = int(profile.sign_in_streak or 0) + 1
    else:
        streak = 1
    total = int(profile.total_checkins or 0) + 1 if profile else 1

    reward = cfg.get_milestone_rewards().get(streak) or {}
    reward_title = str(reward.get('title') or '').strip()
    reward_badge = str(reward.get('badge') or '').strip()

    if profile:
        profile.sign_in_streak = streak
        profile.total_checkins = total
        profile.last_checkin_date = checkin_date
        if reward_title:
            profile.title = reward_title
        if reward_badge:
            profile.badge = reward_badge

    record = ChatCheckinRecord(
        checkin_date=checkin_date,
        kook_id=kook_id,
        user_id=user.id if user else None,
        kook_username=kook_username or None,
        channel_id=str(channel_id or '') or None,
        streak_after=streak,
        total_after=total,
        reward_title=reward_title or None,
        reward_badge=reward_badge or None,
    )
    db.session.add(record)
    db.session.commit()

    name = display_name_for(user, kook_username, kook_id)
    message = f'**{name}** 打卡成功！连续打卡 **{streak}** 天，累计打卡 **{total}** 天。'
    if reward_title or reward_badge:
        message += f'\n达成里程碑奖励：**{reward_title or reward_badge}**'
    if cfg.checkin_broadcast_enabled and cfg.checkin_broadcast_channel_id and cfg.checkin_broadcast_channel_id != str(channel_id or ''):
        _broadcast_checkin(cfg.checkin_broadcast_channel_id, kook_id, name, streak, total, reward_title, reward_badge)

    return {'ok': True, 'message': message, 'record': record, 'reward_title': reward_title, 'reward_badge': reward_badge}


def _broadcast_checkin(channel_id, kook_id, name, streak, total, reward_title='', reward_badge=''):
    try:
        from app.services.kook_service import _send_channel_msg
        mention = f'(met){kook_id}(met)' if kook_id else name
        text = f'{mention} 今日打卡成功，连续 **{streak}** 天，累计 **{total}** 天。'
        if reward_title or reward_badge:
            text += f'\n里程碑奖励：**{reward_title or reward_badge}**'
        _send_channel_msg(channel_id, text)
    except Exception:
        return False
    return True


def get_recent_checkins(limit=50):
    return (
        ChatCheckinRecord.query
        .order_by(ChatCheckinRecord.created_at.desc())
        .limit(limit)
        .all()
    )


def get_latest_settlements(period_type, limit=10):
    return (
        ChatRankSettlement.query
        .filter_by(period_type=period_type)
        .order_by(ChatRankSettlement.period_end.desc(), ChatRankSettlement.rank_no.asc())
        .limit(limit)
        .all()
    )


def get_daily_totals(stat_date=None):
    target_date = to_bj_date(stat_date)
    row = (
        db.session.query(
            func.coalesce(func.sum(ChatDailyUserStat.total_count), 0),
            func.coalesce(func.sum(ChatDailyUserStat.valid_count), 0),
            func.coalesce(func.sum(ChatDailyUserStat.filtered_count), 0),
        )
        .filter(ChatDailyUserStat.stat_date == target_date)
        .first()
    )
    return {
        'total_count': int(row[0] or 0),
        'valid_count': int(row[1] or 0),
        'filtered_count': int(row[2] or 0),
    }
