"""
KOOK REST API 推送服务
直接在 Flask 进程内通过 HTTP 调用 KOOK API 发送消息，无需额外进程。
"""
import json
import logging
import os
import re
import threading
from datetime import datetime
from urllib.parse import quote, urlparse

import requests
from flask import current_app

logger = logging.getLogger(__name__)

KOOK_API_BASE = 'https://www.kookapp.cn/api/v3'


def _get_token():
    return current_app.config.get('KOOK_TOKEN', '')


def _headers():
    return {
        'Authorization': f'Bot {_get_token()}',
        'Content-Type': 'application/json',
    }


def _safe_int(value, default=0):
    try:
        return int(str(value))
    except Exception:
        return default


def _permission_bits(permissions_value):
    """将 KOOK 角色 permissions 转为 bit 列表，便于前端展示。"""
    value = _safe_int(permissions_value, 0)
    bits = [bit for bit in range(0, 63) if value & (1 << bit)]
    return value, bits


def _extract_items(payload_data):
    """兼容 KOOK 接口 data 结构（list 或 {items: []}）。"""
    if isinstance(payload_data, list):
        return payload_data
    if isinstance(payload_data, dict):
        items = payload_data.get('items')
        if isinstance(items, list):
            return items
    return []


def _fetch_all_guilds():
    """获取 Bot 可见的服务器列表。"""
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return [], 'KOOK_TOKEN 未配置'

    page = 1
    guilds = []
    while True:
        try:
            resp = requests.get(
                f'{KOOK_API_BASE}/guild/list',
                headers=_headers(),
                params={'page': page, 'page_size': 50},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            logger.error('[KOOK] 获取服务器列表异常: %s', e)
            return [], str(e)

        if data.get('code') != 0:
            return [], data.get('message') or '获取服务器列表失败'

        payload = data.get('data') or {}
        items = _extract_items(payload)
        guilds.extend(items)

        meta = payload.get('meta') if isinstance(payload, dict) else {}
        page_total = _safe_int((meta or {}).get('page_total'), 1)
        if page >= page_total:
            break
        page += 1

    return guilds, None


def _get_channel_detail(channel_id):
    """读取频道详情，返回接口 data。"""
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return None, 'KOOK_TOKEN 未配置'
    try:
        resp = requests.get(
            f'{KOOK_API_BASE}/channel/view',
            headers=_headers(),
            params={'target_id': str(channel_id)},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            return None, data.get('message') or '获取频道信息失败'
        return data.get('data') or {}, None
    except Exception as e:
        logger.error('[KOOK] 获取频道详情异常: %s', e)
        return None, str(e)


def fetch_kook_role_catalog(guild_id=None, channel_id=None):
    """
    获取 KOOK 服务器角色列表（含 permissions 位信息）。
    返回 (result, error): result 为 dict，error 为 None 或错误字符串。
    """
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return None, 'KOOK_TOKEN 未配置'

    guilds, guild_err = _fetch_all_guilds()
    if guild_err:
        return None, guild_err

    guild_map = {str(g.get('id')): g for g in guilds if g.get('id') is not None}
    resolved_guild_id = str(guild_id).strip() if guild_id else ''

    if not resolved_guild_id and channel_id:
        detail, ch_err = _get_channel_detail(channel_id)
        if ch_err:
            return None, ch_err
        resolved_guild_id = str(detail.get('guild_id') or '').strip()

    target_guild_ids = [resolved_guild_id] if resolved_guild_id else list(guild_map.keys())
    if not target_guild_ids:
        return {
            'resolved_guild_id': '',
            'resolved_guild_name': '',
            'guilds': [],
            'roles': [],
        }, None

    roles = []
    for gid in target_guild_ids:
        try:
            resp = requests.get(
                f'{KOOK_API_BASE}/guild-role/list',
                headers=_headers(),
                params={'guild_id': str(gid)},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            logger.warning('[KOOK] 获取角色列表异常(guild=%s): %s', gid, e)
            continue

        if data.get('code') != 0:
            logger.warning('[KOOK] 获取角色列表失败(guild=%s): %s', gid, data)
            continue

        role_items = _extract_items(data.get('data') or {})
        guild_name = (guild_map.get(str(gid)) or {}).get('name') or f'服务器 {gid}'
        for role in role_items:
            role_id = str(role.get('role_id') or role.get('id') or '').strip()
            if not role_id:
                continue
            perms_value, perm_bits = _permission_bits(role.get('permissions'))
            roles.append({
                'id': role_id,
                'name': str(role.get('name') or role.get('role_name') or role_id),
                'permissions': perms_value,
                'permission_bits': perm_bits,
                'hoist': bool(role.get('hoist')),
                'mentionable': bool(role.get('mentionable', True)),
                'position': _safe_int(role.get('position'), 0),
                'guild_id': str(gid),
                'guild_name': guild_name,
            })

    roles.sort(key=lambda x: (x.get('guild_name', ''), -_safe_int(x.get('position'), 0), x.get('name', '')))
    guild_list = [{
        'id': str(g.get('id')),
        'name': str(g.get('name') or g.get('id')),
    } for g in guilds if g.get('id') is not None]

    result = {
        'resolved_guild_id': resolved_guild_id,
        'resolved_guild_name': (guild_map.get(resolved_guild_id) or {}).get('name', ''),
        'guilds': guild_list,
        'roles': roles,
    }
    return result, None


def _resolve_image_url(image_value):
    """将图片字段解析为 KOOK 可访问 URL。"""
    raw = str(image_value or '').strip()
    if not raw:
        return ''

    if raw.startswith('http://') or raw.startswith('https://'):
        return raw

    site_url = _get_site_url()
    if not site_url:
        return raw

    if raw.startswith('/'):
        return f'{site_url}{raw}'

    # 上传图片通常保存为 uploads/xxx，需要拼接 /static/
    if raw.startswith('uploads/'):
        return f'{site_url}/static/{raw}'

    if raw.startswith('static/'):
        return f'{site_url}/{raw}'

    return f'{site_url}/{raw}'


def _resolve_local_image_path(image_value):
    """将数据库中的图片字段解析为本地文件路径（用于上传 KOOK 资源）。"""
    raw = str(image_value or '').strip()
    if not raw:
        return ''

    if raw.startswith('http://') or raw.startswith('https://'):
        return ''

    app_root = current_app.root_path
    if raw.startswith('/'):
        return raw
    if raw.startswith('uploads/'):
        return os.path.join(app_root, 'static', raw)
    if raw.startswith('static/'):
        return os.path.join(app_root, raw)
    return os.path.join(app_root, raw)


def _upload_kook_asset_from_file(local_path):
    """上传本地文件到 KOOK 资源，返回 KOOK 资源 URL。"""
    if not local_path or not os.path.exists(local_path):
        return ''
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return ''
    try:
        with open(local_path, 'rb') as fp:
            resp = requests.post(
                f'{KOOK_API_BASE}/asset/create',
                headers={'Authorization': f'Bot {_get_token()}'},
                files={'file': (os.path.basename(local_path), fp)},
                timeout=20,
            )
        data = resp.json()
        if data.get('code') != 0:
            logger.warning('[KOOK] 上传资源失败: %s', data)
            return ''
        return str(data.get('data', {}).get('url') or '')
    except Exception as e:
        logger.warning('[KOOK] 上传资源异常: %s', e)
        return ''


def _send_channel_image(channel_id, image_url):
    """发送频道图片消息(type=2)，image_url 需为 KOOK 资源链接。"""
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return False
    if not image_url:
        return False
    try:
        resp = requests.post(
            f'{KOOK_API_BASE}/message/create',
            headers=_headers(),
            json={'target_id': str(channel_id), 'content': str(image_url), 'type': 2},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.warning('[KOOK] 发送图片消息失败: %s', data)
            return False
        return True
    except Exception as e:
        logger.warning('[KOOK] 发送图片消息异常: %s', e)
        return False


def _build_card(title, content, color='#7C3AED', button_text=None, button_url=None, image_url=None):
    """构建普通 KMarkdown 文本（无卡片边框样式）"""
    def _preserve_leading_spaces(text):
        # KOOK/KMarkdown 会折叠普通空格：
        # 1) 行首缩进转为 NBSP 保留
        # 2) 行内连续空格(>=2)也转为 NBSP，尽量保留 ASCII 图案排版
        nbsp = '\u00A0'
        out = []
        for raw_line in str(text or '').split('\n'):
            normalized = raw_line.replace('\t', '    ')
            idx = 0
            while idx < len(normalized) and normalized[idx] == ' ':
                idx += 1
            prefix = nbsp * idx
            body = normalized[idx:]
            body = re.sub(r' {2,}', lambda m: nbsp * len(m.group(0)), body)
            out.append(prefix + body)
        return '\n'.join(out)

    lines = [_preserve_leading_spaces(content or '')]

    # 卡片按钮降级为普通链接，保持“可跳转”
    if button_url:
        if button_text:
            lines.append(f'{button_text}: {button_url}')
        else:
            lines.append(str(button_url))

    # 附图：使用官方 KMarkdown 链接解析语法触发缩略图
    # 文档说明：链接文本与链接地址完全一致，才会显示链接解析(缩略图)
    resolved_image = _resolve_image_url(image_url)
    if resolved_image:
        safe_url = resolved_image.replace(')', '%29').replace('(', '%28')
        lines.append(f'[{safe_url}]({safe_url})')

    return '\n'.join([ln for ln in lines if ln is not None and ln != ''])


def _wrap_dm_card(markdown_text, color='#EC4899', button_text=None, button_url=None):
    """将文本包装为私信卡片（粉色边框，可选底部跳转按钮）"""
    modules = [
        {"type": "section", "text": {"type": "kmarkdown", "content": str(markdown_text or '')}}
    ]
    if button_url:
        modules.append({
            "type": "action-group",
            "elements": [{
                "type": "button",
                "theme": "primary",
                "value": str(button_url),
                "click": "link",
                "text": {"type": "plain-text", "content": str(button_text or '前往查看')},
            }],
        })

    card = [{
        "type": "card",
        "theme": "secondary",
        "color": color,
        "size": "lg",
        "modules": modules,
    }]
    return json.dumps(card)


def _send_channel_msg(channel_id, markdown_text):
    """向频道发送普通 KMarkdown 消息"""
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        logger.warning('[KOOK] Token 未配置，跳过推送')
        return False
    try:
        resp = requests.post(
            f'{KOOK_API_BASE}/message/create',
            headers=_headers(),
            json={'target_id': str(channel_id), 'content': markdown_text, 'type': 9},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[KOOK] 频道消息失败: {data}')
            return False
        return True
    except Exception as e:
        logger.error(f'[KOOK] 频道消息异常: {e}')
        return False


def _send_direct_msg(user_kook_id, markdown_text, button_text=None, button_url=None):
    """向用户发送私信卡片消息（粉色边框）"""
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        logger.warning('[KOOK] Token 未配置，跳过推送')
        return False
    try:
        card_json = _wrap_dm_card(markdown_text, button_text=button_text, button_url=button_url)
        resp = requests.post(
            f'{KOOK_API_BASE}/direct-message/create',
            headers=_headers(),
            json={'target_id': str(user_kook_id), 'content': card_json, 'type': 10},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            logger.error(f'[KOOK] 私信失败: {data}')
            return False
        return True
    except Exception as e:
        logger.error(f'[KOOK] 私信异常: {e}')
        return False


def _async_send(func, *args):
    """在后台线程中发送，不阻塞 Flask 请求"""
    # 捕获当前 Flask app 对象，在新线程中推入 app context
    # 否则 _get_token() 使用 current_app 会报 RuntimeError
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            func(*args)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def send_direct_message(user_kook_id, content):
    """
    通用发送私信接口
    :param user_kook_id: 目标用户 ID
    :param content: 消息内容 (字符串或 JSON 卡片)
    :return: True/False
    """
    msg_type = 10 if (isinstance(content, str) and content.startswith('{')) else 9 # 9: markdown, 10: card
    
    # 如果是 khl.card 对象，转为 json
    try:
        if hasattr(content, 'to_json'):
             content = json.dumps(content.to_json())
             msg_type = 10
    except:
        pass

    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return False

    try:
        resp = requests.post(
            f'{KOOK_API_BASE}/direct-message/create',
            headers=_headers(),
            json={'target_id': str(user_kook_id), 'content': content, 'type': msg_type},
            timeout=10,
        )
        data = resp.json()
        return data.get('code') == 0
    except Exception as e:
        logger.error(f'[KOOK] 发送私信异常: {e}')
        return False


def fetch_kook_user(kook_id):
    """
    通过 KOOK ID 查询用户信息
    :return: (kook_username, avatar_url, error) — 成功时 error 为 None
    """
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return None, None, 'KOOK Token 未配置'
    try:
        resp = requests.get(
            f'{KOOK_API_BASE}/user/view',
            headers=_headers(),
            params={'user_id': str(kook_id)},
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            msg = data.get('message', '未知错误')
            logger.warning(f'[KOOK] 查询用户失败: {msg}')
            return None, None, msg
        user_data = data.get('data', {})
        username = user_data.get('username', '')
        identify_num = user_data.get('identify_num', '')
        avatar_url = user_data.get('avatar', '')
        kook_username = f'{username}#{identify_num}' if username and identify_num else (username or str(kook_id))
        return kook_username, avatar_url, None
    except Exception as e:
        logger.error(f'[KOOK] 查询用户异常: {e}')
        return None, None, str(e)


def search_kook_user_by_name(kook_name):
    """
    通过 KOOK 名称 (abc#1234) 在 Bot 所在服务器中查找用户
    :return: (kook_id, kook_username, avatar_url, error)
    """
    if not _get_token() or _get_token() == 'your-kook-bot-token':
        return None, None, None, 'KOOK Token 未配置'

    kook_name = (kook_name or '').strip()
    if '#' not in kook_name:
        return None, None, None, '请输入完整的 KOOK 名称，格式: 用户名#数字'

    target_username, target_identify = kook_name.rsplit('#', 1)
    target_username = target_username.strip()
    target_identify = target_identify.strip()
    if not target_username or not target_identify:
        return None, None, None, '请输入完整的 KOOK 名称，格式: 用户名#数字'

    try:
        # 1. 获取 Bot 所在的所有服务器
        resp = requests.get(
            f'{KOOK_API_BASE}/guild/list',
            headers=_headers(),
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            return None, None, None, f'获取服务器列表失败: {data.get("message", "")}'

        guild_ids = [g['id'] for g in data.get('data', {}).get('items', [])]
        if not guild_ids:
            return None, None, None, '机器人未加入任何服务器'

        # 2. 在每个服务器中搜索用户
        for guild_id in guild_ids:
            page = 1
            while True:
                resp = requests.get(
                    f'{KOOK_API_BASE}/guild/user-list',
                    headers=_headers(),
                    params={
                        'guild_id': guild_id,
                        'search': target_username,
                        'page': page,
                        'page_size': 50,
                    },
                    timeout=10,
                )
                data = resp.json()
                if data.get('code') != 0:
                    break

                items = data.get('data', {}).get('items', [])
                for u in items:
                    if (u.get('username', '') == target_username and
                            str(u.get('identify_num', '')) == target_identify):
                        uid = str(u['id'])
                        uname = f"{u['username']}#{u['identify_num']}"
                        avatar = u.get('avatar', '')
                        return uid, uname, avatar, None

                # 检查是否还有下一页
                meta = data.get('data', {}).get('meta', {})
                if page >= meta.get('page_total', 1):
                    break
                page += 1

        return None, None, None, '未找到该 KOOK 用户，请确认名称正确且与机器人在同一服务器'

    except Exception as e:
        logger.error(f'[KOOK] 搜索用户异常: {e}')
        return None, None, None, str(e)


# ===== 播报类型元数据 =====

BROADCAST_TYPES = {
    # --- 频道播报 ---
    'recharge': {
        'label': '充值播报',
        'group': '频道播报',
        'target': 'channel',
        'color': '#10B981',
        'title': '充值播报',
        'variables': {
            '{user}': '用户昵称（匿名时自动替换）',
            '{amount}': '充值金额',
            '{role}': '身份（老板/陪玩）',
            '{@user}': '@充值用户（KOOK提及）',
            '{@all}': '@全体成员',
            '{@here}': '@在线成员',
        },
        'default_template': '`{user}` 充值了 `{amount}` 嗯呢币',
        'hint': '按金额档位触发，阈值 = 最低触发金额；老板和陪玩充值都会触发',
    },
    'gift': {
        'label': '礼物播报',
        'group': '频道播报',
        'target': 'channel',
        'color': '#EC4899',
        'title': '礼物播报',
        'variables': {
            '{user}': '老板昵称（匿名时自动替换）',
            '{player}': '陪玩昵称（匿名时自动替换）',
            '{gift_name}': '礼物名称',
            '{quantity}': '数量',
            '{amount}': '总价',
            '{@user}': '@老板（KOOK提及）',
            '{@player}': '@陪玩（KOOK提及）',
            '{@all}': '@全体成员',
            '{@here}': '@在线成员',
        },
        'default_template': '`{user}` 送给 `{player}` `{gift_name}` x`{quantity}`',
        'hint': '赠礼成功后自动播报到频道（需配置频道ID）',
    },
    'upgrade': {
        'label': '升级播报',
        'group': '频道播报',
        'target': 'channel',
        'color': '#F59E0B',
        'title': '等级升级',
        'variables': {
            '{user}': '用户昵称（匿名时自动替换）',
            '{from_level}': '原等级',
            '{level}': '新等级',
            '{@user}': '@升级用户（KOOK提及）',
            '{@all}': '@全体成员',
            '{@here}': '@在线成员',
        },
        'default_template': '恭喜 `{user}` 升级为 `{level}`!',
        'hint': 'VIP升级时自动播报到频道；支持通用模板和按目标等级配置专属模板',
    },
    # --- 抽奖模板 ---
    'lottery_announce': {
        'label': '抽奖公告',
        'group': '抽奖模板',
        'target': 'template',
        'color': '#7C3AED',
        'title': '🎰 抽奖活动',
        'variables': {
            '{title}': '抽奖标题',
            '{prize}': '奖品名称',
            '{winner_count}': '中奖名额',
            '{roles}': '参与资格',
            '{vip}': 'VIP等级要求（无要求时为空）',
            '{description}': '活动描述（无描述时为空）',
            '{count}': '当前参与人数',
        },
        'default_template': (
            '**{title}**\n\n'
            '奖品: **{prize}**\n'
            '名额: **{winner_count}** 人\n'
            '参与资格: {roles}\n'
            '{vip}{description}'
            '添加任意表情回应即可参与抽奖!\n'
            '当前参与人数: **{count}** 人'
        ),
        'hint': '发布抽奖时发到频道的公告卡片。第一行可写 # 自定义标题（或 标题: 自定义标题）来自定义卡片标题。',
    },
    'lottery_result': {
        'label': '开奖结果',
        'group': '抽奖模板',
        'target': 'template',
        'color': '#10B981',
        'title': '开奖结果',
        'variables': {
            '{title}': '抽奖标题',
            '{prize}': '奖品名称',
            '{winners}': '中奖者列表（含@提及）',
        },
        'default_template': (
            '**{title}** 开奖结果\n---\n'
            '奖品: **{prize}**\n'
            '中奖者:\n{winners}'
        ),
        'hint': '开奖后发到频道的结果卡片。第一行可写 # 自定义标题（或 标题: 自定义标题）来自定义卡片标题。',
    },
    'lottery_winner': {
        'label': '中奖通知',
        'group': '抽奖模板',
        'target': 'template',
        'color': '#10B981',
        'title': '🎉 中奖通知',
        'variables': {
            '{title}': '抽奖标题',
            '{prize}': '奖品名称',
        },
        'default_template': (
            '**恭喜你中奖了!**\n---\n'
            '活动: **{title}**\n'
            '奖品: **{prize}**\n---\n'
            '请联系客服领取奖品~'
        ),
        'hint': '开奖后私信中奖者。第一行可写 # 自定义标题（或 标题: 自定义标题）来自定义卡片标题。',
    },
    'channel_join': {
        'label': '进入频道提醒',
        'group': '频道播报',
        'target': 'channel',
        'color': '#10B981',
        'title': '进入频道',
        'variables': {
            '{user}': '用户昵称',
            '{channel}': '语音频道名称',
            '{@user}': '@进入的用户（KOOK提及）',
        },
        'default_template': '`{user}` 进入了 `{channel}`',
        'hint': '用户进入语音频道时自动播报到配置的文字频道',
    },
    'channel_leave': {
        'label': '离开频道提醒',
        'group': '频道播报',
        'target': 'channel',
        'color': '#EF4444',
        'title': '离开频道',
        'variables': {
            '{user}': '用户昵称',
            '{channel}': '语音频道名称',
            '{@user}': '@离开的用户（KOOK提及）',
        },
        'default_template': '`{user}` 离开了 `{channel}`',
        'hint': '用户离开语音频道时自动播报到配置的文字频道',
    },
    # --- 私信通知 ---
    'boss_recharge': {
        'label': '老板充值通知',
        'group': '私信通知',
        'target': 'dm',
        'color': '#10B981',
        'title': '充值到账',
        'variables': {
            '{user}': '老板昵称',
            '{amount}': '本次充值金额',
            '{balance}': '当前嗯呢币总余额（含赠金）',
            '{reason}': '变账原因',
            '{operator}': '操作人（若有）',
        },
        'default_template': (
            '**充值成功**\n---\n'
            '老板: `{user}`\n'
            '本次充值: `{amount}` 嗯呢币\n'
            '当前余额: `{balance}` 嗯呢币\n'
            '原因: `{reason}`\n'
            '操作人: `{operator}`'
        ),
        'hint': '老板产生充值（含客服手动充值/赠金）时私信老板',
    },
    'boss_consume': {
        'label': '老板消费通知',
        'group': '私信通知',
        'target': 'dm',
        'color': '#F59E0B',
        'title': '消费扣款',
        'variables': {
            '{user}': '老板昵称',
            '{amount}': '本次消费金额',
            '{balance}': '当前嗯呢币总余额（含赠金）',
            '{reason}': '消费原因',
            '{operator}': '操作人（若有）',
        },
        'default_template': (
            '**余额变动提醒**\n---\n'
            '老板: `{user}`\n'
            '本次消费: `{amount}` 嗯呢币\n'
            '当前余额: `{balance}` 嗯呢币\n'
            '原因: `{reason}`\n'
            '操作人: `{operator}`'
        ),
        'hint': '老板产生消费（订单/礼物/客服手动扣款）时私信老板',
    },
    'order_refund_boss': {
        'label': '订单退款通知 → 老板',
        'group': '私信通知',
        'target': 'dm',
        'color': '#EF4444',
        'title': '订单已退款',
        'variables': {
            '{boss}': '老板昵称',
            '{player}': '陪玩昵称',
            '{order_no}': '订单号',
            '{game}': '游戏项目',
            '{amount}': '退款金额',
            '{balance}': '退款后老板余额（嗯呢币）',
            '{operator}': '处理人',
        },
        'default_template': (
            '**订单退款成功**\n---\n'
            '订单号: `{order_no}`\n'
            '游戏项目: `{game}`\n'
            '陪玩: `{player}`\n'
            '退款金额: `{amount}` 嗯呢币\n'
            '当前余额: `{balance}` 嗯呢币\n'
            '处理人: `{operator}`'
        ),
        'hint': '订单退款成功后私信老板',
    },
    'order_refund_player': {
        'label': '订单退款通知 → 陪玩',
        'group': '私信通知',
        'target': 'dm',
        'color': '#EF4444',
        'title': '订单退款通知',
        'variables': {
            '{boss}': '老板昵称',
            '{player}': '陪玩昵称',
            '{order_no}': '订单号',
            '{game}': '游戏项目',
            '{amount}': '订单金额（退款额）',
            '{deduct}': '扣回收益',
            '{balance}': '当前可用小猪粮余额',
            '{operator}': '处理人',
        },
        'default_template': (
            '**订单已退款，收益已扣回**\n---\n'
            '订单号: `{order_no}`\n'
            '游戏项目: `{game}`\n'
            '老板: `{boss}`\n'
            '订单金额: `{amount}` 嗯呢币\n'
            '扣回收益: `{deduct}` 小猪粮\n'
            '当前可用小猪粮: `{balance}`\n'
            '处理人: `{operator}`'
        ),
        'hint': '订单退款成功后私信陪玩',
    },
    'order_dispatch': {
        'label': '派单通知 → 陪玩',
        'group': '私信通知',
        'target': 'dm',
        'color': '#7C3AED',
        'title': '新订单通知',
        'variables': {
            '{boss}': '老板昵称',
            '{player}': '陪玩昵称',
            '{game}': '游戏项目',
            '{order_no}': '订单号',
            '{price}': '单价',
            '{est_hours}': '预计可玩时长',
        },
        'default_template': (
            '**你有一笔新的待处理陪玩订单哦>.<..**\n---\n'
            '游戏项目: `{game}`\n点单老板: `{boss}`\n单价: `{price}`\n'
            '老板余额预计支持 大于 `{est_hours}` 小时/局\n---\n'
            '超时请提醒老板续费并咨询客服是否收到续费...\n'
            '游戏结束后登录后台进行"结单申报"填写局数/总时长'
        ),
        'hint': '新订单派发时私信陪玩',
    },
    'boss_order_dispatch': {
        'label': '派单通知 → 老板',
        'group': '私信通知',
        'target': 'dm',
        'color': '#06B6D4',
        'title': '订单已创建',
        'variables': {
            '{boss}': '老板昵称',
            '{player}': '陪玩昵称',
            '{game}': '游戏项目',
            '{order_no}': '订单号',
            '{type}': '订单类型（常规/护航/代练）',
            '{amount}': '订单金额（常规订单为待申报）',
            '{status}': '当前订单状态',
            '{staff}': '派单客服',
        },
        'default_template': (
            '**你的订单已创建成功**\n---\n'
            '订单号: `{order_no}`\n游戏项目: `{game}`\n'
            '陪玩: `{player}`\n订单类型: `{type}`\n'
            '订单金额: `{amount}`\n当前状态: `{status}`\n'
            '派单客服: `{staff}`'
        ),
        'hint': '客服派单后私信老板',
    },
    'order_report': {
        'label': '申报通知 → 老板',
        'group': '私信通知',
        'target': 'dm',
        'color': '#3B82F6',
        'title': '订单已申报',
        'variables': {
            '{player}': '陪玩昵称',
            '{game}': '游戏项目',
            '{order_no}': '订单号',
            '{duration}': '游戏时长',
            '{amount}': '订单金额',
        },
        'default_template': (
            '**你的陪玩订单已完成申报!**\n---\n'
            '订单号: `{order_no}`\n游戏项目: `{game}`\n'
            '陪玩: `{player}`\n游戏时长: `{duration}`h\n'
            '订单金额: `{amount}` 嗯呢币\n---\n'
            '请确认订单，24小时后将自动确认。'
        ),
        'hint': '陪玩申报时长后私信老板',
    },
    'order_confirm': {
        'label': '确认通知 → 陪玩',
        'group': '私信通知',
        'target': 'dm',
        'color': '#10B981',
        'title': '订单已确认',
        'variables': {
            '{order_no}': '订单号',
            '{amount}': '订单金额',
            '{earning}': '到手收益',
            '{balance}': '当前小猪粮余额',
        },
        'default_template': (
            '**订单已确认，佣金已到账!**\n---\n'
            '订单号: `{order_no}`\n订单金额: `{amount}` 嗯呢币\n'
            '到手收益: `{earning}` 小猪粮\n当前小猪粮: `{balance}` 小猪粮'
        ),
        'hint': '老板确认/24h自动确认后私信陪玩',
    },
    'order_settle': {
        'label': '结算通知 → 陪玩',
        'group': '私信通知',
        'target': 'dm',
        'color': '#10B981',
        'title': '订单已结算',
        'variables': {
            '{order_no}': '订单号',
            '{earning}': '到手收益',
            '{balance}': '当前小猪粮余额',
        },
        'default_template': (
            '**护航/代练订单已结算，佣金已解冻到账!**\n---\n'
            '订单号: `{order_no}`\n到手收益: `{earning}` 小猪粮\n'
            '当前可用小猪粮: `{balance}` 小猪粮'
        ),
        'hint': '护航/代练结算后私信陪玩',
    },
    'escort_dispatch': {
        'label': '护航/代练通知 → 陪玩',
        'group': '私信通知',
        'target': 'dm',
        'color': '#8B5CF6',
        'title': '新订单通知',
        'variables': {
            '{boss}': '老板昵称',
            '{game}': '游戏项目',
            '{order_no}': '订单号',
            '{amount}': '订单金额',
            '{earning}': '到手收益',
            '{type}': '订单类型（护航/代练）',
        },
        'default_template': (
            '**你有一笔新的{type}订单!**\n---\n'
            '订单号: `{order_no}`\n游戏项目: `{game}`\n'
            '点单老板: `{boss}`\n订单金额: `{amount}` 嗯呢币\n'
            '到手收益: `{earning}` 小猪粮 (冻结中)\n---\n'
            '佣金已冻结，待客服结算后到账'
        ),
        'hint': '护航/代练派单时私信陪玩',
    },
    'gift_receive': {
        'label': '收到礼物通知 → 收礼人',
        'group': '私信通知',
        'target': 'dm',
        'color': '#EC4899',
        'title': '收到礼物',
        'variables': {
            '{boss}': '赠送人昵称（匿名时自动替换）',
            '{gift_name}': '礼物名称',
            '{quantity}': '数量',
            '{amount}': '礼物总价',
            '{earning}': '到手收益',
        },
        'default_template': (
            '**你收到了一份礼物!**\n---\n'
            '赠送人: `{boss}`\n礼物: `{gift_name}` x`{quantity}`\n'
            '礼物价值: `{amount}` 嗯呢币\n你的收益: `{earning}` 小猪粮'
        ),
        'hint': '收到礼物后私信收礼人',
    },
    'withdraw_submit': {
        'label': '提现提交通知',
        'group': '私信通知',
        'target': 'dm',
        'color': '#3B82F6',
        'title': '提现申请已提交',
        'variables': {
            '{user}': '申请人昵称（优先陪玩昵称）',
            '{request_id}': '提现单号',
            '{amount}': '提现金额',
            '{balance}': '当前可用小猪粮',
            '{frozen}': '当前冻结小猪粮',
            '{status}': '当前状态',
        },
        'default_template': (
            '**提现申请已提交**\n---\n'
            '申请人: `{user}`\n'
            '提现单号: `#{request_id}`\n'
            '提现金额: `{amount}` 小猪粮\n'
            '当前状态: `{status}`\n'
            '可用小猪粮: `{balance}`\n'
            '冻结小猪粮: `{frozen}`'
        ),
        'hint': '提交提现后私信申请人',
    },
    'withdraw_approved': {
        'label': '提现通过通知',
        'group': '私信通知',
        'target': 'dm',
        'color': '#10B981',
        'title': '提现已通过',
        'variables': {
            '{user}': '申请人昵称（优先陪玩昵称）',
            '{request_id}': '提现单号',
            '{amount}': '提现金额',
            '{operator}': '审核人',
            '{remark}': '审核备注',
            '{balance}': '当前可用小猪粮',
            '{frozen}': '当前冻结小猪粮',
            '{status}': '当前状态',
        },
        'default_template': (
            '**提现审核通过，已打款**\n---\n'
            '申请人: `{user}`\n'
            '提现单号: `#{request_id}`\n'
            '提现金额: `{amount}` 小猪粮\n'
            '状态: `{status}`\n'
            '审核人: `{operator}`\n'
            '备注: `{remark}`\n'
            '可用小猪粮: `{balance}`\n'
            '冻结小猪粮: `{frozen}`'
        ),
        'hint': '提现审核通过后私信申请人',
    },
    'withdraw_rejected': {
        'label': '提现拒绝通知',
        'group': '私信通知',
        'target': 'dm',
        'color': '#EF4444',
        'title': '提现已拒绝',
        'variables': {
            '{user}': '申请人昵称（优先陪玩昵称）',
            '{request_id}': '提现单号',
            '{amount}': '提现金额',
            '{operator}': '审核人',
            '{remark}': '拒绝原因/备注',
            '{balance}': '当前可用小猪粮',
            '{frozen}': '当前冻结小猪粮',
            '{status}': '当前状态',
        },
        'default_template': (
            '**提现申请未通过**\n---\n'
            '申请人: `{user}`\n'
            '提现单号: `#{request_id}`\n'
            '申请金额: `{amount}` 小猪粮\n'
            '状态: `{status}`\n'
            '审核人: `{operator}`\n'
            '原因: `{remark}`\n'
            '可用小猪粮: `{balance}`\n'
            '冻结小猪粮: `{frozen}`'
        ),
        'hint': '提现审核拒绝后私信申请人（金额已退回）',
    },
    'birthday_dm': {
        'label': '生日祝福私信',
        'group': '私信通知',
        'target': 'dm',
        'color': '#EC4899',
        'title': '生日快乐',
        'variables': {
            '{user}': '用户昵称',
            '{birthday}': '生日日期（MM-DD）',
            '{year}': '当前年份',
        },
        'default_template': (
            '🎂 **生日快乐，{user}！**\n---\n'
            '今天是你的生日（{birthday}），\n'
            '祝你在新的一岁里天天开心、把把连胜！'
        ),
        'hint': '每天定时检查当日生日用户并私信祝福',
    },
    'birthday_channel': {
        'label': '生日频道播报',
        'group': '频道播报',
        'target': 'channel',
        'color': '#F472B6',
        'title': '生日祝福',
        'variables': {
            '{user}': '用户昵称',
            '{birthday}': '生日日期（MM-DD）',
            '{year}': '当前年份',
            '{@user}': '用户提及（失败时回退昵称）',
            '{@all}': '@全体成员',
            '{@here}': '@在线成员',
        },
        'default_template': (
            '🎂 **今天是 {user} 的生日**\n---\n'
            '生日日期: `{birthday}`\n'
            '一起祝 {@user} 生日快乐，新的这一岁顺顺利利！'
        ),
        'hint': '每天定时检查当日生日用户并发送到指定频道，需要填写频道ID',
    },
    'weekly_withdraw_reminder': {
        'label': '定时提现提醒',
        'group': '定时任务',
        'target': 'channel',
        'color': '#06B6D4',
        'title': '提现提醒',
        'variables': {
            '{weekday}': '星期几',
            '{time}': '触发时间（HH:MM）',
            '{roles}': '@角色提及字符串（由角色Tag自动生成）',
            '{@all}': '@全体成员',
            '{@here}': '@在线成员',
        },
        'default_template': (
            '{roles}\n'
            '【提现提醒】今天是{weekday}，请符合条件的陪玩及时提交提现申请。'
        ),
        'hint': '按周定时触发：需配置频道ID、周几、时间、@角色Tag列表',
    },
}


def _get_broadcast_config(broadcast_type):
    """从 BroadcastConfig 获取完整配置对象（取最新一条启用配置）"""
    from app.models.broadcast import BroadcastConfig
    return BroadcastConfig.query.filter_by(
        broadcast_type=broadcast_type, status=True
    ).order_by(BroadcastConfig.updated_at.desc(), BroadcastConfig.id.desc()).first()


def _get_custom_template(broadcast_type):
    """从 BroadcastConfig 获取自定义模板（最新启用配置优先）"""
    config = _get_broadcast_config(broadcast_type)
    if config and config.template and config.template.strip():
        return config.template
    return None


def _is_broadcast_enabled(broadcast_type):
    """
    广播类型开关判断：
    - 若不存在配置记录，默认启用（兼容历史行为）
    - 若存在配置记录，至少一条 status=True 才视为启用
    """
    from app.models.broadcast import BroadcastConfig

    rows = BroadcastConfig.query.filter_by(broadcast_type=broadcast_type).all()
    if not rows:
        return True
    return any(bool(r.status) for r in rows)


def _render_tpl(template, variables):
    """渲染模板，替换 {var} 变量"""
    result = template
    for key, value in variables.items():
        result = result.replace('{' + key + '}', str(value))
    return result


def _kook_mention(kook_id):
    """生成 KOOK @提及 语法"""
    return f'(met){kook_id}(met)' if kook_id else ''


def _fallback_display_name(user, prefer_player_name=False):
    """获取用户显示名（未匿名场景）"""
    if not user:
        return ''
    if prefer_player_name:
        return user.player_nickname or user.nickname or user.username
    return user.nickname or user.username


def _display_name(user, anonymous=False, anonymous_text='匿名用户', prefer_player_name=False):
    """获取最终展示名（支持匿名）"""
    if anonymous:
        return anonymous_text
    return _fallback_display_name(user, prefer_player_name=prefer_player_name)


def _mention_or_text(user, text_value):
    """模板中的 {@user}/{@player} 变量：优先 @ 提及，失败回退文本"""
    mention = _kook_mention(getattr(user, 'kook_id', None))
    return mention or text_value


def _get_type_meta(broadcast_type):
    """获取播报类型元数据"""
    return BROADCAST_TYPES.get(broadcast_type, {})


# ===== 业务推送函数 =====

def _get_site_url():
    """获取系统站点URL"""
    def _normalize(url_text):
        url = (url_text or '').strip().rstrip('/')
        if not url:
            return ''
        try:
            parsed = urlparse(url if '://' in url else f'http://{url}')
            host = (parsed.hostname or '').lower()
            if host in ('localhost', '127.0.0.1') or host.startswith('127.'):
                public_url = (current_app.config.get('PUBLIC_SITE_URL', '') or '').strip().rstrip('/')
                return public_url or url
        except Exception:
            return url
        return url

    try:
        site_url = _normalize(current_app.config.get('SITE_URL', ''))
        if site_url:
            return site_url
        return _normalize(current_app.config.get('PUBLIC_SITE_URL', ''))
    except RuntimeError:
        return ''


def push_order_dispatch(order, site_url=''):
    """派单推送 → 私信陪玩"""
    player = order.player
    if not player.kook_id or not player.kook_bound:
        return

    site_url = (site_url or '').strip().rstrip('/')
    if not site_url:
        site_url = _get_site_url()
    else:
        parsed = urlparse(site_url if '://' in site_url else f'http://{site_url}')
        host = (parsed.hostname or '').lower()
        if host in ('localhost', '127.0.0.1') or host.startswith('127.'):
            site_url = _get_site_url()
    boss_name = order.boss.nickname or order.boss.username
    unit_price = float(order.base_price) + float(order.extra_price)
    boss_balance = float(order.boss.m_coin + order.boss.m_coin_gift)
    est_hours = int(boss_balance / unit_price) if unit_price > 0 else 0
    report_url = f'{site_url}/orders/report/{order.order_no}' if site_url else ''

    variables = {
        'boss': boss_name,
        'player': player.player_nickname or player.nickname,
        'game': order.project_display,
        'order_no': order.order_no,
        'price': str(unit_price),
        'est_hours': str(est_hours),
    }

    meta = BROADCAST_TYPES['order_dispatch']
    content = _render_tpl(_get_custom_template('order_dispatch') or meta['default_template'], variables)
    # 追加 bot 命令提示
    content += f'\n---\n也可以通过机器人命令结单: `/结单 {order.order_no} 时长`'

    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, player.kook_id, card, '前往后台结单', report_url if report_url else None)


def push_boss_order_dispatch(order, site_url=''):
    """派单推送 → 私信老板"""
    boss = order.boss
    if not boss.kook_id or not boss.kook_bound:
        return

    site_url = (site_url or '').strip().rstrip('/')
    if not site_url:
        site_url = _get_site_url()
    else:
        parsed = urlparse(site_url if '://' in site_url else f'http://{site_url}')
        host = (parsed.hostname or '').lower()
        if host in ('localhost', '127.0.0.1') or host.startswith('127.'):
            site_url = _get_site_url()
    detail_url = f'{site_url}/orders' if site_url else None
    order_type_map = {'normal': '常规陪玩', 'escort': '护航', 'training': '代练'}
    order_type = order_type_map.get(order.order_type, order.order_type or '订单')

    amount_text = '待申报'
    if order.total_price and float(order.total_price) > 0:
        amount_text = f'{order.total_price} 嗯呢币'

    variables = {
        'boss': boss.nickname or boss.username,
        'player': order.player.player_nickname or order.player.nickname or order.player.username,
        'game': order.project_display,
        'order_no': order.order_no,
        'type': order_type,
        'amount': amount_text,
        'status': order.status_label,
        'staff': order.staff.staff_display_name if order.staff else '系统',
    }

    meta = BROADCAST_TYPES['boss_order_dispatch']
    content = _render_tpl(_get_custom_template('boss_order_dispatch') or meta['default_template'], variables)

    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, boss.kook_id, card, '前往订单中心', detail_url)


def push_order_report(order, site_url=''):
    """申报推送 → 私信老板"""
    boss = order.boss
    if not boss.kook_id or not boss.kook_bound:
        return

    site_url = (site_url or '').strip().rstrip('/')
    if not site_url:
        site_url = _get_site_url()
    else:
        parsed = urlparse(site_url if '://' in site_url else f'http://{site_url}')
        host = (parsed.hostname or '').lower()
        if host in ('localhost', '127.0.0.1') or host.startswith('127.'):
            site_url = _get_site_url()
    confirm_url = ''
    if site_url:
        order_no = quote(str(order.order_no or ''), safe='')
        confirm_url = f'{site_url}/orders/confirm/{order_no}'

    variables = {
        'player': order.player.player_nickname or order.player.nickname,
        'game': order.project_display,
        'order_no': order.order_no,
        'duration': str(order.duration),
        'amount': str(order.total_price),
    }

    meta = BROADCAST_TYPES['order_report']
    content = _render_tpl(_get_custom_template('order_report') or meta['default_template'], variables)
    # 追加 bot 命令提示
    content += f'\n---\n也可以通过机器人命令确认: `/确认 {order.order_no}`'

    card = _build_card(
        meta['title'],
        content,
        meta['color'],
    )
    _async_send(_send_direct_msg, boss.kook_id, card, '前往后台确认', confirm_url if confirm_url else None)


def push_order_confirm(order):
    """确认通知 → 私信陪玩"""
    player = order.player
    if not player.kook_id or not player.kook_bound:
        return

    variables = {
        'order_no': order.order_no,
        'amount': str(order.total_price),
        'earning': str(order.player_earning),
        'balance': str(player.m_bean),
    }

    meta = BROADCAST_TYPES['order_confirm']
    content = _render_tpl(_get_custom_template('order_confirm') or meta['default_template'], variables)

    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, player.kook_id, card)


def push_order_settle(order):
    """护航/代练结算通知 → 私信陪玩"""
    player = order.player
    if not player.kook_id or not player.kook_bound:
        return

    variables = {
        'order_no': order.order_no,
        'earning': str(order.player_earning),
        'balance': str(player.m_bean),
    }

    meta = BROADCAST_TYPES['order_settle']
    content = _render_tpl(_get_custom_template('order_settle') or meta['default_template'], variables)

    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, player.kook_id, card)


def push_escort_dispatch(order):
    """护航/代练派单通知 → 私信陪玩"""
    player = order.player
    if not player.kook_id or not player.kook_bound:
        return

    boss_name = order.boss.nickname or order.boss.username
    order_type_map = {'escort': '护航', 'training': '代练'}
    type_name = order_type_map.get(order.order_type, '订单')

    variables = {
        'boss': boss_name,
        'game': order.project_display,
        'order_no': order.order_no,
        'amount': str(order.total_price),
        'earning': str(order.player_earning),
        'type': type_name,
    }

    meta = BROADCAST_TYPES['escort_dispatch']
    content = _render_tpl(_get_custom_template('escort_dispatch') or meta['default_template'], variables)

    card = _build_card(f'新{type_name}订单', content, meta['color'])
    _async_send(_send_direct_msg, player.kook_id, card)


def push_gift_to_player(gift_order):
    """礼物推送 → 私信收礼人"""
    player = gift_order.player
    if not player.kook_id or not player.kook_bound:
        return

    boss = gift_order.boss
    boss_display = _display_name(
        boss,
        anonymous=boss.anonymous_gift_send,
        anonymous_text='匿名用户',
    )

    variables = {
        'boss': boss_display,
        'gift_name': gift_order.gift.name,
        'quantity': str(gift_order.quantity),
        'amount': str(gift_order.total_price),
        'earning': str(gift_order.player_earning),
    }

    meta = BROADCAST_TYPES['gift_receive']
    content = _render_tpl(_get_custom_template('gift_receive') or meta['default_template'], variables)

    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, player.kook_id, card)


def push_gift_broadcast(gift_order):
    """礼物频道播报"""
    from app.models.broadcast import BroadcastConfig

    configs = BroadcastConfig.query.filter_by(
        broadcast_type='gift', status=True
    ).all()

    if not configs:
        logger.info('[KOOK] 礼物播报跳过: 未找到启用的 gift 播报配置')
        return

    boss = gift_order.boss
    player = gift_order.player
    boss_name = _display_name(
        boss,
        anonymous=boss.anonymous_gift_send,
        anonymous_text='匿名用户',
    )
    player_name = _display_name(
        player,
        anonymous=player.anonymous_gift_recv,
        anonymous_text='匿名陪玩',
        prefer_player_name=True,
    )

    # 构建变量（含 @提及）
    variables = {
        'user': boss_name,
        'player': player_name,
        'gift_name': gift_order.gift.name,
        'quantity': str(gift_order.quantity),
        'amount': str(gift_order.total_price),
        '@user': boss_name if boss.anonymous_gift_send else _mention_or_text(boss, boss_name),
        '@player': player_name if player.anonymous_gift_recv else _mention_or_text(player, player_name),
        '@all': '(met)all(met)',
        '@here': '(met)here(met)',
    }

    meta = BROADCAST_TYPES['gift']
    gift_image_url = _resolve_image_url(getattr(gift_order.gift, 'image', ''))
    gift_image_local = _resolve_local_image_path(getattr(gift_order.gift, 'image', ''))
    gift_image_asset_url = _upload_kook_asset_from_file(gift_image_local)

    def _normalize_legacy_gift_template(template_raw):
        template_trimmed = (template_raw or '').strip()
        if not template_trimmed:
            return ''
        # 兼容历史初始化数据: {user} 送给 {player} 一个<礼物名>！
        # 该值是种子默认文案，不应覆盖“播报管理-礼物播报”模板
        legacy_seed_templates = {
            f'{{user}} 送给 {{player}} 一个{gift_order.gift.name}！',
            f'{{user}} 送给 {{player}} 一个{gift_order.gift.name}!',
        }
        return '' if template_trimmed in legacy_seed_templates else template_raw

    gift_template = _normalize_legacy_gift_template(getattr(gift_order.gift, 'broadcast_template', '') or '')
    crown_template = (getattr(gift_order.gift, 'crown_broadcast_template', '') or '')
    crown_template = crown_template if crown_template.strip() else ''
    is_crown_gift = getattr(gift_order.gift, 'gift_type', '') == 'crown'

    if is_crown_gift and crown_template:
        selected_gift_template = crown_template
        selected_source = 'gift.crown'
    elif gift_template and gift_template.strip():
        selected_gift_template = gift_template
        selected_source = 'gift.custom'
    else:
        selected_gift_template = ''
        selected_source = ''
    sent = False
    for cfg in configs:
        if not cfg.channel_id:
            continue
        cfg_template_raw = cfg.template or ''
        cfg_template = cfg_template_raw if cfg_template_raw.strip() else ''
        use_gift = bool(selected_gift_template and selected_gift_template.strip())
        use_cfg = bool(cfg_template and cfg_template.strip())
        template = selected_gift_template if use_gift else (cfg_template if use_cfg else meta['default_template'])
        source = selected_source if use_gift else ('broadcast.config' if use_cfg else 'broadcast.default')
        logger.info('[KOOK] 礼物播报模板来源: %s (cfg_id=%s)', source, getattr(cfg, 'id', '-'))
        text = _render_tpl(template, variables)
        # 若礼物图已上传为 KOOK 资源，则图片用独立 type=2 消息发送，避免解析成普通链接
        image_url = '' if gift_image_asset_url else (gift_image_url or _resolve_image_url(cfg.image_url))
        card_json = _build_card(meta['title'], text, meta['color'], image_url=image_url)
        _async_send(_send_channel_msg, cfg.channel_id, card_json)
        if gift_image_asset_url:
            _async_send(_send_channel_image, cfg.channel_id, gift_image_asset_url)
        sent = True

    if not sent:
        logger.warning('[KOOK] 礼物播报跳过: gift 配置存在但未填写频道ID')


def push_upgrade_broadcast(user, from_level, to_level):
    """VIP升级播报 → 频道"""
    from app.models.broadcast import BroadcastConfig

    configs = BroadcastConfig.query.filter_by(
        broadcast_type='upgrade', status=True
    ).all()

    if not configs:
        logger.warning('[KOOK] 升级播报跳过: 未找到启用的 upgrade 播报配置')
        return 0

    display_name = _display_name(
        user,
        anonymous=user.anonymous_upgrade,
        anonymous_text='匿名用户',
    )

    variables = {
        'user': display_name,
        'from_level': from_level,
        'level': to_level,
        '@user': display_name if user.anonymous_upgrade else _mention_or_text(user, display_name),
        '@all': '(met)all(met)',
        '@here': '(met)here(met)',
    }

    meta = BROADCAST_TYPES['upgrade']
    level_configs = [
        cfg for cfg in configs
        if str(getattr(cfg, 'target_level', '') or '').strip() == str(to_level or '').strip()
    ]
    generic_configs = [
        cfg for cfg in configs
        if not str(getattr(cfg, 'target_level', '') or '').strip()
    ]

    selected_configs = [cfg for cfg in level_configs if cfg.channel_id]
    source = 'level'
    if not selected_configs:
        if level_configs:
            logger.warning('[KOOK] 升级播报等级专属配置缺少频道ID，回退通用模板 level=%s', to_level)
        selected_configs = [cfg for cfg in generic_configs if cfg.channel_id]
        source = 'generic'

    if not selected_configs:
        logger.warning('[KOOK] 升级播报跳过: 未找到可用频道配置 level=%s', to_level)
        return 0

    sent = 0
    for cfg in selected_configs:
        template = (cfg.template or '').strip() or meta['default_template']
        logger.info(
            '[KOOK] 升级播报模板来源: %s (cfg_id=%s, target_level=%s, to_level=%s)',
            source,
            getattr(cfg, 'id', '-'),
            getattr(cfg, 'target_level', '') or 'ALL',
            to_level,
        )
        text = _render_tpl(template, variables)
        card_json = _build_card(meta['title'], text, meta['color'], image_url=cfg.image_url)
        _async_send(_send_channel_msg, cfg.channel_id, card_json)
        sent += 1

    return sent


def push_recharge_broadcast(user, amount):
    """充值播报 → 频道 (按金额档位匹配)"""
    from decimal import Decimal
    from app.models.broadcast import BroadcastConfig

    amount = Decimal(str(amount))
    configs = BroadcastConfig.query.filter(
        BroadcastConfig.broadcast_type == 'recharge',
        BroadcastConfig.status == True,
        BroadcastConfig.threshold <= amount,
    ).order_by(BroadcastConfig.threshold.desc()).all()

    if not configs:
        return

    # 根据角色取合适的展示名称
    display_name = _display_name(
        user,
        anonymous=user.anonymous_recharge,
        anonymous_text='匿名用户',
        prefer_player_name=(user.role == 'player'),
    )

    role_map = {'god': '老板', 'player': '陪玩', 'staff': '客服', 'admin': '管理员'}
    variables = {
        'user': display_name,
        'amount': str(amount),
        'role': role_map.get(user.role, '用户'),
        '@user': display_name if user.anonymous_recharge else _mention_or_text(user, display_name),
        '@all': '(met)all(met)',
        '@here': '(met)here(met)',
    }

    # 取阈值最大的那一条匹配的配置
    cfg = configs[0]
    if not cfg.channel_id:
        return

    meta = BROADCAST_TYPES['recharge']
    text = _render_tpl(cfg.template or meta['default_template'], variables)
    card_json = _build_card(meta['title'], text, meta['color'], image_url=cfg.image_url)
    _async_send(_send_channel_msg, cfg.channel_id, card_json)


def push_boss_recharge_notice(user, amount, reason='', operator=''):
    """老板充值私信通知（支持播报管理自定义模板）"""
    if not user or not user.has_role('god'):
        return
    if not user.kook_id or not user.kook_bound:
        return

    variables = {
        'user': _display_name(
            user,
            anonymous=user.anonymous_consume,
            anonymous_text='匿名用户',
        ),
        'amount': str(amount),
        'balance': str(user.m_coin + user.m_coin_gift),
        'reason': reason or '-',
        'operator': operator or '-',
    }

    meta = BROADCAST_TYPES['boss_recharge']
    content = _render_tpl(_get_custom_template('boss_recharge') or meta['default_template'], variables)
    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, user.kook_id, card)


def push_boss_consume_notice(user, amount, reason='', operator=''):
    """老板消费私信通知（支持播报管理自定义模板）"""
    if not user or not user.has_role('god'):
        return
    if not user.kook_id or not user.kook_bound:
        return

    variables = {
        'user': _display_name(
            user,
            anonymous=user.anonymous_recharge,
            anonymous_text='匿名用户',
        ),
        'amount': str(amount),
        'balance': str(user.m_coin + user.m_coin_gift),
        'reason': reason or '-',
        'operator': operator or '-',
    }

    meta = BROADCAST_TYPES['boss_consume']
    content = _render_tpl(_get_custom_template('boss_consume') or meta['default_template'], variables)
    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, user.kook_id, card)


def _withdraw_notice_common_vars(withdraw_request, status_text, operator='', remark=''):
    user = withdraw_request.user
    display_name = _fallback_display_name(user, prefer_player_name=True)
    return {
        'user': display_name or '-',
        'request_id': str(withdraw_request.id or '-'),
        'amount': str(withdraw_request.amount or 0),
        'status': status_text,
        'operator': operator or '系统',
        'remark': remark or '-',
        'balance': str(getattr(user, 'm_bean', 0) or 0),
        'frozen': str(getattr(user, 'm_bean_frozen', 0) or 0),
    }


def push_withdraw_submit_notice(withdraw_request):
    """提现提交后私信申请人（支持播报管理模板）"""
    if not _is_broadcast_enabled('withdraw_submit'):
        return

    user = getattr(withdraw_request, 'user', None)
    if not user or not user.kook_id or not user.kook_bound:
        return

    variables = _withdraw_notice_common_vars(withdraw_request, status_text='待审核')
    meta = BROADCAST_TYPES['withdraw_submit']
    content = _render_tpl(_get_custom_template('withdraw_submit') or meta['default_template'], variables)
    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, user.kook_id, card)


