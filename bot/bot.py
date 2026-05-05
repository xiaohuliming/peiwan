import os
import sys
import logging
import asyncio
import random
import json
import re
import uuid
from decimal import Decimal
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
import requests
from khl import Bot, Message, MessageTypes, EventTypes, Event
from khl.channel import PublicTextChannel
from khl.user import User as KhlUser

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.order import Order
from app.models.lottery import Lottery
from app.models.finance import WithdrawRequest, CommissionLog, BalanceLog

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask App (禁止在 Bot 进程中再次拉起后台任务，避免递归启动)
app = create_app(start_background_tasks=False)

# Initialize KOOK Bot
bot = Bot(token=app.config.get('KOOK_TOKEN', ''))

STORY_BUTTON_PREFIX = 'story_continue'
BLACKJACK_BUTTON_PREFIX = 'blackjack_action'


def _kook_user_tag(author):
    """返回 KOOK 显示名: username#identify_num"""
    username = (getattr(author, 'username', '') or '').strip()
    identify_num = (getattr(author, 'identify_num', '') or '').strip()
    if username and identify_num:
        return f'{username}#{identify_num}'
    return username or str(getattr(author, 'id', ''))


def _generate_unique_username(base):
    """生成不重复用户名"""
    username = base[:50]
    if not User.query.filter_by(username=username).first():
        return username

    idx = 1
    while idx < 1000:
        suffix = f"_{idx}"
        candidate = f"{base[:50-len(suffix)]}{suffix}"
        if not User.query.filter_by(username=candidate).first():
            return candidate
        idx += 1
    return f"{base[:48]}_x"


def _extract_msg_channel_id(msg: Message) -> str:
    """提取命令消息所在频道 ID（优先公共频道）"""
    try:
        ch = getattr(getattr(msg, 'ctx', None), 'channel', None)
        if ch and getattr(ch, 'id', None):
            return str(ch.id)
    except Exception:
        pass

    for attr in ('channel_id', 'target_id'):
        v = getattr(msg, attr, None)
        if v:
            return str(v)
    return ''


def _extract_msg_guild_id(msg: Message) -> str:
    """提取命令消息所在服务器 ID（公共频道消息才有）。"""
    try:
        gd = getattr(getattr(msg, 'ctx', None), 'guild', None)
        if gd and getattr(gd, 'id', None):
            return str(gd.id)
    except Exception:
        pass

    try:
        extra = getattr(msg, 'extra', {}) or {}
        gid = extra.get('guild_id') if isinstance(extra, dict) else ''
        if gid:
            return str(gid)
    except Exception:
        pass
    return ''


def _is_private_message(msg: Message) -> bool:
    """判断是否 KOOK 私信消息。"""
    try:
        channel_type = getattr(msg, 'channel_type', None)
        value = getattr(channel_type, 'value', channel_type)
        return str(value or '').upper() == 'PERSON'
    except Exception:
        return False


def get_or_create_user_by_kook(author):
    """
    根据 KOOK 作者信息直接识别用户，不再强依赖 /bind：
    1. 有 kook_id 账号则直接使用（自动补全 kook_username / kook_bound）
    2. 没有则自动创建 GOD 账号
    """
    kook_id = str(author.id)
    kook_username = _kook_user_tag(author)

    users = User.query.filter_by(kook_id=kook_id).order_by(User.kook_bound.desc(), User.id.asc()).all()
    user = users[0] if users else None

    # 获取 KOOK 头像
    kook_avatar = getattr(author, 'avatar', None) or ''

    if user:
        changed = False
        if user.kook_username != kook_username:
            user.kook_username = kook_username
            changed = True
        if not user.kook_bound:
            user.kook_bound = True
            changed = True
        # 自动更新头像（每次登录都同步最新头像）
        if kook_avatar and user.avatar != kook_avatar:
            user.avatar = kook_avatar
            changed = True
        if changed:
            db.session.commit()
        return user

    # 自动创建 KOOK 用户
    username = _generate_unique_username(f'kook_{kook_id}')
    user = User(
        username=username,
        role='god',
        nickname=kook_username or username,
        kook_id=kook_id,
        kook_username=kook_username,
        kook_bound=True,
        avatar=kook_avatar or None,
        status=True,
        register_type='kook',
    )
    # 新注册用户默认身份标签：老板 + 陪玩（主角色保持 god）
    user.tag_list = ['老板', '陪玩']
    user.set_password('123456789')
    db.session.add(user)
    db.session.commit()
    return user


def _transfer_bean_to_coin(user: User, amount: Decimal):
    """将小猪金(小猪粮, m_bean)按 1:1 转为嗯呢币(m_coin)。"""
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        return False, '转换金额必须大于 0'

    bean_available = Decimal(str(user.m_bean or 0))
    if bean_available < amount:
        return False, f'小猪金余额不足，当前可转: {bean_available}'

    user.m_bean -= amount

    user.m_coin += amount

    clog = CommissionLog(
        user_id=user.id,
        change_type='exchange_out',
        amount=-amount,
        balance_after=user.m_bean,
        reason='KOOK /转换 小猪金转出',
    )
    blog = BalanceLog(
        user_id=user.id,
        change_type='exchange_in',
        amount=amount,
        balance_after=user.m_coin + user.m_coin_gift,
        reason='KOOK /转换 转入嗯呢币',
    )
    db.session.add(clog)
    db.session.add(blog)
    return True, None


# ─── 互动抽奖（命令版）──────────────────────────────────────────────
_interactive_tasks = {}       # lottery_id -> asyncio.Task
_withdraw_pending_uploads = {}  # kook_user_id -> {"amount":"100.00","step":"wechat|alipay","wechat_image":"","created_at":ts}
_WITHDRAW_UPLOAD_TTL_SECONDS = 10 * 60


def _is_command_message(msg: Message) -> bool:
    content = str(getattr(msg, 'content', '') or '').strip()
    return content.startswith('/')


def _is_bot_author(msg: Message) -> bool:
    try:
        return bool(getattr(getattr(msg, 'author', None), 'bot', False))
    except Exception:
        return False


def _cleanup_expired_withdraw_pending():
    now = time.time()
    expired = [
        uid for uid, item in _withdraw_pending_uploads.items()
        if now - float(item.get('created_at') or 0) > _WITHDRAW_UPLOAD_TTL_SECONDS
    ]
    for uid in expired:
        _withdraw_pending_uploads.pop(uid, None)


def _withdraw_gui_url() -> str:
    site = (app.config.get('SITE_URL') or '').strip().rstrip('/')
    if not site:
        site = 'http://127.0.0.1:5000'
    return f'{site}/finance/withdraw'


def _build_story_choice_card(text: str, choices=None, owner_id: str = ''):
    choices = [str(choice or '').strip() for choice in (choices or []) if str(choice or '').strip()]
    if not choices:
        return None
    labels = ('A', 'B', 'C')
    choice_lines = [
        f"{labels[index]}. {choice}"
        for index, choice in enumerate(choices[:3])
    ]

    modules = [
        {"type": "header", "text": {"type": "plain-text", "content": "灰区档案"}},
        {
            "type": "section",
            "text": {"type": "kmarkdown", "content": str(text or '').strip() or "剧情正在等待你的行动。"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "kmarkdown", "content": "**可选行动**\n" + "\n".join(choice_lines)},
        },
        {
            "type": "context",
            "elements": [
                {"type": "kmarkdown", "content": "点击选项可直接推进剧情；自由输入请使用 `/游戏 剧情 继续 你的行动`。"}
            ],
        },
    ]

    elements = []
    for index, _choice in enumerate(choices[:3], start=1):
        label = labels[index - 1]
        elements.append({
            "type": "button",
            "theme": "secondary",
            "value": f"{STORY_BUTTON_PREFIX}|{owner_id}|{index}",
            "click": "return-val",
            "text": {"type": "plain-text", "content": label},
        })
    modules.append({"type": "action-group", "elements": elements})
    return [{"type": "card", "theme": "secondary", "size": "lg", "modules": modules}]


