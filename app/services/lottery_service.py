"""
KOOK 抽奖服务
"""
import logging
import random
import threading
from datetime import datetime, timedelta
import json
import re

import requests
from flask import current_app

from app.extensions import db
from app.models.lottery import Lottery, LotteryParticipant, LotteryWinner
from app.models.user import User

logger = logging.getLogger(__name__)

KOOK_API_BASE = 'https://www.kookapp.cn/api/v3'
_draw_locks = {}
_draw_locks_guard = threading.Lock()
_lottery_count_cache = {}
_lottery_count_guard = threading.Lock()


def _get_token():
    return current_app.config.get('KOOK_TOKEN', '')


def _headers():
    return {
        'Authorization': f'Bot {_get_token()}',
        'Content-Type': 'application/json',
    }


def _token_ok():
    t = _get_token()
    return t and t != 'your-kook-bot-token'


def _get_draw_lock(lottery_id):
    """获取单个抽奖的进程内互斥锁，避免并发重复开奖"""
    with _draw_locks_guard:
        lock = _draw_locks.get(lottery_id)
        if lock is None:
            lock = threading.Lock()
            _draw_locks[lottery_id] = lock
        return lock


def _get_cached_participant_count(msg_id):
    with _lottery_count_guard:
        return _lottery_count_cache.get(str(msg_id))


def _set_cached_participant_count(msg_id, count):
    with _lottery_count_guard:
        _lottery_count_cache[str(msg_id)] = int(count)


# ─── KOOK API 调用 ──────────────────────────────────────────