def push_withdraw_approved_notice(withdraw_request, operator='', remark=''):
    """提现审核通过后私信申请人（支持播报管理模板）"""
    if not _is_broadcast_enabled('withdraw_approved'):
        return

    user = getattr(withdraw_request, 'user', None)
    if not user or not user.kook_id or not user.kook_bound:
        return

    variables = _withdraw_notice_common_vars(
        withdraw_request,
        status_text='已打款',
        operator=operator,
        remark=remark,
    )
    meta = BROADCAST_TYPES['withdraw_approved']
    content = _render_tpl(_get_custom_template('withdraw_approved') or meta['default_template'], variables)
    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, user.kook_id, card)


def push_withdraw_rejected_notice(withdraw_request, operator='', remark=''):
    """提现审核拒绝后私信申请人（支持播报管理模板）"""
    if not _is_broadcast_enabled('withdraw_rejected'):
        return

    user = getattr(withdraw_request, 'user', None)
    if not user or not user.kook_id or not user.kook_bound:
        return

    variables = _withdraw_notice_common_vars(
        withdraw_request,
        status_text='已拒绝',
        operator=operator,
        remark=remark,
    )
    meta = BROADCAST_TYPES['withdraw_rejected']
    content = _render_tpl(_get_custom_template('withdraw_rejected') or meta['default_template'], variables)
    card = _build_card(meta['title'], content, meta['color'])
    _async_send(_send_direct_msg, user.kook_id, card)