async def _reply_story_result(msg: Message, result_or_text, owner_id: str):
    if isinstance(result_or_text, dict):
        choices = result_or_text.get('choices') or []
        text = (result_or_text.get('visible_text') if choices else None) or result_or_text.get('message') or ''
    else:
        text = str(result_or_text or '')
        choices = []

    card = _build_story_choice_card(text, choices, owner_id)
    if card:
        try:
            await msg.reply(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
            return
        except Exception:
            logger.exception('剧情选项卡片发送失败，降级 KMD')
    await msg.reply(text, type=MessageTypes.KMD)


def _event_body_value(body, *keys):
    if not isinstance(body, dict):
        return ''
    for key in keys:
        value = body.get(key)
        if value not in (None, ''):
            return value
    return ''


def _nested_event_body_value(body, outer_key, inner_key):
    if not isinstance(body, dict):
        return ''
    item = body.get(outer_key)
    if isinstance(item, dict):
        return item.get(inner_key) or ''
    return ''


def _parse_story_button_value(value):
    parts = str(value or '').split('|')
    if len(parts) != 3 or parts[0] != STORY_BUTTON_PREFIX:
        return None
    owner_id = parts[1].strip()
    choice_index = parts[2].strip()
    if not choice_index.isdigit():
        return None
    return {'owner_id': owner_id, 'choice': choice_index}


def _parse_blackjack_button_value(value):
    parts = str(value or '').split('|')
    if len(parts) != 4 or parts[0] != BLACKJACK_BUTTON_PREFIX:
        return None
    owner_id = parts[1].strip()
    channel_id = parts[2].strip()
    action = parts[3].strip().lower()
    if action not in {'hit', 'stand'}:
        return None
    return {'owner_id': owner_id, 'channel_id': channel_id, 'action': action}


def _button_event_user_id(event: Event) -> str:
    body = getattr(event, 'body', {}) or {}
    return str(
        _event_body_value(body, 'user_id', 'author_id')
        or _nested_event_body_value(body, 'user', 'id')
        or _nested_event_body_value(body, 'user_info', 'id')
        or getattr(event, 'author_id', '')
        or ''
    )


def _button_event_target_id(event: Event) -> str:
    body = getattr(event, 'body', {}) or {}
    return str(
        _event_body_value(body, 'target_id', 'channel_id')
        or getattr(event, 'target_id', '')
        or ''
    )


def _button_event_channel_type(event: Event) -> str:
    body = getattr(event, 'body', {}) or {}
    return str(
        _event_body_value(body, 'channel_type', 'channel_type_name')
        or getattr(event, '_channel_type', '')
        or ''
    ).upper()


def _minigame_event_channel_id(event: Event, fallback_channel_id: str = '') -> str:
    # 按钮 value 里 baked 的 channel_id 就是开局保存 session 时用的 ID,优先用它,确保 session 一定能命中。
    if fallback_channel_id:
        return str(fallback_channel_id)
    if _button_event_channel_type(event) == 'PERSON':
        return 'dm'
    return str(_button_event_target_id(event) or 'unknown')


async def _send_story_event_message(
    bot_obj: Bot,
    event: Event,
    result_or_text,
    owner_id: str = '',
    temp_target_id: str = '',
):
    if isinstance(result_or_text, dict):
        choices = result_or_text.get('choices') or []
        text = (result_or_text.get('visible_text') if choices else None) or result_or_text.get('message') or ''
    else:
        choices = []
        text = str(result_or_text or '')

    card = _build_story_choice_card(text, choices, owner_id)
    channel_type = _button_event_channel_type(event)
    target_id = _button_event_target_id(event)

    try:
        if channel_type == 'PERSON':
            target_user = KhlUser(id=owner_id or temp_target_id or _button_event_user_id(event), _gate_=bot_obj.client.gate)
            if card:
                await target_user.send(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
            else:
                await target_user.send(text, type=MessageTypes.KMD)
            return

        if target_id:
            channel = PublicTextChannel(id=target_id, _gate_=bot_obj.client.gate)
            if card:
                await channel.send(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD, temp_target_id=temp_target_id)
            else:
                await channel.send(text, type=MessageTypes.KMD, temp_target_id=temp_target_id)
            return

        fallback_user_id = temp_target_id or owner_id or _button_event_user_id(event)
        if fallback_user_id:
            target_user = KhlUser(id=fallback_user_id, _gate_=bot_obj.client.gate)
            if card:
                await target_user.send(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
            else:
                await target_user.send(text, type=MessageTypes.KMD)
    except Exception:
        logger.exception('剧情按钮事件回复失败')


async def _send_minigame_event_result(
    bot_obj: Bot,
    event: Event,
    result,
    owner_id: str = '',
    channel_id: str = '',
    temp_target_id: str = '',
):
    message = (result or {}).get('message') or '小游戏暂无响应。'
    card = None
    if _is_active_blackjack_result(result):
        card = _build_blackjack_action_card(message, owner_id, channel_id)
    channel_type = _button_event_channel_type(event)
    target_id = _button_event_target_id(event)
    content_type = MessageTypes.CARD if card else MessageTypes.KMD
    content = json.dumps(card, ensure_ascii=False) if card else message

    try:
        if channel_type == 'PERSON':
            target_user = KhlUser(id=owner_id or temp_target_id or _button_event_user_id(event), _gate_=bot_obj.client.gate)
            await target_user.send(content, type=content_type)
            return

        send_target_id = channel_id if channel_id and channel_id not in {'dm', 'unknown'} else target_id
        if send_target_id:
            channel = PublicTextChannel(id=send_target_id, _gate_=bot_obj.client.gate)
            if temp_target_id:
                await channel.send(content, type=content_type, temp_target_id=temp_target_id)
            else:
                await channel.send(content, type=content_type)
            return

        fallback_user_id = temp_target_id or owner_id or _button_event_user_id(event)
        if fallback_user_id:
            target_user = KhlUser(id=fallback_user_id, _gate_=bot_obj.client.gate)
            await target_user.send(content, type=content_type)
    except Exception:
        logger.exception('小游戏按钮事件回复失败')


async def _reply_withdraw_prompt(msg: Message, text: str):
    """提现提示消息：优先卡片+按钮，失败时回退纯文本链接。"""
    url = _withdraw_gui_url()
    card = [
        {
            "type": "card",
            "theme": "secondary",
            "size": "lg",
            "modules": [
                {"type": "section", "text": {"type": "kmarkdown", "content": str(text or '')}},
                {
                    "type": "action-group",
                    "elements": [
                        {
                            "type": "button",
                            "theme": "primary",
                            "value": url,
                            "click": "link",
                            "text": {"type": "plain-text", "content": "前往网页提现"}
                        }
                    ]
                }
            ]
        }
    ]
    try:
        await msg.reply(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
    except Exception:
        await msg.reply(f'{text}\n前往网页提现: {url}')


def _extract_image_url_from_message(msg: Message) -> str:
    """从消息中提取图片 URL（兼容 KOOK 图片消息 / KMD 图片语法）。"""
    def _pick_url(obj):
        if isinstance(obj, dict):
            for k in ('url', 'src', 'download_url', 'file_url', 'content'):
                v = obj.get(k)
                if isinstance(v, str) and v.startswith(('http://', 'https://')):
                    return v
        else:
            for k in ('url', 'src', 'download_url', 'file_url', 'content'):
                v = getattr(obj, k, None)
                if isinstance(v, str) and v.startswith(('http://', 'https://')):
                    return v
        return ''

    attachments = getattr(msg, 'attachments', None)
    if isinstance(attachments, (list, tuple)):
        for item in attachments:
            u = _pick_url(item)
            if u:
                return u
    elif attachments:
        u = _pick_url(attachments)
        if u:
            return u

    extra = getattr(msg, 'extra', None)
    if isinstance(extra, dict):
        for key in ('attachments', 'attachment'):
            data = extra.get(key)
            if isinstance(data, (list, tuple)):
                for item in data:
                    u = _pick_url(item)
                    if u:
                        return u
            elif data:
                u = _pick_url(data)
                if u:
                    return u

    content = str(getattr(msg, 'content', '') or '')
    m = re.search(r'\(img\)(https?://[^()\s]+)\(img\)', content, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    m = re.search(r'\(file\)(https?://[^()\s]+)\(file\)', content, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    m = re.search(r'https?://[^\s]+', content)
    if m:
        return m.group(0)
    return ''


def _guess_image_ext(image_url: str, content_type: str, data: bytes = b'') -> str:
    ct = (content_type or '').split(';', 1)[0].strip().lower()
    ct_map = {
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/jpg': 'jpg',
        'image/gif': 'gif',
        'image/webp': 'webp',
        'image/bmp': 'bmp',
    }
    if ct in ct_map:
        return ct_map[ct]
    path = urlparse(image_url).path or ''
    ext = os.path.splitext(path)[1].lower().lstrip('.')
    if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'):
        return 'jpg' if ext == 'jpeg' else ext
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith((b'\xff\xd8\xff',)):
        return 'jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if data.startswith((b'BM',)):
        return 'bmp'
    if data.startswith((b'RIFF',)) and data[8:12] == b'WEBP':
        return 'webp'
    return 'png'


def _looks_like_image_bytes(data: bytes) -> bool:
    if not data:
        return False
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return True
    if data.startswith((b'\xff\xd8\xff',)):
        return True
    if data.startswith((b'GIF87a', b'GIF89a')):
        return True
    if data.startswith((b'BM',)):
        return True
    if data.startswith((b'RIFF',)) and data[8:12] == b'WEBP':
        return True
    return False


def _get_recent_withdrawal_within_3_days(user_id: int):
    """仅 pending/paid 计入限制，rejected/failed 不限制"""
    window_start = datetime.utcnow() - timedelta(days=3)
    return (
        WithdrawRequest.query
        .filter(WithdrawRequest.user_id == user_id)
        .filter(WithdrawRequest.created_at >= window_start)
        .filter(WithdrawRequest.status.in_(['pending', 'paid']))
        .order_by(WithdrawRequest.created_at.desc())
        .first()
    )


def _parse_dual_payment_images(payment_method: str, payment_image: str):
    """兼容历史单码与新双码存储，返回(wechat_image, alipay_image)。"""
    raw = str(payment_image or '').strip()
    if not raw:
        return '', ''
    if '|' in raw:
        left, right = raw.split('|', 1)
        return left.strip(), right.strip()
    method = str(payment_method or '').strip().lower()
    if method == 'alipay':
        return '', raw
    return raw, ''


def _get_saved_withdraw_payment_info(user_id: int):
    """获取用户最近一次保存的收款码信息（双码优先）。"""
    records = (
        WithdrawRequest.query
        .filter(WithdrawRequest.user_id == user_id)
        .order_by(WithdrawRequest.created_at.desc())
        .limit(20)
        .all()
    )
    for wr in records:
        wx_img, ali_img = _parse_dual_payment_images(getattr(wr, 'payment_method', ''), getattr(wr, 'payment_image', ''))
        if wx_img and ali_img:
            return {
                'wechat_image': wx_img,
                'alipay_image': ali_img,
                'payment_account': str(getattr(wr, 'payment_account', '') or '').strip(),
            }
    return None


def _create_withdraw_request(user, amount: Decimal, payment_account: str, payment_image: str):
    """创建提现单并冻结余额。"""
    recent_wr = _get_recent_withdrawal_within_3_days(user.id)
    if recent_wr:
        next_time = (recent_wr.created_at + timedelta(days=3)).strftime('%Y-%m-%d %H:%M')
        raise ValueError(f'限制：3天内仅可提交1次提现申请。你可在 {next_time} 后再次申请。')

    if user.m_bean < amount:
        raise ValueError(f'余额不足，当前可提现: **{user.m_bean}** 小猪粮。')

    user.m_bean -= amount
    user.m_bean_frozen += amount

    wr = WithdrawRequest(
        user_id=user.id,
        amount=amount,
        payment_method='wechat+alipay',
        payment_account=payment_account or '双码收款',
        payment_image=payment_image,
        status='pending',
    )
    db.session.add(wr)
    db.session.flush()

    cl = CommissionLog(
        user_id=user.id,
        change_type='withdraw_freeze',
        amount=-amount,
        balance_after=user.m_bean,
        reason=f'提现申请冻结 #{wr.id}'
    )
    db.session.add(cl)
    return wr


def _download_payment_image(image_url: str):
    """下载收款码图片到 static/uploads/payment_codes，返回相对路径。"""
    try:
        resp = requests.get(str(image_url), timeout=20)
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')

        data = resp.content or b''
        if not data:
            return None, '图片内容为空'
        if len(data) > 10 * 1024 * 1024:
            return None, '图片过大，请使用 10MB 以内的收款码图片'

        low_ct = content_type.lower()
        ext_from_url = os.path.splitext((urlparse(image_url).path or '').lower())[1]
        is_image_ct = 'image' in low_ct
        is_image_ext = ext_from_url in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
        if not (is_image_ct or is_image_ext or _looks_like_image_bytes(data)):
            return None, f'上传内容不是图片，Content-Type={content_type or "unknown"}'

        ext = _guess_image_ext(image_url, content_type, data)
        filename = f'{uuid.uuid4().hex}.{ext}'
        upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'payment_codes')
        os.makedirs(upload_folder, exist_ok=True)
        full_path = os.path.join(upload_folder, filename)
        with open(full_path, 'wb') as fp:
            fp.write(data)
        return f'uploads/payment_codes/{filename}', None
    except Exception as e:
        logger.error(f'下载收款码失败: {e}')
        return None, str(e)


async def _try_complete_withdraw_with_payment_image(msg: Message) -> bool:
    """若用户存在待提交提现，处理微信/支付宝收款码上传并最终提交申请。"""
    _cleanup_expired_withdraw_pending()
    author = getattr(msg, 'author', None)
    if not author:
        return False

    kook_id = str(getattr(author, 'id', '') or '')
    if not kook_id:
        return False

    pending = _withdraw_pending_uploads.get(kook_id)
    if not pending:
        return False

    step = str(pending.get('step') or 'wechat')
    image_url = _extract_image_url_from_message(msg)
    if not image_url:
        # 保留其他命令正常处理；普通文字则提示上传图片
        if _is_command_message(msg):
            return False
        if step == 'alipay':
            await _reply_withdraw_prompt(msg, '请上传**支付宝收款码**图片（直接上传图片即可）。')
        else:
            await _reply_withdraw_prompt(msg, '请上传**微信收款码**图片（直接上传图片即可）。')
        return True

    with app.app_context():
        user = get_or_create_user_by_kook(author)
        try:
            amount = Decimal(str(pending.get('amount', '0')))
        except Exception:
            amount = Decimal('0')

        if amount <= 0:
            _withdraw_pending_uploads.pop(kook_id, None)
            await msg.reply('提现金额无效，请重新发起 `/提现 金额`。')
            return True

        if not user.has_player_tag:
            _withdraw_pending_uploads.pop(kook_id, None)
            await msg.reply('仅拥有陪玩身份的用户可申请提现。')
            return True

        recent_wr = _get_recent_withdrawal_within_3_days(user.id)
        if recent_wr:
            _withdraw_pending_uploads.pop(kook_id, None)
            next_time = (recent_wr.created_at + timedelta(days=3)).strftime('%Y-%m-%d %H:%M')
            await msg.reply(f'限制：3天内仅可提交1次提现申请。你可在 {next_time} 后再次申请。')
            return True

        if user.m_bean < amount:
            _withdraw_pending_uploads.pop(kook_id, None)
            await msg.reply(f'余额不足，当前可提现: **{user.m_bean}** 小猪粮。请重新发起 `/提现 金额`。')
            return True

        payment_image_path, err = _download_payment_image(image_url)
        if err or not payment_image_path:
            await msg.reply(f'收款码上传失败：{err or "未知错误"}\n请重新发送清晰的收款码图片。')
            return True

        # 第一步：微信收款码
        if step != 'alipay':
            pending['wechat_image'] = payment_image_path
            pending['step'] = 'alipay'
            pending['created_at'] = time.time()
            _withdraw_pending_uploads[kook_id] = pending
            await _reply_withdraw_prompt(msg, '微信收款码已记录。\n请继续上传**支付宝收款码**图片。')
            return True

        # 第二步：支付宝收款码 → 完成提现
        wechat_image_path = str(pending.get('wechat_image') or '').strip()
        alipay_image_path = payment_image_path
        if not wechat_image_path:
            pending['step'] = 'wechat'
            _withdraw_pending_uploads[kook_id] = pending
            await _reply_withdraw_prompt(msg, '未检测到微信收款码，请先上传**微信收款码**。')
            return True

        try:
            saved_info = _get_saved_withdraw_payment_info(user.id) or {}
            payment_account = str(saved_info.get('payment_account') or '').strip() or '机器人提现(双码)'
            wr = _create_withdraw_request(
                user=user,
                amount=amount,
                payment_account=payment_account,
                payment_image=f'{wechat_image_path}|{alipay_image_path}',
            )
            db.session.commit()
            try:
                from app.services.kook_service import push_withdraw_submit_notice
                push_withdraw_submit_notice(wr)
            except Exception as e:
                logger.warning(f'提现提交私信通知失败: {e}')
            _withdraw_pending_uploads.pop(kook_id, None)

            await msg.reply(
                f"**提现申请已提交**\n"
                f"提现金额: **{amount}** 小猪粮\n"
                f"收款码: 微信 + 支付宝（均已上传）\n"
                f"剩余可用: **{user.m_bean}** 小猪粮\n"
                f"---\n"
                f"请等待管理员审核"
            )
            return True
        except ValueError as e:
            db.session.rollback()
            _withdraw_pending_uploads.pop(kook_id, None)
            await msg.reply(str(e))
            return True
        except Exception as e:
            logger.error(f"Error withdraw after dual image upload: {e}")
            db.session.rollback()
            await msg.reply('提现失败，请联系管理员')
            return True


async def _auto_draw_interactive_lottery(lottery_id: int, delay_seconds: float):
    """到期开奖时间后尝试自动开奖（Bot 独立运行时兜底）。"""
    try:
        await asyncio.sleep(max(0, delay_seconds))
        with app.app_context():
            from app.services.lottery_service import draw_lottery
            lottery = Lottery.query.get(lottery_id)
            if not lottery or not lottery.is_interactive or lottery.status != 'published':
                return
            ok, msg = draw_lottery(lottery)
            if ok:
                logger.info(f'互动抽奖自动开奖成功 #{lottery_id}: {msg}')
            else:
                logger.warning(f'互动抽奖自动开奖失败 #{lottery_id}: {msg}')
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.error(f'互动抽奖自动开奖任务异常: {e}')
    finally:
        _interactive_tasks.pop(lottery_id, None)


@bot.command(name='ping')
async def ping(msg: Message):
    await msg.reply('pong')


@bot.command(name='hello')
async def hello(msg: Message):
    await msg.reply('Hello! I am 嗯呢呗电竞机器人.')


@bot.command(name='bind')
async def bind(msg: Message, token: str = ''):
    """
    绑定KOOK账号
    用法:
    - /bind            (自动按KOOK ID匹配绑定)
    - /bind <用户编码> (手动编码绑定)
    """
    kook_id = str(msg.author.id)
    kook_username = _kook_user_tag(msg.author)

    with app.app_context():
        # 已改为自动识别，/bind 默认仅展示当前识别结果
        if not token:
            user = get_or_create_user_by_kook(msg.author)
            await msg.reply(
                f'已自动识别你的KOOK账号，无需手动绑定。\n'
                f'当前账号: **{user.nickname or user.username}**\n'
                f'编码: `{user.user_code}`'
            )
            return

        # 若当前 KOOK 已绑定，直接返回结果
        bound_user = User.query.filter_by(kook_id=kook_id, kook_bound=True).first()
        if bound_user:
            await msg.reply(
                f'当前KOOK已绑定账号: **{bound_user.nickname or bound_user.username}**\n'
                f'编码: `{bound_user.user_code}`'
            )
            return

        user = None
        token = (token or '').strip()

        if token:
            # 手动编码绑定
            user = User.query.filter_by(user_code=token).first()
            if not user:
                await msg.reply('无效的用户编码')
                return
        else:
            # 自动 KOOK ID 绑定
            candidates = User.query.filter_by(kook_id=kook_id).all()
            if len(candidates) == 1:
                user = candidates[0]
            elif len(candidates) > 1:
                await msg.reply('检测到多个同KOOK ID账号，请使用 `/bind 用户编码` 精确绑定')
                return
            else:
                await msg.reply(
                    '已自动读取你的KOOK ID，但未找到可绑定账号。\n'
                    '请使用 `/bind 用户编码` 绑定，或让管理员先在后台填写你的 KOOK ID。'
                )
                return

        if user.kook_bound:
            await msg.reply('该账号已绑定KOOK用户')
            return

        try:
            user.kook_id = kook_id
            user.kook_username = kook_username
            user.kook_bound = True
            # 同步头像
            kook_avatar = getattr(msg.author, 'avatar', None)
            if kook_avatar:
                user.avatar = kook_avatar
            db.session.commit()

            await msg.reply(
                f"**绑定成功**\n"
                f"KOOK账号已绑定到 **{user.nickname or user.username}**\n"
                f"角色: {user.role_name}\n"
                f"编码: `{user.user_code}`"
            )
        except Exception as e:
            logger.error(f"Error binding user: {e}")
            db.session.rollback()
            await msg.reply('绑定失败，请联系管理员')


@bot.command(name='钱包')
async def wallet(msg: Message):
    """查询钱包信息"""
    with app.app_context():
        user = get_or_create_user_by_kook(msg.author)

        display_name = user.player_nickname or user.nickname or user.username
        total_coin = user.m_coin + user.m_coin_gift

        modules = [
            {"type": "header", "text": {"type": "plain-text", "content": f"💳 {display_name} 的钱包"}},
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "kmarkdown",
                    "content": (
                        "💰 **嗯呢币**\n"
                        f"充值余额　**{user.m_coin}**\n"
                        f"赠　　金　**{user.m_coin_gift}**\n"
                        f"合计可用　**{total_coin}** 嗯呢币"
                    ),
                },
            },
        ]

        # ── 小猪粮（陪玩可见，或有余额时可见）──
        has_bean = user.m_bean > 0 or user.m_bean_frozen > 0
        if user.has_player_tag or has_bean:
            total_bean = user.m_bean + user.m_bean_frozen
            modules.append({"type": "divider"})
            modules.append({
                "type": "section",
                "text": {
                    "type": "kmarkdown",
                    "content": (
                        "🐷 **小猪粮（收益）**\n"
                        f"可 提 现　**{user.m_bean}**\n"
                        f"冻 结 中　**{user.m_bean_frozen}**\n"
                        f"合　　计　**{total_bean}** 小猪粮"
                    ),
                },
            })

        # ── 操作提示 ──
        if user.has_player_tag:
            modules.append({"type": "divider"})
            modules.append({
                "type": "context",
                "elements": [
                    {
                        "type": "kmarkdown",
                        "content": "📌 `/提现 金额` 申请提现　·　`/转换 金额` 小猪粮转嗯呢币",
                    }
                ],
            })

        card = [{"type": "card", "theme": "info", "size": "lg", "modules": modules}]
        try:
            await msg.reply(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
        except Exception:
            # fallback 纯文本
            fallback = f"{display_name} 的钱包\n嗯呢币: {user.m_coin} | 赠金: {user.m_coin_gift} | 合计: {total_coin}\n小猪粮: {user.m_bean} | 冻结: {user.m_bean_frozen}"
            await msg.reply(fallback)


@bot.command(name='提现')
async def withdraw(msg: Message, amount_str: str = ''):
    """
    申请提现小猪粮
    用法: /提现 100（随后依次上传微信/支付宝收款码）
    """
    with app.app_context():
        user = get_or_create_user_by_kook(msg.author)

        if not user.has_player_tag:
            await msg.reply('仅拥有陪玩身份的用户可申请提现')
            return

        if not amount_str:
            await _reply_withdraw_prompt(
                msg,
                f"请输入提现金额: `/提现 金额`\n"
                f"当前可提现: **{user.m_bean}** 小猪粮\n"
                f"首次需要上传微信+支付宝收款码；后续可复用已保存收款码。"
            )
            return

        _cleanup_expired_withdraw_pending()

        try:
            amount = Decimal(amount_str)
        except Exception:
            await msg.reply('金额格式不正确')
            return

        if amount <= 0:
            await msg.reply('金额必须大于0')
            return

        if user.m_bean < amount:
            await msg.reply(f'余额不足，当前可提现: **{user.m_bean}** 小猪粮')
            return

        recent_wr = _get_recent_withdrawal_within_3_days(user.id)
        if recent_wr:
            next_time = (recent_wr.created_at + timedelta(days=3)).strftime('%Y-%m-%d %H:%M')
            await msg.reply(f'限制：3天内仅可提交1次提现申请。你可在 {next_time} 后再次申请。')
            return

        # 若已有历史双码，直接复用提交（无需重复上传）
        saved_info = _get_saved_withdraw_payment_info(user.id)
        if saved_info and saved_info.get('wechat_image') and saved_info.get('alipay_image'):
            try:
                wr = _create_withdraw_request(
                    user=user,
                    amount=amount,
                    payment_account=str(saved_info.get('payment_account') or '双码收款'),
                    payment_image=f"{saved_info['wechat_image']}|{saved_info['alipay_image']}",
                )
                db.session.commit()
                try:
                    from app.services.kook_service import push_withdraw_submit_notice
                    push_withdraw_submit_notice(wr)
                except Exception as e:
                    logger.warning(f'提现提交私信通知失败: {e}')
                await msg.reply(
                    f"**提现申请已提交**\n"
                    f"提现金额: **{amount}** 小猪粮\n"
                    f"收款码: 已复用已保存的微信+支付宝双码\n"
                    f"单号: #{wr.id}\n"
                    f"剩余可用: **{user.m_bean}** 小猪粮\n"
                    f"---\n"
                    f"如需修改收款码，请点击下方按钮进入网页面板修改。"
                )
                await _reply_withdraw_prompt(msg, "需要修改收款码时，请前往网页提现面板重新上传。")
                return
            except ValueError as e:
                db.session.rollback()
                await msg.reply(str(e))
                return
            except Exception as e:
                logger.error(f'复用收款码提现失败: {e}')
                db.session.rollback()
                await msg.reply('提现失败，请联系管理员')
                return

        kook_id = str(getattr(getattr(msg, 'author', None), 'id', '') or '')
        if not kook_id:
            await msg.reply('未获取到你的KOOK身份，请重试')
            return
        if kook_id in _withdraw_pending_uploads:
            await _reply_withdraw_prompt(
                msg,
                '你已有一笔待上传收款码的提现，请先完成上传（微信+支付宝），或发送 `/取消提现` 取消后重提。'
            )
            return

        _withdraw_pending_uploads[kook_id] = {
            'amount': str(amount),
            'step': 'wechat',
            'wechat_image': '',
            'created_at': time.time(),
        }
        await _reply_withdraw_prompt(
            msg,
            f"已记录提现金额: **{amount}** 小猪粮\n"
            f"请在 10 分钟内依次上传**微信收款码**和**支付宝收款码**（各一张）。\n"
            f"上传完成后将自动提交提现申请。\n"
            f"如需取消，请发送 `/取消提现`。"
        )


@bot.command(name='转换')
async def convert_coin_cmd(msg: Message, amount_str: str = ''):
    """
    小猪金转嗯呢币（1:1）
    用法: /转换 金额
    """
    with app.app_context():
        user = get_or_create_user_by_kook(msg.author)

        if not amount_str:
            await msg.reply(
                f"请输入转换金额: `/转换 金额`\n"
                f"当前小猪金(小猪粮): **{user.m_bean}**\n"
                f"当前嗯呢币余额: **{user.m_coin}**"
            )
            return

        try:
            amount = Decimal(str(amount_str).strip())
        except Exception:
            await msg.reply('金额格式不正确，请输入数字。例如: `/转换 100`')
            return

        try:
            success, error = _transfer_bean_to_coin(user, amount)
            if not success:
                await msg.reply(f'转换失败: {error}')
                return

            db.session.commit()
            await msg.reply(
                f"**转换成功**\n"
                f"转换金额: **{amount}**\n"
                f"剩余小猪金(小猪粮): **{user.m_bean}**\n"
                f"当前嗯呢币余额: **{user.m_coin}**"
            )
        except Exception as e:
            db.session.rollback()
            logger.error(f'/转换 执行失败: {e}')
            await msg.reply(f'转换失败: {e}')


@bot.command(name='结单')
async def report_order_cmd(msg: Message, order_no: str = '', duration_str: str = ''):
    """
    陪玩结单申报
    用法: /结单 订单号 时长(小时，支持整数或0.5)
    例: /结单 202501011234561234 1.5
    """
    try:
        with app.app_context():
            user = get_or_create_user_by_kook(msg.author)

            if not order_no:
                await msg.reply('请输入订单号和时长: `/结单 订单号 时长`\n例: `/结单 202501011234561234 1.5`')
                return

            order = Order.query.filter_by(order_no=order_no).first()
            if not order:
                await msg.reply(f'未找到订单: `{order_no}`')
                return

            if order.player_id != user.id:
                await msg.reply('你只能申报自己的订单')
                return

            if order.order_type in ('escort', 'training'):
                await msg.reply('护航/代练订单无需结单申报，创建后已自动结算并冻结。')
                return

            if not duration_str:
                await msg.reply('请输入游戏时长(小时): `/结单 订单号 时长`\n例: `/结单 202501011234561234 1.5`\n仅支持整数或0.5（如 0.5、1、1.5）')
                return

            if order.status not in ('pending_report', 'pending_confirm'):
                await msg.reply(f'该订单当前状态为 **{order.status_label}**，仅待申报/待确认可修改申报')
                return

            try:
                duration = Decimal(duration_str)
            except Exception:
                await msg.reply('时长格式不正确，请输入数字(小时)')
                return

            if duration <= 0:
                await msg.reply('时长必须大于0')
                return

            from app.services.order_service import report_order

            # 当前业务为“仅填几小时”，直接传小时数
            success, error = report_order(order, duration, operator_id=user.id)
            if not success:
                await msg.reply(f'结单失败: {error}')
                return

            db.session.commit()

            # 常规陪玩：仍需老板确认
            from app.services.kook_service import push_order_report
            push_order_report(order)

            await msg.reply(
                f"**结单申报成功**\n"
                f"订单号: `{order.order_no}`\n"
                f"游戏项目: **{order.project_display}**\n"
                f"游戏时长: **{order.duration}** 小时\n"
                f"订单金额: **{order.total_price}** 嗯呢币\n"
                f"你的收益: **{order.player_earning}** 小猪粮\n"
                f"---\n"
                f"等待老板确认，24小时后将自动确认"
            )
    except Exception as e:
        logger.exception('执行 /结单 命令异常')
        await msg.reply(f'结单失败: {e}')


@bot.command(name='确认')
async def confirm_order_cmd(msg: Message, order_no: str = ''):
    """
    老板确认订单
    用法: /确认 订单号
    """
    with app.app_context():
        user = get_or_create_user_by_kook(msg.author)

        if not order_no:
            await msg.reply('请输入订单号: `/确认 订单号`')
            return

        order = Order.query.filter_by(order_no=order_no).first()
        if not order:
            await msg.reply(f'未找到订单: `{order_no}`')
            return

        if order.boss_id != user.id:
            await msg.reply('你只能确认自己的订单')
            return

        if order.status != 'pending_confirm':
            await msg.reply(f'该订单当前状态为 **{order.status_label}**，不在待确认状态')
            return

        from app.services.order_service import confirm_order

        success, error = confirm_order(order, operator_id=user.id)
        if not success:
            await msg.reply(f'确认失败: {error}')
            return

        db.session.commit()

        # 发送 KOOK 推送给陪玩
        from app.services.kook_service import push_order_confirm
        push_order_confirm(order)

        await msg.reply(
            f"**订单已确认**\n"
            f"订单号: `{order.order_no}`\n"
            f"订单金额: **{order.total_price}** 嗯呢币\n"
            f"---\n"
            f"佣金已发放给陪玩"
        )


@bot.command(name='roll')
async def roll_cmd(msg: Message, total_str: str = '', count_str: str = ''):
    """
    随机掷点
    用法: /roll 总点数 抽几个点
    例: /roll 6 1
    """
    if not total_str or not count_str:
        await msg.reply('用法: `/roll 总点数 抽几个点`\n例: `/roll 6 1`')
        return

    try:
        total = int(str(total_str).strip())
        count = int(str(count_str).strip())
    except Exception:
        await msg.reply('参数格式错误，请输入整数。\n例: `/roll 6 1`')
        return

    if total <= 0:
        await msg.reply('总点数必须大于 0')
        return
    if count <= 0:
        await msg.reply('抽取数量必须大于 0')
        return
    if count > 100:
        await msg.reply('抽取数量过大，请输入 1-100')
        return

    results = [random.randint(1, total) for _ in range(count)]
    result_text = ' '.join([f'「{n}」' for n in results])
    card = [
        {
            "type": "card",
            "theme": "secondary",
            "size": "lg",
            "modules": [
                {"type": "header", "text": {"type": "plain-text", "content": "Roll点结果"}},
                {"type": "section", "text": {"type": "kmarkdown", "content": result_text}},
            ],
        }
    ]
    try:
        await msg.reply(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
    except Exception:
        await msg.reply(f'Roll点结果: {result_text}')


@bot.command(name='发布抽奖')
async def publish_lottery_cmd(msg: Message, winner_count_str: str = ''):
    """
    发布抽奖（30分钟自动开奖）
    用法: /发布抽奖 中奖人数
    """
    if not winner_count_str:
        await msg.reply('请输入中奖人数: `/发布抽奖 中奖人数`')
        return

    try:
        winner_count = int(str(winner_count_str).strip())
    except Exception:
        await msg.reply('中奖人数格式不正确，请输入整数')
        return

    if winner_count <= 0:
        await msg.reply('中奖人数必须大于 0')
        return
    if winner_count > 100:
        await msg.reply('中奖人数过大，请输入 1-100')
        return

    channel_id = _extract_msg_channel_id(msg)
    if not channel_id:
        await msg.reply('未获取到频道 ID，请在服务器文字频道中使用该命令')
        return

    with app.app_context():
        from app.services.lottery_service import create_interactive_lottery
        from app.services.log_service import log_operation

        user = get_or_create_user_by_kook(msg.author)
        lottery = create_interactive_lottery(
            channel_id=channel_id,
            created_by=user.id,
            winner_count=winner_count,
        )
        log_operation(
            user.id,
            'lottery_create',
            'lottery',
            lottery.id,
            f'KOOK 指令创建互动抽奖: {lottery.title}',
        )
        log_operation(
            user.id,
            'lottery_publish',
            'lottery',
            lottery.id,
            f'KOOK 指令发布互动抽奖: {lottery.title}',
        )
        db.session.commit()
        lottery_id = lottery.id
        delay_seconds = max(0, (lottery.draw_time - datetime.now()).total_seconds())

    old_task = _interactive_tasks.pop(lottery_id, None)
    if old_task and not old_task.done():
        old_task.cancel()
    _interactive_tasks[lottery_id] = asyncio.create_task(
        _auto_draw_interactive_lottery(lottery_id, delay_seconds)
    )

    await msg.reply(
        f"「互动抽奖」互动抽奖已经发起啦，本次中奖人数为：{winner_count}人。\n"
        f"抽奖ID：`#{lottery_id}`\n"
        f"参与方式：在本频道发送普通消息即可参与。\n"
        f"结束命令：`/结束抽奖 {lottery_id}`\n"
        f"如果不手动结束，将在30分钟后自动开奖。",
        use_quote=False,
        type=MessageTypes.KMD,
    )


@bot.command(name='结束抽奖')
async def end_lottery_cmd(msg: Message, lottery_id_str: str = ''):
    """
    提前结束当前频道抽奖并立即开奖
    用法: /结束抽奖 [抽奖ID]
    """
    channel_id = _extract_msg_channel_id(msg)
    if not channel_id:
        await msg.reply('未获取到频道 ID，请在服务器文字频道中使用该命令')
        return

    with app.app_context():
        from app.services.lottery_service import draw_lottery, get_active_interactive_lotteries
        from app.services.log_service import log_operation

        actor = get_or_create_user_by_kook(msg.author)
        active_lotteries = get_active_interactive_lotteries(channel_id, include_expired=True)
        if not active_lotteries:
            await msg.reply('当前频道没有进行中的互动抽奖')
            return

        lottery = None
        if lottery_id_str:
            try:
                lottery_id = int(str(lottery_id_str).strip().lstrip('#'))
            except Exception:
                await msg.reply('抽奖 ID 格式不正确，请使用 `/结束抽奖 抽奖ID`')
                return
            lottery = next((item for item in active_lotteries if item.id == lottery_id), None)
            if not lottery:
                await msg.reply(f'当前频道未找到进行中的互动抽奖 `#{lottery_id}`')
                return
        else:
            if len(active_lotteries) > 1:
                ids_text = '、'.join(f'#{item.id}' for item in active_lotteries[:10])
                await msg.reply(
                    f'当前频道有多个进行中的互动抽奖：{ids_text}\n'
                    f'请使用 `/结束抽奖 抽奖ID` 指定要结束的活动。'
                )
                return
            lottery = active_lotteries[0]

        ok, result_msg = draw_lottery(lottery)
        if not ok:
            await msg.reply(result_msg)
            return

        log_operation(
            actor.id,
            'lottery_draw',
            'lottery',
            lottery.id,
            f'KOOK 指令提前结束互动抽奖: {lottery.title}',
        )
        db.session.commit()
        lottery_id = lottery.id

    task = _interactive_tasks.pop(lottery_id, None)
    if task and not task.done():
        task.cancel()
    await msg.reply(f'互动抽奖 `#{lottery_id}` 已结束，{result_msg}')


def _build_help_text():
    content = (
        "**嗯呢呗电竞机器人 命令列表**\n"
        "---\n"
        "`/bind` - 查看当前自动识别的账号\n"
        "`/钱包` - 查看钱包信息\n"
        "`/签到` 或 `/打卡` - 每日签到并累计连续天数\n"
        "`/转换 金额` - 将小猪金(小猪粮)按1:1转换为嗯呢币\n"
        "`/结单 订单号 时长` - 结单申报(仅支持整数或0.5小时)\n"
        "`/确认 订单号` - 确认订单(老板)\n"
        "`/roll 总点数 抽几个点` - 掷点/随机点数\n"
        "`/游戏` - 游戏厅菜单（猜词/炸弹/21点/四子棋/卧底/灰区档案）\n"
        "`/发布抽奖 中奖人数` - 全员可用，发起互动抽奖(30分钟自动开奖)\n"
        "`/结束抽奖 [抽奖ID]` - 结束互动抽奖并立即开奖\n"
        "`/提现 [金额]` - 申请提现(无金额会弹网页入口；需微信+支付宝收款码)\n"
        "`/取消提现` - 取消待上传收款码的提现\n"
        "`/帮助` 或 `/help` - 查看此帮助\n"
        "`/ping` - 测试机器人"
    )
    return content


def _minigame_channel_id(msg: Message) -> str:
    # DM 必须返回固定 'dm',否则按钮回调路径的 channel_id 与开局存的不一致,导致 session 找不到。
    if _is_private_message(msg):
        return 'dm'
    return _extract_msg_channel_id(msg) or 'unknown'


def _minigame_user_id(msg: Message) -> str:
    return str(getattr(getattr(msg, 'author', None), 'id', '') or getattr(msg, 'author_id', '') or '')


def _is_active_blackjack_result(result) -> bool:
    message = str((result or {}).get('message') or '')
    return (
        bool(result and result.get('ok', True))
        and not bool(result.get('ended'))
        and '**21 点**' in message
    )


def _build_blackjack_action_card(text: str, owner_id: str, channel_id: str):
    owner_id = str(owner_id or '').strip()
    channel_id = str(channel_id or '').strip() or 'unknown'
    if not owner_id:
        return None
    actions = [
        ('要牌', 'hit', 'primary'),
        ('停牌', 'stand', 'danger'),
    ]
    return [{
        "type": "card",
        "theme": "secondary",
        "size": "lg",
        "modules": [
            {
                "type": "section",
                "text": {"type": "kmarkdown", "content": str(text or '')},
            },
            {
                "type": "action-group",
                "elements": [
                    {
                        "type": "button",
                        "theme": theme,
                        "value": f"{BLACKJACK_BUTTON_PREFIX}|{owner_id}|{channel_id}|{action}",
                        "click": "return-val",
                        "text": {"type": "plain-text", "content": label},
                    }
                    for label, action, theme in actions
                ],
            },
        ],
    }]


async def _reply_minigame_result(msg: Message, result):
    message = (result or {}).get('message') or '小游戏暂无响应。'
    record_payload = (result or {}).get('record') or None
    rating_text = ''
    if record_payload and record_payload.get('game') == 'blackjack' and record_payload.get('outcome_kind'):
        try:
            with app.app_context():
                from app.services import minigame_service
                try:
                    if getattr(msg, 'author', None):
                        get_or_create_user_by_kook(msg.author)
                except Exception:
                    logger.exception('21 点排位分账号识别失败')
                    db.session.rollback()
                rating_text = minigame_service.apply_blackjack_rating(record_payload) or ''
        except Exception:
            logger.exception('21 点排位分更新失败')
            try:
                db.session.rollback()
            except Exception:
                pass
    if rating_text:
        message = f'{message}\n\n{rating_text}'
        result['message'] = message
    if _is_active_blackjack_result(result):
        card = _build_blackjack_action_card(message, _minigame_user_id(msg), _minigame_channel_id(msg))
        if card:
            try:
                await msg.reply(json.dumps(card, ensure_ascii=False), type=MessageTypes.CARD)
                await _persist_minigame_record(msg, result)
                await _dispatch_minigame_side_effects((result or {}).get('side_effects'))
                return
            except Exception:
                logger.exception('21 点按钮卡片发送失败，降级 KMD')
    await msg.reply(message, type=MessageTypes.KMD)
    await _persist_minigame_record(msg, result)
    await _dispatch_minigame_side_effects((result or {}).get('side_effects'))


async def _dispatch_minigame_side_effects(side_effects):
    """处理小游戏返回的副作用（目前只有 DM 私信派发，谁是卧底用）。"""
    if not side_effects:
        return
    dm_list = side_effects.get('dm') or []
    for dm in dm_list:
        kook_id = str(dm.get('kook_id') or '').strip()
        text = dm.get('text') or ''
        if not kook_id or not text:
            continue
        try:
            target = KhlUser(id=kook_id, _gate_=bot.client.gate)
            await target.send(text, type=MessageTypes.KMD)
        except Exception:
            logger.exception('小游戏 DM 发送失败 kook_id=%s', kook_id)


async def _persist_minigame_record(msg: Message, result):
    await _persist_minigame_record_payload(
        (result or {}).get('record'),
        author=getattr(msg, 'author', None),
    )


async def _persist_minigame_record_payload(record_payload, author=None):
    if not record_payload:
        return
    try:
        with app.app_context():
            try:
                if author:
                    get_or_create_user_by_kook(author)
            except Exception:
                logger.exception('小游戏玩家账号自动识别失败')
                db.session.rollback()
            from app.services import minigame_service
            minigame_service.record_minigame_result(record_payload)
    except Exception:
        logger.exception('小游戏战绩记录失败')
        try:
            db.session.rollback()
        except Exception:
            pass


def _minigame_leaderboard_message(game_key: str = '') -> str:
    from app.services import minigame_service

    try:
        with app.app_context():
            return minigame_service.format_leaderboard(game_key)
    except Exception:
        logger.exception('小游戏排行榜读取失败')
        try:
            db.session.rollback()
        except Exception:
            pass
        return '小游戏排行榜读取失败，请确认已经执行 `flask db upgrade`。'


async def _start_minigame(msg: Message, game_key: str):
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    result = minigame_service.start_game(
        channel_id=_minigame_channel_id(msg),
        kook_id=kook_id,
        player_name=_kook_user_tag(getattr(msg, 'author', None)),
        game_key=game_key,
    )
    await _reply_minigame_result(msg, result)


def _extract_kook_id_from_text(text: str) -> str:
    raw = str(text or '').strip()
    patterns = (
        r'\(met\)(\d+)\(met\)',
        r'<@!?(\d+)>',
        r'\b(\d{4,})\b',
    )
    for pattern in patterns:
        m = re.search(pattern, raw)
        if m:
            return m.group(1)
    return ''


async def _handle_connect4_command(msg: Message, action: str = '', *args: str):
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return

    channel_id = _minigame_channel_id(msg)
    action_raw = str(action or '').strip()
    action_key = action_raw.lower()
    rest = ' '.join(args).strip()

    if action_key in ('', 'help', '帮助', '菜单'):
        result = {'message': minigame_service.connect4_menu_text()}
    elif action_key in ('状态', 'status'):
        result = minigame_service.get_status(channel_id, kook_id)
    elif action_key in ('退出', '结束', 'quit', 'stop', 'cancel'):
        result = minigame_service.quit_game(channel_id, kook_id)
    elif action_key in ('落子', 'move', 'drop', '下'):
        result = minigame_service.handle_connect4_move(channel_id, kook_id, rest)
    else:
        opponent_text = ' '.join([part for part in [action_raw, rest] if part]).strip()
        result = minigame_service.start_connect4(
            channel_id=channel_id,
            starter_id=kook_id,
            starter_name=_kook_user_tag(getattr(msg, 'author', None)),
            opponent_id=_extract_kook_id_from_text(opponent_text),
            opponent_name='',
        )

    await _reply_minigame_result(msg, result)


@bot.command(name='帮助')
async def help_cmd(msg: Message):
    """帮助命令（中文）"""
    await msg.reply(_build_help_text())


@bot.command(name='help')
async def help_en_cmd(msg: Message):
    """帮助命令别名。"""
    await msg.reply(_build_help_text())


@bot.command(name='游戏')
async def minigame_cmd(msg: Message, action: str = '', *args: str):
    """KOOK 小游戏厅。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return

    channel_id = _minigame_channel_id(msg)
    action_raw = str(action or '').strip()
    action_key = action_raw.lower()
    rest = ' '.join(args).strip()

    if action_key in ('', 'help', '菜单', '帮助'):
        result = {'message': minigame_service.menu_text()}
    elif action_key in ('退出', '结束', 'quit', 'stop', 'cancel'):
        result = minigame_service.quit_game(channel_id, kook_id)
    elif action_key in ('状态', 'status'):
        result = minigame_service.get_status(channel_id, kook_id)
    elif action_key in ('排行', '排行榜', 'rank', 'ranking'):
        result = {'message': _minigame_leaderboard_message(rest)}
    elif action_key in ('猜', 'guess', 'g'):
        result = minigame_service.handle_guess(channel_id, kook_id, rest)
    elif action_key in ('剧情', '故事', 'story', '灰区档案'):
        story_action = args[0] if len(args) >= 1 else ''
        story_args = args[1:] if len(args) >= 2 else ()
        await story_cmd(msg, story_action, *story_args)
        return
    elif action_key in ('炸弹', 'bomb', '数字炸弹'):
        sub_parts = rest.split(maxsplit=1)
        sub_action = sub_parts[0] if sub_parts else ''
        sub_rest = sub_parts[1] if len(sub_parts) > 1 else ''
        result = minigame_service.handle_bomb_command(
            channel_id,
            kook_id,
            _kook_user_tag(getattr(msg, 'author', None)),
            sub_action,
            sub_rest,
        )
    elif action_key in ('卧底', 'undercover', '谁是卧底'):
        sub_parts = rest.split(maxsplit=1)
        sub_action = sub_parts[0] if sub_parts else ''
        sub_rest = sub_parts[1] if len(sub_parts) > 1 else ''
        result = minigame_service.handle_undercover_command(
            channel_id,
            kook_id,
            _kook_user_tag(getattr(msg, 'author', None)),
            sub_action,
            sub_rest,
        )
    elif action_key in ('四子棋', 'connect4', '连四'):
        result = minigame_service.start_connect4(
            channel_id=channel_id,
            starter_id=kook_id,
            starter_name=_kook_user_tag(getattr(msg, 'author', None)),
            opponent_id=_extract_kook_id_from_text(rest),
            opponent_name='',
        )
    elif action_key in ('落子', 'move', 'drop', '下'):
        result = minigame_service.handle_connect4_move(channel_id, kook_id, rest)
    elif action_key in ('要牌', 'hit', 'h', '拿牌', '停牌', 'stand', 's', '不要', '开牌'):
        result = minigame_service.handle_blackjack_action(channel_id, kook_id, action_key)
    elif minigame_service.normalize_game_key(action_key):
        result = minigame_service.start_game(
            channel_id=channel_id,
            kook_id=kook_id,
            player_name=_kook_user_tag(getattr(msg, 'author', None)),
            game_key=action_key,
        )
    else:
        # 让 `/游戏 红 蓝 绿 黄`、`/游戏 陪玩店` 这类输入也能直接喂给当前局。
        guess_text = ' '.join([part for part in [action_raw, rest] if part]).strip()
        result = minigame_service.handle_guess(channel_id, kook_id, guess_text)

    await _reply_minigame_result(msg, result)


@bot.command(name='猜词')
async def hangman_game_cmd(msg: Message):
    """快速开始猜词。"""
    await _start_minigame(msg, '猜词')


@bot.command(name='乱序')
async def scramble_game_cmd(msg: Message):
    """快速开始乱序词。"""
    await _start_minigame(msg, '乱序')


@bot.command(name='密码')
async def mastermind_game_cmd(msg: Message):
    """快速开始密码色。"""
    await _start_minigame(msg, '密码')


@bot.command(name='21点')
async def blackjack_game_cmd(msg: Message):
    """快速开始 21 点。"""
    await _start_minigame(msg, '21点')


@bot.command(name='炸弹')
async def bomb_game_cmd(msg: Message, action: str = '', *args: str):
    """数字炸弹（单人/多人）。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    rest = ' '.join(args).strip()
    result = minigame_service.handle_bomb_command(
        _minigame_channel_id(msg),
        kook_id,
        _kook_user_tag(getattr(msg, 'author', None)),
        action,
        rest,
    )
    await _reply_minigame_result(msg, result)


@bot.command(name='卧底')
async def undercover_game_cmd(msg: Message, action: str = '', *args: str):
    """谁是卧底。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    rest = ' '.join(args).strip()
    result = minigame_service.handle_undercover_command(
        _minigame_channel_id(msg),
        kook_id,
        _kook_user_tag(getattr(msg, 'author', None)),
        action,
        rest,
    )
    await _reply_minigame_result(msg, result)


@bot.command(name='四子棋')
async def connect4_game_cmd(msg: Message, action: str = '', *args: str):
    """双人四子棋。"""
    await _handle_connect4_command(msg, action, *args)


@bot.command(name='connect4')
async def connect4_en_game_cmd(msg: Message, action: str = '', *args: str):
    """双人四子棋别名。"""
    await _handle_connect4_command(msg, action, *args)


@bot.command(name='落子')
async def connect4_move_cmd(msg: Message, column: str = ''):
    """四子棋落子。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    result = minigame_service.handle_connect4_move(_minigame_channel_id(msg), kook_id, column)
    await _reply_minigame_result(msg, result)


@bot.command(name='猜')
async def minigame_guess_cmd(msg: Message, *parts: str):
    """提交小游戏猜测。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    result = minigame_service.handle_guess(_minigame_channel_id(msg), kook_id, ' '.join(parts).strip())
    await _reply_minigame_result(msg, result)


@bot.command(name='要牌')
async def blackjack_hit_cmd(msg: Message):
    """21 点要牌。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    result = minigame_service.handle_blackjack_action(_minigame_channel_id(msg), kook_id, '要牌')
    await _reply_minigame_result(msg, result)


@bot.command(name='停牌')
async def blackjack_stand_cmd(msg: Message):
    """21 点停牌。"""
    from app.services import minigame_service

    kook_id = _minigame_user_id(msg)
    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return
    result = minigame_service.handle_blackjack_action(_minigame_channel_id(msg), kook_id, '停牌')
    await _reply_minigame_result(msg, result)


@bot.command(name='取消提现')
async def cancel_withdraw_cmd(msg: Message):
    """取消待上传收款码的提现申请。"""
    kook_id = str(getattr(getattr(msg, 'author', None), 'id', '') or '')
    if not kook_id:
        await msg.reply('未获取到你的KOOK身份，请重试')
        return
    _cleanup_expired_withdraw_pending()
    if _withdraw_pending_uploads.pop(kook_id, None):
        await msg.reply('已取消本次提现申请。')
    else:
        await msg.reply('当前没有待上传收款码的提现申请。')


async def _handle_checkin(msg: Message):
    channel_id = _extract_msg_channel_id(msg)
    kook_id = str(getattr(getattr(msg, 'author', None), 'id', '') or '')
    kook_username = _kook_user_tag(getattr(msg, 'author', None))
    if not kook_id:
        await msg.reply('未获取到你的KOOK身份，请重试')
        return

    try:
        with app.app_context():
            user = get_or_create_user_by_kook(msg.author)
            from app.services.chat_stats_service import perform_checkin
            result = perform_checkin(
                channel_id=channel_id,
                kook_id=kook_id,
                kook_username=kook_username,
                user_id=user.id if user else None,
            )
        await msg.reply(result.get('message') or '打卡完成')
    except Exception as e:
        logger.exception('/签到 执行失败')
        await msg.reply(f'打卡失败: {e}')


@bot.command(name='签到')
async def checkin_cmd(msg: Message):
    """每日签到。"""
    await _handle_checkin(msg)


@bot.command(name='打卡')
async def checkin_alias_cmd(msg: Message):
    """每日打卡。"""
    await _handle_checkin(msg)


@bot.command(name='story')
async def story_cmd(msg: Message, action: str = '', *args: str):
    """AI 剧情互动游戏入口。"""
    kook_id = str(getattr(getattr(msg, 'author', None), 'id', '') or '')
    kook_username = _kook_user_tag(getattr(msg, 'author', None))
    channel_id = _extract_msg_channel_id(msg)
    action_key = str(action or '').strip().lower()

    if not kook_id:
        await msg.reply('未获取到你的 KOOK 身份，请重试')
        return

    try:
        with app.app_context():
            user = get_or_create_user_by_kook(msg.author)
            from app.services import story_game_service
            reply_payload = None

            if action_key in ('', 'help', 'menu', '菜单', '帮助'):
                reply_text = story_game_service.menu_text()
            elif action_key in ('start', '开始'):
                world_arg = args[0] if len(args) >= 1 else ''
                background_arg = args[1] if len(args) >= 2 else ''
                result = story_game_service.start_story(
                    kook_id=kook_id,
                    kook_username=kook_username,
                    user_id=user.id if user else None,
                    world_arg=world_arg,
                    background_arg=background_arg,
                    reset=False,
                )
                reply_payload = result if result.get('ok') else None
                reply_text = result.get('message') or '剧情已开始。'
            elif action_key in ('restart', 'reset', '重开', '重新开始'):
                world_arg = args[0] if len(args) >= 1 else ''
                background_arg = args[1] if len(args) >= 2 else ''
                result = story_game_service.start_story(
                    kook_id=kook_id,
                    kook_username=kook_username,
                    user_id=user.id if user else None,
                    world_arg=world_arg,
                    background_arg=background_arg,
                    reset=True,
                )
                reply_payload = result if result.get('ok') else None
                reply_text = result.get('message') or '剧情已重开。'
            elif action_key in ('continue', 'c', '继续'):
                user_input = ' '.join(args).strip()
                result = story_game_service.continue_story(
                    kook_id=kook_id,
                    user_id=user.id if user else None,
                    user_input=user_input,
                    channel_id=channel_id,
                )
                reply_payload = result if result.get('ok') else None
                reply_text = result.get('message') or '剧情推进完成。'
            elif action_key in ('profile', '档案'):
                reply_text = story_game_service.profile_text(kook_id)
            elif action_key in ('archive', 'archives', '记忆', '档案库'):
                reply_text = story_game_service.archive_text(kook_id)
            elif action_key in ('dm', 'mail', '私信'):
                reply_text = story_game_service.dm_inbox_text(kook_id)
            elif action_key in ('memory', 'mem0', 'longmemory', '长期记忆'):
                query = ' '.join(args).strip()
                reply_text = story_game_service.memory_text(kook_id, query)
            elif action_key in ('status', '状态'):
                reply_text = story_game_service.llm_status_text()
            elif action_key in ('reply', '回复'):
                character_arg = args[0] if len(args) >= 1 else ''
                reply_body = ' '.join(args[1:]).strip() if len(args) >= 2 else ''
                result = story_game_service.reply_dm(
                    kook_id=kook_id,
                    user_id=user.id if user else None,
                    character_arg=character_arg,
                    reply_text=reply_body,
                    channel_id=channel_id,
                )
                reply_text = result.get('message') or '私信已回复。'
            else:
                reply_text = (
                    '未知剧情指令。\n'
                    '`/游戏 剧情` 查看菜单；`/游戏 剧情 继续 你的行动` 推进剧情；'
                    '`/游戏 剧情 档案` 查看档案。'
                )
        if reply_payload is not None:
            await _reply_story_result(msg, reply_payload, owner_id=kook_id)
        else:
            await msg.reply(reply_text, type=MessageTypes.KMD)
    except Exception as e:
        logger.exception('/story 执行失败')
        with app.app_context():
            db.session.rollback()
        await msg.reply(f'剧情系统暂时异常: {e}')


# ─── 事件处理器 ──────────────────────────────────────────────

@bot.on_event(EventTypes.MESSAGE_BTN_CLICK)
async def on_story_choice_button(bot_obj: Bot, event: Event):
    """处理剧情和小游戏卡片按钮。"""
    try:
        body = getattr(event, 'body', {}) or {}
        value = (
            _event_body_value(body, 'value')
            or _nested_event_body_value(body, 'data', 'value')
            or _nested_event_body_value(body, 'extra', 'value')
        )
        blackjack_action = _parse_blackjack_button_value(value)
        if blackjack_action:
            click_user_id = _button_event_user_id(event)
            owner_id = blackjack_action['owner_id']
            if owner_id and click_user_id and owner_id != click_user_id:
                await _send_minigame_event_result(
                    bot_obj,
                    event,
                    {'message': '这局 21 点属于另一位玩家，请使用 `/游戏 21点` 开始自己的牌局。'},
                    owner_id=click_user_id,
                    channel_id=_minigame_event_channel_id(event, blackjack_action.get('channel_id')),
                    temp_target_id=click_user_id,
                )
                return

            kook_id = click_user_id or owner_id
            if not kook_id:
                logger.warning('21 点按钮事件缺少用户 ID: %s', body)
                return

            channel_id = _minigame_event_channel_id(event, blackjack_action.get('channel_id'))
            action = '要牌' if blackjack_action['action'] == 'hit' else '停牌'
            with app.app_context():
                from app.services import minigame_service

                result = minigame_service.handle_blackjack_action(channel_id, kook_id, action)
                record_payload = (result or {}).get('record') or None
                if record_payload and record_payload.get('outcome_kind'):
                    rating_text = minigame_service.apply_blackjack_rating(record_payload) or ''
                    if rating_text:
                        result['message'] = f"{result.get('message', '')}\n\n{rating_text}"

            await _send_minigame_event_result(
                bot_obj,
                event,
                result,
                owner_id=kook_id,
                channel_id=channel_id,
            )
            await _persist_minigame_record_payload((result or {}).get('record'))
            return

        parsed = _parse_story_button_value(value)
        if not parsed:
            return

        click_user_id = _button_event_user_id(event)
        owner_id = parsed['owner_id']
        if owner_id and click_user_id and owner_id != click_user_id:
            await _send_story_event_message(
                bot_obj,
                event,
                '这张剧情卡属于另一位玩家，请使用 `/游戏 剧情` 开始自己的剧情。',
                owner_id=click_user_id,
                temp_target_id=click_user_id,
            )
            return

        kook_id = click_user_id or owner_id
        if not kook_id:
            logger.warning('剧情按钮事件缺少用户 ID: %s', body)
            return

        target_id = _button_event_target_id(event)
        with app.app_context():
            from app.services import story_game_service

            user = (
                User.query.filter_by(kook_id=kook_id)
                .order_by(User.kook_bound.desc(), User.id.asc())
                .first()
            )
            user_id = user.id if user else None
            choice_text = story_game_service.choice_feedback_text(kook_id, parsed['choice'])

        if choice_text:
            await _send_story_event_message(
                bot_obj,
                event,
                f'你选择了 **{choice_text}**\n剧情引擎正在读取你的行动，请稍等...',
                owner_id=kook_id,
            )

        with app.app_context():
            from app.services import story_game_service

            result = story_game_service.continue_story(
                kook_id=kook_id,
                user_id=user_id,
                user_input=parsed['choice'],
                channel_id=target_id,
            )

        await _send_story_event_message(bot_obj, event, result, owner_id=kook_id)
    except Exception as e:
        logger.exception('按钮事件处理失败')
        with app.app_context():
            db.session.rollback()
        click_user_id = _button_event_user_id(event)
        await _send_minigame_event_result(
            bot_obj,
            event,
            {'message': f'按钮处理失败: {e}'},
            owner_id=click_user_id,
            channel_id=_minigame_event_channel_id(event),
            temp_target_id=click_user_id,
        )


@bot.on_message()
async def on_public_message(msg: Message):
    """互动抽奖参与收集：仅活动所在频道发言才自动参与。"""
    try:
        if _is_bot_author(msg):
            return

        # 提现图片上传：优先处理，处理成功后不再进入其他逻辑
        if await _try_complete_withdraw_with_payment_image(msg):
            return

        # 忽略命令消息，仅统计普通发言
        if _is_command_message(msg):
            return

        # 仅统计抽奖发起频道内的发言，避免跨频道误参与
        msg_channel_id = str(_extract_msg_channel_id(msg) or '')
        if _is_private_message(msg):
            uid = str(getattr(msg, 'author_id', '') or getattr(getattr(msg, 'author', None), 'id', '') or '')
            if not uid:
                return
            try:
                with app.app_context():
                    user = get_or_create_user_by_kook(msg.author)
                    from app.services.story_game_service import handle_direct_free_input
                    result = handle_direct_free_input(
                        kook_id=uid,
                        user_id=user.id if user else None,
                        content=str(getattr(msg, 'content', '') or ''),
                        channel_id='dm',
                    )
                if result and result.get('message'):
                    await msg.reply(result['message'], type=MessageTypes.KMD)
            except Exception as e:
                logger.warning(f'剧情私信回复处理失败: {e}')
            return

        if not msg_channel_id:
            return

        uid = str(getattr(msg, 'author_id', '') or getattr(getattr(msg, 'author', None), 'id', '') or '')
        if not uid:
            return
        kook_username = _kook_user_tag(getattr(msg, 'author', None))

        with app.app_context():
            bound_user = (
                User.query
                .filter_by(kook_id=uid)
                .order_by(User.kook_bound.desc(), User.id.asc())
                .first()
            )
            try:
                from app.services.chat_stats_service import record_message
                record_message(
                    channel_id=msg_channel_id,
                    kook_id=uid,
                    kook_username=kook_username,
                    content=str(getattr(msg, 'content', '') or ''),
                    user_id=bound_user.id if bound_user else None,
                )
            except Exception as e:
                logger.warning(f'发言统计记录失败: {e}')

            from app.services.lottery_service import record_interactive_participation
            record_interactive_participation(
                channel_id=msg_channel_id,
                kook_id=uid,
                kook_username=kook_username,
                user_id=bound_user.id if bound_user else None,
            )
    except Exception as e:
        logger.error(f'互动抽奖参与收集异常: {e}')

# 抽奖参与人数：内存缓存（msg_id → set of kook_user_id）
# 添加表情时直接 set.add() 后更新卡片，只需 1 次 API 调用（message/update），实现秒级刷新
_lottery_participants = {}
_lottery_delete_ts = {}  # 移除反应防抖


def _init_participants(msg_id):
    """首次访问时从 API 拉取完整参与者集合（仅调用一次）"""
    from app.services.lottery_service import _get_all_reaction_users
    users = _get_all_reaction_users(msg_id)
    _lottery_participants[msg_id] = set(users)
    return _lottery_participants[msg_id]


def _extract_reaction_event_ids(event: Event):
    """兼容不同事件体结构，提取 msg_id / user_id"""
    body = event.body if isinstance(event.body, dict) else {}
    extra = body.get('extra') if isinstance(body.get('extra'), dict) else {}

    msg_id = str(
        body.get('msg_id')
        or extra.get('msg_id')
        or extra.get('target_id')
        or ''
    )
    user_id = str(
        body.get('user_id')
        or extra.get('user_id')
        or extra.get('author_id')
        or ''
    )
    return msg_id, user_id


@bot.on_event(EventTypes.ADDED_REACTION)
async def on_reaction_add(b: Bot, event: Event):
    """有人添加表情回应 → 实时更新抽奖参与人数"""
    msg_id, user_id = _extract_reaction_event_ids(event)
    if not msg_id or not user_id:
        return

    with app.app_context():
        from app.models.lottery import Lottery
        lottery = Lottery.query.filter_by(kook_msg_id=msg_id, status='published').first()
        if not lottery:
            return

        from app.services.lottery_service import _get_bot_id
        if user_id == _get_bot_id():
            return

        # 首次事件：从 API 初始化集合；之后直接 set.add()
        if msg_id not in _lottery_participants:
            _init_participants(msg_id)

        prev_len = len(_lottery_participants[msg_id])
        _lottery_participants[msg_id].add(user_id)

        if len(_lottery_participants[msg_id]) == prev_len:
            return  # 用户已在集合中（换了个表情），人数没变，无需更新卡片

        count = len(_lottery_participants[msg_id])
        from app.services.lottery_service import build_lottery_card, _update_channel_msg
        card_json = build_lottery_card(lottery, participant_count=count)
        _update_channel_msg(msg_id, card_json)


@bot.on_event(EventTypes.DELETED_REACTION)
async def on_reaction_delete(b: Bot, event: Event):
    """有人移除表情回应 → 重新计数并更新（5 秒防抖）"""
    msg_id, _ = _extract_reaction_event_ids(event)
    if not msg_id:
        return

    now = time.time()
    if msg_id in _lottery_delete_ts and now - _lottery_delete_ts[msg_id] < 5:
        return
    _lottery_delete_ts[msg_id] = now

    with app.app_context():
        from app.models.lottery import Lottery
        lottery = Lottery.query.filter_by(kook_msg_id=msg_id, status='published').first()
        if not lottery:
            return

        # 移除反应时需重新拉取，因为用户可能还有其他 emoji 反应
        _init_participants(msg_id)
        count = len(_lottery_participants[msg_id])
        from app.services.lottery_service import build_lottery_card, _update_channel_msg
        card_json = build_lottery_card(lottery, participant_count=count)
        _update_channel_msg(msg_id, card_json)


@bot.on_event(EventTypes.JOINED_CHANNEL)
async def on_joined_channel(b: Bot, event: Event):
    """用户进入语音频道 → 播报"""
    user_id = event.body.get('user_id', '')
    channel_id = event.body.get('channel_id', '')
    if not user_id or not channel_id:
        return

    with app.app_context():
        from app.services.kook_service import push_channel_event
        push_channel_event(user_id, channel_id, 'join')


@bot.on_event(EventTypes.EXITED_CHANNEL)
async def on_exited_channel(b: Bot, event: Event):
    """用户离开语音频道 → 播报"""
    user_id = event.body.get('user_id', '')
    channel_id = event.body.get('channel_id', '')
    if not user_id or not channel_id:
        return

    with app.app_context():
        from app.services.kook_service import push_channel_event
        push_channel_event(user_id, channel_id, 'leave')


if __name__ == '__main__':
    if not app.config.get('KOOK_TOKEN') or app.config.get('KOOK_TOKEN') == 'your-kook-bot-token':
        logger.error("KOOK_TOKEN is not set in configuration.")
        sys.exit(1)

    logger.info("Starting KOOK Bot...")
    bot.run()