def _send_channel_msg_with_id(channel_id, card_json):
    """向频道发送卡片消息并返回 msg_id"""
    if not _token_ok():
        logger.warning('[Lottery] Token 未配置，跳过发送')
        return None
    try:
        resp = requests.post(
            f'{KOOK_API_BASE}/message/create',
            headers=_headers(),
            json={'target_id': str(channel_id), 'content': card_json, 'type': 10},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[Lottery] 发送频道消息失败: {data}')
            return None
        return data.get('data', {}).get('msg_id')
    except Exception as e:
        logger.error(f'[Lottery] 发送频道消息异常: {e}')
        return None


def _add_reaction(msg_id, emoji):
    """给消息添加 emoji 反应"""
    if not _token_ok():
        return False
    try:
        resp = requests.post(
            f'{KOOK_API_BASE}/message/add-reaction',
            headers=_headers(),
            json={'msg_id': str(msg_id), 'emoji': emoji},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[Lottery] 添加反应失败: {data}')
            return False
        return True
    except Exception as e:
        logger.error(f'[Lottery] 添加反应异常: {e}')
        return False


def _get_message_reaction_emojis(msg_id):
    """获取消息上所有反应的 emoji ID 列表"""
    if not _token_ok():
        return []
    try:
        resp = requests.get(
            f'{KOOK_API_BASE}/message/view',
            headers=_headers(),
            params={'msg_id': str(msg_id)},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[Lottery] 获取消息详情失败: {data}')
            return []
        reactions = data.get('data', {}).get('reactions', [])
        return [r['emoji']['id'] for r in reactions if r.get('emoji', {}).get('id')]
    except Exception as e:
        logger.error(f'[Lottery] 获取消息详情异常: {e}')
        return []


def _get_all_reaction_users(msg_id):
    """获取消息上所有 emoji 的反应用户 kook_id 列表（去重，任意表情均算参与）"""
    if not _token_ok():
        return []

    emojis = _get_message_reaction_emojis(msg_id)
    if not emojis:
        return []

    bot_id = _get_bot_id()
    all_users = set()

    for emoji_id in emojis:
        page = 1
        while page <= 200:
            try:
                resp = requests.get(
                    f'{KOOK_API_BASE}/message/reaction-list',
                    headers=_headers(),
                    params={'msg_id': str(msg_id), 'emoji': emoji_id, 'page': page, 'page_size': 50},
                    timeout=10,
                )
                data = resp.json()
                if data.get('code') != 0:
                    logger.error(f'[Lottery] 获取反应用户失败: {data}')
                    break

                raw_data = data.get('data', [])
                meta = data.get('meta', {}) or {}
                if isinstance(raw_data, dict):
                    users = raw_data.get('items') or raw_data.get('list') or raw_data.get('users') or []
                    meta = raw_data.get('meta', {}) or meta
                elif isinstance(raw_data, list):
                    users = raw_data
                else:
                    users = []

                for u in users:
                    uid = str(u.get('id', ''))
                    if uid and uid != bot_id:
                        all_users.add(uid)

                page_total = meta.get('page_total') or meta.get('pageTotal')
                if page_total is not None:
                    try:
                        if page >= int(page_total):
                            break
                    except (TypeError, ValueError):
                        if len(users) < 50:
                            break
                else:
                    if len(users) < 50:
                        break

                page += 1
            except Exception as e:
                logger.error(f'[Lottery] 获取反应用户异常: {e}')
                break
        if page > 200:
            logger.warning(f'[Lottery] msg_id={msg_id} emoji={emoji_id} 反应用户分页超过 200 页，已中断')

    return list(all_users)


def _update_channel_msg(msg_id, card_json):
    """更新频道消息内容（卡片消息）"""
    if not _token_ok():
        return False
    try:
        resp = requests.post(
            f'{KOOK_API_BASE}/message/update',
            headers=_headers(),
            json={'msg_id': str(msg_id), 'content': card_json},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[Lottery] 更新消息失败: {data}')
            return False
        return True
    except Exception as e:
        logger.error(f'[Lottery] 更新消息异常: {e}')
        return False


def _get_bot_id():
    """获取 Bot 自身用户 ID（缓存到 app config）"""
    try:
        cached = current_app.config.get('_KOOK_BOT_USER_ID')
        if cached:
            return cached
        resp = requests.get(
            f'{KOOK_API_BASE}/user/me',
            headers=_headers(),
            timeout=10,
        )
        data = resp.json()
        if data.get('code') == 0:
            bot_id = str(data['data']['id'])
            current_app.config['_KOOK_BOT_USER_ID'] = bot_id
            return bot_id
    except Exception:
        pass
    return ''


def _send_direct_msg(user_kook_id, markdown_text):
    """向用户发送私信卡片消息（粉色边框）"""
    if not _token_ok():
        return False
    try:
        card_json = json.dumps([{
            "type": "card",
            "theme": "secondary",
            "color": "#EC4899",
            "size": "lg",
            "modules": [
                {"type": "section", "text": {"type": "kmarkdown", "content": str(markdown_text or '')}}
            ],
        }])
        resp = requests.post(
            f'{KOOK_API_BASE}/direct-message/create',
            headers=_headers(),
            json={'target_id': str(user_kook_id), 'content': card_json, 'type': 10},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[Lottery] 私信失败: {data}')
            return False
        return True
    except Exception as e:
        logger.error(f'[Lottery] 私信异常: {e}')
        return False


# ─── 模板工具 ────────────────────────────────────────────────

def _get_lottery_template(broadcast_type):
    """获取抽奖相关的自定义模板"""
    from app.services.kook_service import _get_custom_template, BROADCAST_TYPES
    custom = _get_custom_template(broadcast_type)
    if custom:
        return custom
    meta = BROADCAST_TYPES.get(broadcast_type, {})
    return meta.get('default_template', '')


def _parse_header_body(template):
    """解析模板标题与正文。支持 '# xxx' 与 '标题: xxx' 两种标题写法。"""
    if not template:
        return None, ''
    lines = template.split('\n', 1)
    first = str(lines[0] or '').strip()
    if first.startswith('#'):
        header = first.lstrip('#').strip()
        body = lines[1] if len(lines) > 1 else ''
        return header, body
    m = re.match(r'^(?:标题(?:（[^）]*）|\([^)]*\))?|title)\s*[:：]\s*(.*)$', first, re.IGNORECASE)
    if m:
        header = m.group(1).strip()
        body = lines[1] if len(lines) > 1 else ''
        return header, body
    return None, template


def _render_tpl(template, variables):
    """渲染模板变量 {var}"""
    result = template
    for key, value in variables.items():
        result = result.replace('{' + key + '}', str(value))
    return result


def _clean_header_text(header):
    """去掉模板里误填的“标题”前缀，仅保留真正标题内容。"""
    text = str(header or '').strip()
    if not text:
        return ''
    text = re.sub(
        r'^(?:标题(?:（[^）]*）|\([^)]*\))?|title)\s*[:：\-—]*\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


# ─── 卡片构建 ────────────────────────────────────────────────

def build_lottery_card(lottery, participant_count=0):
    """构建抽奖公告卡片（粉色边框）"""
    from app.services.kook_service import BROADCAST_TYPES

    draw_ts = int(lottery.draw_time.timestamp() * 1000)

    # 准备变量
    eligible = lottery.get_eligible_roles()
    role_map = {'god': '老板', 'player': '陪玩', 'staff': '客服'}
    roles_text = '、'.join(role_map.get(r, r) for r in eligible) if eligible else '所有人'
    vip_text = f'最低 VIP: **{lottery.min_vip_level}**\n' if lottery.min_vip_level else ''
    desc_text = f'\n{lottery.description}\n' if lottery.description else ''

    variables = {
        'title': lottery.title,
        'prize': lottery.prize,
        'winner_count': str(lottery.winner_count),
        'roles': roles_text,
        'vip': vip_text,
        'description': desc_text,
        'count': str(participant_count),
    }

    # 获取模板（自定义 > 默认）
    template = _get_lottery_template('lottery_announce')
    header, body = _parse_header_body(template)

    default_meta = BROADCAST_TYPES.get('lottery_announce', {})
    _, default_body = _parse_header_body(default_meta.get('default_template', ''))
    body_tpl = body if str(body or '').strip() else default_body
    content = _render_tpl(body_tpl, variables)
    raw_desc = (lottery.description or '').strip()
    if raw_desc and raw_desc not in content:
        content = f'{content.rstrip()}\n\n活动简介:\n{raw_desc}'

    card_header = _clean_header_text(header) or _clean_header_text(default_meta.get('title', '')) or '抽奖活动'

    card = [{
        "type": "card",
        "theme": "secondary",
        "color": "#EC4899",
        "size": "lg",
        "modules": [
            {"type": "header", "text": {"type": "plain-text", "content": card_header}},
            {"type": "section", "text": {"type": "kmarkdown", "content": content}},
            {"type": "divider"},
            {"type": "countdown", "mode": "day", "endTime": draw_ts},
        ],
    }]
    return json.dumps(card)


def build_result_card(lottery, winners):
    """构建开奖结果卡片（粉色边框）"""
    from app.services.kook_service import BROADCAST_TYPES

    # 构建中奖者文本
    if winners:
        winner_lines = []
        for w in winners:
            if w.user:
                mention = f'(met){w.kook_id}(met)' if w.kook_id else (w.user.nickname or w.user.username or '未知用户')
                winner_lines.append(f'  {mention}')
            else:
                mention = f'(met){w.kook_id}(met)' if w.kook_id else '未知用户'
                winner_lines.append(f'  {mention}')
        winner_text = '\n'.join(winner_lines)
    else:
        winner_text = '  无人中奖'

    variables = {
        'title': lottery.title,
        'prize': lottery.prize,
        'winners': winner_text,
    }

    template = _get_lottery_template('lottery_result')
    header, body = _parse_header_body(template)
    default_meta = BROADCAST_TYPES.get('lottery_result', {})
    _, default_body = _parse_header_body(default_meta.get('default_template', ''))
    body_tpl = body if str(body or '').strip() else default_body
    content = _render_tpl(body_tpl, variables)

    card_header = _clean_header_text(header) or '开奖结果'

    card = [{
        "type": "card",
        "theme": "secondary",
        "color": "#EC4899",
        "size": "lg",
        "modules": [
            {"type": "header", "text": {"type": "plain-text", "content": card_header}},
            {"type": "section", "text": {"type": "kmarkdown", "content": content}},
        ],
    }]
    return json.dumps(card)


# ─── 业务逻辑 ────────────────────────────────────────────────

def create_interactive_lottery(channel_id, created_by, winner_count):
    """创建并直接发布一个互动抽奖。"""
    now = datetime.now()
    lottery = Lottery(
        title=f'互动抽奖 {now.strftime("%m-%d %H:%M:%S")}',
        description='由 KOOK 指令 /发布抽奖 发起；参与方式：在开奖前于当前频道发送普通消息即可参与。',
        prize='互动抽奖奖品',
        winner_count=winner_count,
        channel_id=str(channel_id),
        emoji='',
        draw_time=now + timedelta(minutes=30),
        created_by=created_by,
        lottery_mode='interactive',
        status='published',
    )
    db.session.add(lottery)
    db.session.commit()
    return lottery


def get_active_interactive_lotteries(channel_id, include_expired=False):
    query = Lottery.query.filter(
        Lottery.lottery_mode == 'interactive',
        Lottery.status == 'published',
        Lottery.channel_id == str(channel_id),
    )
    if not include_expired:
        query = query.filter(Lottery.draw_time > datetime.now())
    return query.order_by(Lottery.created_at.asc()).all()


def record_interactive_participation(channel_id, kook_id, kook_username=None, user_id=None):
    """将一条频道消息记入该频道全部进行中的互动抽奖。"""
    lotteries = get_active_interactive_lotteries(channel_id, include_expired=False)
    if not lotteries:
        return 0

    lottery_ids = [lottery.id for lottery in lotteries]
    existing_rows = (
        LotteryParticipant.query
        .filter(
            LotteryParticipant.lottery_id.in_(lottery_ids),
            LotteryParticipant.kook_id == str(kook_id),
        )
        .all()
    )
    existing_by_lottery = {row.lottery_id: row for row in existing_rows}

    now = datetime.utcnow()
    changed = False
    for lottery in lotteries:
        row = existing_by_lottery.get(lottery.id)
        if row:
            row.last_message_at = now
            if user_id and row.user_id != user_id:
                row.user_id = user_id
            if kook_username and row.kook_username != kook_username:
                row.kook_username = kook_username
            changed = True
            continue

        db.session.add(LotteryParticipant(
            lottery_id=lottery.id,
            user_id=user_id,
            kook_id=str(kook_id),
            kook_username=kook_username or None,
            joined_at=now,
            last_message_at=now,
        ))
        changed = True

    if changed:
        db.session.commit()
    return len(lotteries)


def _resolve_eligible_kook_ids(lottery, candidate_kook_ids):
    candidate_kook_ids = [str(kid) for kid in candidate_kook_ids if kid]
    if not candidate_kook_ids:
        return [], {}

    # 匹配系统用户
    kook_to_user = {}
    users = User.query.filter(User.kook_id.in_(candidate_kook_ids)).all()
    for u in users:
        kook_to_user[str(u.kook_id)] = u

    # 过滤资格
    eligible_roles = lottery.get_eligible_roles()
    min_vip = lottery.min_vip_level
    VipLevel = None
    min_level = None
    if min_vip:
        from app.models.vip import VipLevel as _VipLevel
        VipLevel = _VipLevel
        min_level = VipLevel.query.filter_by(name=min_vip).first()
        if not min_level:
            logger.warning(f'[Lottery] #{lottery.id} 最低VIP配置无效: {min_vip}')
            return None, {}

    def is_eligible(kook_id):
        user = kook_to_user.get(kook_id)
        if not user:
            if eligible_roles or min_vip:
                return False
            return True
        if eligible_roles and not any(user.has_role(role_key) for role_key in eligible_roles):
            return False
        if min_level:
            if not user.vip_level:
                return False
            user_level = VipLevel.query.filter_by(name=user.vip_level).first()
            if not user_level or user_level.sort_order < min_level.sort_order:
                return False
        return True

    eligible_kook_ids = [kid for kid in candidate_kook_ids if is_eligible(kid)]
    return eligible_kook_ids, kook_to_user

def publish_lottery(lottery):
    """发布抽奖到 KOOK 频道"""
    if lottery.is_interactive:
        return False, '互动抽奖由机器人指令直接发起，无需后台发布'
    if lottery.status != 'pending':
        return False, '只有待发布状态的抽奖可以发布'

    card_json = build_lottery_card(lottery)
    msg_id = _send_channel_msg_with_id(lottery.channel_id, card_json)
    if not msg_id:
        return False, '发送 KOOK 消息失败，请检查 Token 和频道 ID'

    lottery.kook_msg_id = msg_id
    lottery.status = 'published'
    db.session.commit()
    _set_cached_participant_count(msg_id, 0)

    # Bot 添加 emoji 引导用户参与
    _add_reaction(msg_id, lottery.emoji)

    return True, '抽奖已发布到 KOOK 频道'


def draw_lottery(lottery):
    """执行开奖"""
    lottery_id = lottery.id
    draw_lock = _get_draw_lock(lottery_id)
    if not draw_lock.acquire(blocking=False):
        return False, '该抽奖正在开奖，请稍后重试'

    try:
        # 数据库行锁（支持的数据库上生效）+ 进程内锁，双重避免重复开奖
        lottery = Lottery.query.filter_by(id=lottery_id).with_for_update().first()
        if not lottery:
            return False, '抽奖不存在'
        if lottery.status != 'published':
            return False, '只有已发布状态的抽奖可以开奖'
        if lottery.is_interactive:
            participant_kook_ids = [
                row.kook_id
                for row in LotteryParticipant.query.filter_by(lottery_id=lottery.id).all()
            ]
            logger.info(f'[Lottery] #{lottery.id} 互动参与用户数: {len(participant_kook_ids)}')
        else:
            if not lottery.kook_msg_id:
                return False, '缺少 KOOK 消息 ID'
            participant_kook_ids = _get_all_reaction_users(lottery.kook_msg_id)
            logger.info(f'[Lottery] #{lottery.id} 反应用户数: {len(participant_kook_ids)}')

        eligible_kook_ids, kook_to_user = _resolve_eligible_kook_ids(lottery, participant_kook_ids)
        if eligible_kook_ids is None:
            return False, f'抽奖配置错误：最低 VIP 等级 `{lottery.min_vip_level}` 不存在'
        logger.info(f'[Lottery] #{lottery.id} 合格用户数: {len(eligible_kook_ids)}')

        # 4. 内定用户优先
        rigged_ids = lottery.get_rigged_ids()  # user.id 列表
        rigged_kook_ids = []
        if rigged_ids:
            rigged_users = User.query.filter(User.id.in_(rigged_ids), User.kook_id.isnot(None)).all()
            for u in rigged_users:
                if u.kook_id in eligible_kook_ids:
                    rigged_kook_ids.append(u.kook_id)

        # 5. 抽取
        final_winners = []
        # 先加入内定（上限为 winner_count）
        for kid in rigged_kook_ids[:lottery.winner_count]:
            final_winners.append((kid, True))

        # 剩余名额从非内定的合格用户中随机抽取
        remaining = lottery.winner_count - len(final_winners)
        if remaining > 0:
            winner_kook_ids = {w[0] for w in final_winners}
            pool = [kid for kid in eligible_kook_ids if kid not in winner_kook_ids]
            sample_size = min(remaining, len(pool))
            if sample_size > 0:
                sampled = random.sample(pool, sample_size)
                for kid in sampled:
                    final_winners.append((kid, False))

        # 6. 保存中奖记录
        winner_records = []
        for kook_id, is_rigged in final_winners:
            user = kook_to_user.get(kook_id)
            w = LotteryWinner(
                lottery_id=lottery.id,
                user_id=user.id if user else None,
                kook_id=kook_id,
                is_rigged=is_rigged,
            )
            db.session.add(w)
            winner_records.append(w)

        lottery.status = 'drawn'
        db.session.commit()

        # 7. 发送结果卡片到频道
        result_card = build_result_card(lottery, winner_records)
        _send_channel_msg_with_id(lottery.channel_id, result_card)

        # 8. 私信通知中奖者
        _notify_winners(lottery, winner_records)

        return True, f'开奖完成，共 {len(winner_records)} 人中奖'
    except Exception as e:
        db.session.rollback()
        logger.error(f'[Lottery] #{lottery_id} 开奖异常: {e}')
        return False, '开奖失败，请稍后重试'
    finally:
        draw_lock.release()


def _notify_winners(lottery, winners):
    """私信通知每位中奖者"""
    from app.services.kook_service import BROADCAST_TYPES

    variables = {
        'title': lottery.title,
        'prize': lottery.prize,
    }

    template = _get_lottery_template('lottery_winner')
    header, body = _parse_header_body(template)
    content = _render_tpl(body, variables)

    default_meta = BROADCAST_TYPES.get('lottery_winner', {})
    card_header = header or default_meta.get('title', '🎉 中奖通知')
    msg_text = f"**{card_header}**\n{content}"

    for w in winners:
        ok = _send_direct_msg(w.kook_id, msg_text)
        if ok:
            w.notified = True
    db.session.commit()


def cancel_lottery(lottery):
    """取消抽奖"""
    if lottery.status not in ('pending', 'published'):
        return False, '当前状态无法取消'
    lottery.status = 'cancelled'
    db.session.commit()
    return True, '抽奖已取消'


def check_and_draw_due_lotteries():
    """定时任务：检查已到开奖时间的抽奖并自动开奖"""
    # draw_time 来自用户表单（本地时间），所以用 datetime.now() 对比
    now = datetime.now()
    due = Lottery.query.filter(
        Lottery.status == 'published',
        Lottery.draw_time <= now,
    ).all()

    count = 0
    for lottery in due:
        ok, msg = draw_lottery(lottery)
        if ok:
            count += 1
            logger.info(f'[Lottery] 自动开奖 #{lottery.id}: {msg}')
        else:
            logger.warning(f'[Lottery] 自动开奖 #{lottery.id} 失败: {msg}')
    return count


# ─── 参与人数更新 ─────────────────────────────────────────────

def update_lottery_participant_count(lottery):
    """更新单个抽奖卡片的参与人数"""
    if lottery.is_interactive or lottery.status != 'published' or not lottery.kook_msg_id:
        return
    users = _get_all_reaction_users(lottery.kook_msg_id)
    count = len(users)
    cached = _get_cached_participant_count(lottery.kook_msg_id)
    if cached is not None and cached == count:
        return
    _set_cached_participant_count(lottery.kook_msg_id, count)
    card_json = build_lottery_card(lottery, participant_count=count)
    _update_channel_msg(lottery.kook_msg_id, card_json)


def update_lottery_by_msg_id(msg_id):
    """根据 KOOK 消息 ID 更新抽奖卡片参与人数（供 Bot 事件调用）"""
    lottery = Lottery.query.filter_by(kook_msg_id=msg_id, status='published').first()
    if lottery:
        update_lottery_participant_count(lottery)


def update_all_published_lottery_counts():
    """定时任务：批量更新所有已发布抽奖的参与人数"""
    lotteries = Lottery.query.filter_by(status='published').all()
    for lottery in lotteries:
        try:
            update_lottery_participant_count(lottery)
        except Exception as e:
            logger.error(f'[Lottery] 更新 #{lottery.id} 参与人数异常: {e}')