def push_order_refund_notice(order, operator=''):
    """订单退款后私信通知老板和陪玩（支持播报管理自定义模板）"""
    boss = order.boss
    player = order.player
    if not boss and not player:
        return
    boss_enabled = _is_broadcast_enabled('order_refund_boss')
    player_enabled = _is_broadcast_enabled('order_refund_player')

    boss_name = _fallback_display_name(boss)
    player_name = _fallback_display_name(player, prefer_player_name=True)
    common_vars = {
        'boss': boss_name or '-',
        'player': player_name or '-',
        'order_no': str(order.order_no or '-'),
        'game': str(order.project_display or '-'),
        'amount': str(order.total_price or 0),
        'deduct': str(order.player_earning or 0),
        'operator': operator or '系统',
    }

    if boss_enabled and boss and boss.kook_id and boss.kook_bound:
        variables = dict(common_vars)
        variables['balance'] = str((boss.m_coin or 0) + (boss.m_coin_gift or 0))
        meta = BROADCAST_TYPES['order_refund_boss']
        content = _render_tpl(_get_custom_template('order_refund_boss') or meta['default_template'], variables)
        card = _build_card(meta['title'], content, meta['color'])
        _async_send(_send_direct_msg, boss.kook_id, card)

    if player_enabled and player and player.kook_id and player.kook_bound:
        variables = dict(common_vars)
        variables['balance'] = str(player.m_bean or 0)
        meta = BROADCAST_TYPES['order_refund_player']
        content = _render_tpl(_get_custom_template('order_refund_player') or meta['default_template'], variables)
        card = _build_card(meta['title'], content, meta['color'])
        _async_send(_send_direct_msg, player.kook_id, card)


def push_gift_refund_notice(gift_order):
    """礼物退款后私信通知老板和陪玩"""
    boss = gift_order.boss
    player = gift_order.player
    gift_name = gift_order.gift.name if gift_order.gift else '礼物'
    qty = gift_order.quantity
    amount = gift_order.total_price
    deduct = gift_order.player_earning

    boss_name = _display_name(
        boss,
        anonymous=boss.anonymous_gift_send if boss else False,
        anonymous_text='匿名用户',
    )
    player_name = _display_name(
        player,
        anonymous=player.anonymous_gift_recv if player else False,
        anonymous_text='匿名陪玩',
        prefer_player_name=True,
    )

    if boss and boss.kook_id and boss.kook_bound:
        boss_msg = (
            f"**礼物退款通知**\n"
            f"礼物订单: `#{gift_order.id}`\n"
            f"礼物: `{gift_name}` x`{qty}`\n"
            f"退款金额: `{amount}` 嗯呢币\n"
            f"对象陪玩: `{player_name}`"
        )
        _async_send(_send_direct_msg, boss.kook_id, boss_msg)

    if player and player.kook_id and player.kook_bound:
        player_msg = (
            f"**礼物退款通知**\n"
            f"礼物订单: `#{gift_order.id}`\n"
            f"老板: `{boss_name}`\n"
            f"礼物: `{gift_name}` x`{qty}`\n"
            f"扣回收益: `{deduct}` 小猪粮"
        )
        _async_send(_send_direct_msg, player.kook_id, player_msg)


def push_order_delete_notice(order_no, boss=None, player=None, game='', operator=''):
    """订单删除后私信通知老板和陪玩"""
    if boss and boss.kook_id and boss.kook_bound:
        boss_msg = (
            f"**订单已删除通知**\n"
            f"订单号: `{order_no}`\n"
            f"项目: `{game or '-'}`\n"
            f"处理人: `{operator or '系统'}`\n"
            f"说明: 该订单为未付款订单，已从系统删除"
        )
        _async_send(_send_direct_msg, boss.kook_id, boss_msg)

    if player and player.kook_id and player.kook_bound:
        player_msg = (
            f"**订单已删除通知**\n"
            f"订单号: `{order_no}`\n"
            f"项目: `{game or '-'}`\n"
            f"处理人: `{operator or '系统'}`\n"
            f"说明: 该订单为未付款订单，已从系统删除"
        )
        _async_send(_send_direct_msg, player.kook_id, player_msg)


def _get_channel_name(channel_id):
    """获取 KOOK 频道名称"""
    detail, err = _get_channel_detail(channel_id)
    if err or not detail:
        return None
    return detail.get('name', '')


def push_channel_event(kook_user_id, voice_channel_id, event_type='join'):
    """语音频道进出播报"""
    from app.models.broadcast import BroadcastConfig
    from app.models.user import User

    broadcast_type = 'channel_join' if event_type == 'join' else 'channel_leave'
    configs = BroadcastConfig.query.filter_by(
        broadcast_type=broadcast_type, status=True
    ).all()

    if not configs:
        return

    # 查找用户
    user = User.query.filter_by(kook_id=str(kook_user_id)).first()
    user_name = user.nickname or user.username if user else '未知用户'

    # 获取语音频道名称
    channel_name = _get_channel_name(voice_channel_id) or '语音频道'

    variables = {
        'user': user_name,
        'channel': channel_name,
        '@user': _kook_mention(kook_user_id),
    }

    meta = BROADCAST_TYPES[broadcast_type]
    for cfg in configs:
        if not cfg.channel_id:
            continue
        text = _render_tpl(cfg.template or meta['default_template'], variables)
        card_json = _build_card(meta['title'], text, meta['color'], image_url=cfg.image_url)
        _async_send(_send_channel_msg, cfg.channel_id, card_json)


def _weekday_cn(weekday: int) -> str:
    mapping = {
        0: '周一',
        1: '周二',
        2: '周三',
        3: '周四',
        4: '周五',
        5: '周六',
        6: '周日',
    }
    return mapping.get(int(weekday), '周日')


def _parse_hhmm(value: str):
    text = str(value or '').strip()
    m = re.match(r'^(\d{1,2}):(\d{1,2})$', text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _role_mentions_from_csv(raw_ids: str) -> str:
    parts = [p.strip() for p in str(raw_ids or '').split(',') if p.strip()]
    if not parts:
        return ''
    return ' '.join([f'(rol){rid}(rol)' for rid in parts])


def run_birthday_broadcast_job():
    """
    生日播报任务（按北京时间当日触发）。
    支持生日私信和生日频道播报。
    返回成功通知的用户数量。
    """
    from app.extensions import db
    from app.models.broadcast import BroadcastConfig
    from app.models.user import User

    from app.utils.time_utils import to_beijing

    now_bj = to_beijing(datetime.utcnow())
    if not now_bj:
        return 0
    month = now_bj.month
    day = now_bj.day
    current_year = now_bj.year

    dm_enabled = _is_broadcast_enabled('birthday_dm')
    channel_configs = BroadcastConfig.query.filter_by(
        broadcast_type='birthday_channel',
        status=True,
    ).all()

    if not dm_enabled and not channel_configs:
        return 0

    users = User.query.filter(
        User.status == True,
        User.birthday.isnot(None),
    ).all()

    sent = 0
    dm_meta = BROADCAST_TYPES['birthday_dm']
    dm_template = _get_custom_template('birthday_dm') or dm_meta['default_template']
    channel_meta = BROADCAST_TYPES['birthday_channel']
    for user in users:
        if not user.birthday:
            continue
        if user.birthday.month != month or user.birthday.day != day:
            continue
        if int(user.birthday_notified_year or 0) >= current_year:
            continue

        display_name = _fallback_display_name(user, prefer_player_name=user.has_player_tag) or '-'
        variables = {
            'user': display_name,
            'birthday': f'{month:02d}-{day:02d}',
            'year': str(current_year),
            '@user': _mention_or_text(user, display_name),
            '@all': '(met)all(met)',
            '@here': '(met)here(met)',
        }
        sent_any = False

        if dm_enabled and user.kook_id and user.kook_bound:
            text = _render_tpl(dm_template, variables)
            if _send_direct_msg(user.kook_id, _build_card(dm_meta['title'], text, dm_meta['color'])):
                sent_any = True

        for cfg in channel_configs:
            if not cfg.channel_id:
                continue
            channel_template = (cfg.template or '').strip() or channel_meta['default_template']
            text = _render_tpl(channel_template, variables)
            card_json = _build_card(channel_meta['title'], text, channel_meta['color'], image_url=cfg.image_url)
            if _send_channel_msg(cfg.channel_id, card_json):
                sent_any = True

        if sent_any:
            user.birthday_notified_year = current_year
            sent += 1

    if sent > 0:
        db.session.commit()
    return sent


def run_birthday_dm_job():
    """兼容旧调用，统一转到生日播报任务。"""
    return run_birthday_broadcast_job()


def run_weekly_withdraw_reminder_job():
    """
    周定时提现提醒任务（按北京时间匹配周几+时间）。
    返回成功发送数量。
    """
    from app.models.broadcast import BroadcastConfig
    from app.extensions import db

    from app.utils.time_utils import to_beijing

    now_bj = to_beijing(datetime.utcnow())
    if not now_bj:
        return 0
    weekday = now_bj.weekday()  # 0=Mon
    hm = (now_bj.hour, now_bj.minute)

    configs = BroadcastConfig.query.filter_by(
        broadcast_type='weekly_withdraw_reminder',
        status=True,
    ).all()
    if not configs:
        return 0

    meta = BROADCAST_TYPES['weekly_withdraw_reminder']
    sent = 0
    for cfg in configs:
        if not cfg.channel_id:
            continue

        cfg_weekday = int(cfg.schedule_weekday if cfg.schedule_weekday is not None else 6)
        if cfg_weekday != weekday:
            continue

        parsed = _parse_hhmm(cfg.schedule_time or '12:00')
        if not parsed:
            parsed = (12, 0)
        if parsed != hm:
            continue

        # 防重复：同一天同配置只发送一次
        if cfg.last_sent_at:
            from app.utils.time_utils import to_beijing
            last_bj = to_beijing(cfg.last_sent_at)
            if not last_bj:
                last_bj = cfg.last_sent_at
            if (
                last_bj.year == now_bj.year and
                last_bj.month == now_bj.month and
                last_bj.day == now_bj.day
            ):
                continue

        roles = _role_mentions_from_csv(cfg.mention_role_ids or '')
        variables = {
            'weekday': _weekday_cn(cfg_weekday),
            'time': f'{parsed[0]:02d}:{parsed[1]:02d}',
            'roles': roles or '(met)all(met)',
            '@all': '(met)all(met)',
            '@here': '(met)here(met)',
        }
        text = _render_tpl((cfg.template or meta['default_template']), variables)
        ok = _send_channel_msg(cfg.channel_id, _build_card(meta['title'], text, meta['color'], image_url=cfg.image_url))
        if ok:
            cfg.last_sent_at = datetime.utcnow()
            sent += 1

    if sent > 0:
        db.session.commit()
    return sent


def send_test_message(channel_id, title, content, msg_type='success'):
    """Bot 调测 — 发送测试消息到指定频道"""
    color_map = {
        'success': '#10B981',
        'warning': '#F59E0B',
        'error': '#EF4444',
        'normal': '#7C3AED',
    }
    color = color_map.get(msg_type, '#7C3AED')
    card_json = _build_card(title or '调测消息', content, color)
    return _send_channel_msg(channel_id, card_json)
