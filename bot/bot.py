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
# 需求：
# 1) /发布抽奖 任何人可用
# 2) 机器人发送普通文本消息（非卡片）
# 3) 抽奖发布后到结束前，在同一服务器发过消息的用户自动参与
# 4) 支持 /结束抽奖 提前结束，或 30 分钟自动结束
_interactive_lotteries = {}   # scope_key -> lottery_state
_interactive_tasks = {}       # scope_key -> asyncio.Task
_withdraw_pending_uploads = {}  # kook_user_id -> {"amount":"100.00","step":"wechat|alipay","wechat_image":"","created_at":ts}
_WITHDRAW_UPLOAD_TTL_SECONDS = 10 * 60


def _interactive_scope_key(msg: Message) -> str:
    """抽奖作用域：优先服务器级；拿不到服务器ID时回退到频道级。"""
    gid = _extract_msg_guild_id(msg)
    if gid:
        return f'guild:{gid}'
    cid = _extract_msg_channel_id(msg)
    if cid:
        return f'channel:{cid}'
    return ''


def _locate_interactive_lottery(msg: Message, allow_single_fallback: bool = False):
    """
    定位当前上下文对应的进行中互动抽奖。
    返回: (scope_key, state)；找不到返回 ('', None)
    """
    scope_key = _interactive_scope_key(msg)
    if scope_key:
        state = _interactive_lotteries.get(scope_key)
        if state:
            return scope_key, state

    guild_id = str(_extract_msg_guild_id(msg) or '')
    channel_id = str(_extract_msg_channel_id(msg) or '')

    if guild_id:
        for key, state in _interactive_lotteries.items():
            if str(state.get('guild_id') or '') == guild_id:
                return key, state

    if channel_id:
        for key, state in _interactive_lotteries.items():
            if str(state.get('channel_id') or '') == channel_id:
                return key, state

    if allow_single_fallback and len(_interactive_lotteries) == 1:
        key, state = next(iter(_interactive_lotteries.items()))
        return key, state

    return '', None


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
    window_start = datetime.utcnow() - timedelta(days=3)
    return (
        WithdrawRequest.query
        .filter(WithdrawRequest.user_id == user_id)
        .filter(WithdrawRequest.created_at >= window_start)
        .filter(~WithdrawRequest.status.in_(['rejected', 'failed']))
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

        pending_db = WithdrawRequest.query.filter_by(user_id=user.id, status='pending').first()
        if pending_db:
            _withdraw_pending_uploads.pop(kook_id, None)
            await msg.reply(f'你有一笔待审核的提现 ({pending_db.amount} 小猪粮)，请等待处理。')
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
            user.m_bean -= amount
            user.m_bean_frozen += amount

            saved_info = _get_saved_withdraw_payment_info(user.id) or {}
            payment_account = str(saved_info.get('payment_account') or '').strip() or '机器人提现(双码)'
            wr = _create_withdraw_request(
                user=user,
                amount=amount,
                payment_account=payment_account,
                payment_image=f'{wechat_image_path}|{alipay_image_path}',
            )
            db.session.commit()
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
        except Exception as e:
            logger.error(f"Error withdraw after dual image upload: {e}")
            db.session.rollback()
            await msg.reply('提现失败，请联系管理员')
            return True


async def _finish_interactive_lottery(scope_key: str, auto: bool = False):
    """结束互动抽奖并发送开奖消息。"""
    state = _interactive_lotteries.get(scope_key)
    if not state:
        return

    participants = [uid for uid in state.get('participants', set()) if uid]
    winner_count = int(state.get('winner_count', 1))
    pick_count = min(winner_count, len(participants))
    winners = random.sample(participants, pick_count) if pick_count > 0 else []

    if auto:
        prefix = '「自动开奖」抽奖已持续30分钟，自动结束！'
    else:
        prefix = '「互动抽奖」抽奖已手动结束！'

    if winners:
        mentions = '\n'.join(f'(met){uid}(met)' for uid in winners)
        extra_tip = f'\n（参与人数不足，实际中奖{len(winners)}位）' if len(winners) < winner_count else ''
        text = (
            f'{prefix}\n'
            f'恭喜一下{winner_count}位用户中奖：\n'
            f'{mentions}{extra_tip}'
        )
    else:
        text = f'{prefix}\n本次无人参与，未产生中奖用户。'

    channel = state.get('channel')
    try:
        if channel:
            await channel.send(text, type=MessageTypes.KMD)
    except Exception as e:
        logger.error(f'发送互动抽奖结果失败: {e}')

    # 清理状态
    _interactive_lotteries.pop(scope_key, None)
    task = _interactive_tasks.pop(scope_key, None)
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()


async def _auto_end_interactive_lottery(scope_key: str, lottery_no: str):
    """30 分钟后自动结束（若期间未被手动结束）。"""
    try:
        await asyncio.sleep(30 * 60)
        state = _interactive_lotteries.get(scope_key)
        if not state or state.get('lottery_no') != lottery_no:
            return
        await _finish_interactive_lottery(scope_key, auto=True)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.error(f'互动抽奖自动结束任务异常: {e}')


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

        if user.role == 'god':
            content = (
                f"**{user.nickname or user.username}** 的钱包\n"
                f"---\n"
                f"VIP等级: **{user.vip_level}**\n"
                f"折扣: {user.vip_discount}%\n"
                f"经验值: {user.experience}\n"
                f"---\n"
                f"嗯呢币: **{user.m_coin}**\n"
                f"赠金: **{user.m_coin_gift}**\n"
                f"合计可用: **{user.m_coin + user.m_coin_gift}** 嗯呢币"
            )
        elif user.role == 'player':
            content = (
                f"**{user.player_nickname or user.nickname or user.username}** 的钱包\n"
                f"---\n"
                f"小猪粮 (可提现): **{user.m_bean}**\n"
                f"冻结小猪粮: **{user.m_bean_frozen}**\n"
                f"---\n"
                f"使用 `/提现 金额` 申请提现"
            )
        else:
            content = (
                f"**{user.nickname or user.username}**\n"
                f"角色: {user.role_name}\n"
                f"嗯呢币: {user.m_coin} | 赠金: {user.m_coin_gift}\n"
                f"小猪粮: {user.m_bean} | 冻结: {user.m_bean_frozen}"
            )

        await msg.reply(content)


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

        pending = WithdrawRequest.query.filter_by(user_id=user.id, status='pending').first()
        if pending:
            await msg.reply(f'你有一笔待审核的提现 ({pending.amount} 小猪粮)，请等待处理')
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

    scope_key = _interactive_scope_key(msg)
    if not scope_key:
        await msg.reply('未获取到频道/服务器信息，请在服务器文字频道中使用该命令')
        return

    # 同一平台上下文仅允许一个进行中的互动抽奖（含兼容回溯匹配）
    _, existing_state = _locate_interactive_lottery(msg, allow_single_fallback=True)
    if existing_state:
        await msg.reply('当前平台已有进行中的互动抽奖，请先使用 `/结束抽奖` 结束后再发布新的。')
        return

    lottery_no = f"{int(time.time() * 1000)}"
    state = {
        'lottery_no': lottery_no,
        'winner_count': winner_count,
        'channel_id': channel_id,
        'guild_id': _extract_msg_guild_id(msg),
        'channel': getattr(getattr(msg, 'ctx', None), 'channel', None),
        # 不默认加入发起人；抽奖期间有实际发言才计入参与
        'participants': set(),
        'created_at': time.time(),
    }
    _interactive_lotteries[scope_key] = state

    # 创建 30 分钟自动结束任务
    _interactive_tasks[scope_key] = asyncio.create_task(_auto_end_interactive_lottery(scope_key, lottery_no))

    await msg.reply(
        f"「互动抽奖」互动抽奖已经发起啦，本次中奖人数为：{winner_count}人，\n"
        f"在本频道使用`/结束抽奖`命令来结束本次抽奖。\n"
        f"或者在30分钟后自动结束。",
        use_quote=False,
        type=MessageTypes.KMD,
    )


@bot.command(name='结束抽奖')
async def end_lottery_cmd(msg: Message):
    """
    提前结束当前频道抽奖并立即开奖
    用法: /结束抽奖
    """
    channel_id = _extract_msg_channel_id(msg)
    if not channel_id:
        await msg.reply('未获取到频道 ID，请在服务器文字频道中使用该命令')
        return

    scope_key, state = _locate_interactive_lottery(msg, allow_single_fallback=True)
    if not state:
        await msg.reply('当前平台没有进行中的互动抽奖')
        return

    # 要求在发布抽奖的同一频道结束（避免跨频道误结束）
    if str(state.get('channel_id') or '') != str(channel_id):
        await msg.reply('请在发起抽奖的那个频道使用 `/结束抽奖`。')
        return

    await _finish_interactive_lottery(scope_key, auto=False)


def _build_help_text():
    content = (
        "**嗯呢呗电竞机器人 命令列表**\n"
        "---\n"
        "`/bind` - 查看当前自动识别的账号\n"
        "`/钱包` - 查看钱包信息\n"
        "`/转换 金额` - 将小猪金(小猪粮)按1:1转换为嗯呢币\n"
        "`/结单 订单号 时长` - 结单申报(仅支持整数或0.5小时)\n"
        "`/确认 订单号` - 确认订单(老板)\n"
        "`/roll 总点数 抽几个点` - 掷点/随机点数\n"
        "`/发布抽奖 中奖人数` - 全员可用，发起互动抽奖(30分钟自动开奖)\n"
        "`/结束抽奖` - 结束当前互动抽奖并立即开奖\n"
        "`/提现 [金额]` - 申请提现(无金额会弹网页入口；需微信+支付宝收款码)\n"
        "`/取消提现` - 取消待上传收款码的提现\n"
        "`/帮助` 或 `/help` - 查看此帮助\n"
        "`/ping` - 测试机器人"
    )
    return content


@bot.command(name='帮助')
async def help_cmd(msg: Message):
    """帮助命令（中文）"""
    await msg.reply(_build_help_text())


@bot.command(name='help')
async def help_en_cmd(msg: Message):
    """帮助命令（英文）"""
    await msg.reply(_build_help_text())


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


# ─── 事件处理器 ──────────────────────────────────────────────

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

        _, state = _locate_interactive_lottery(msg, allow_single_fallback=False)
        if not state:
            return

        # 仅统计抽奖发起频道内的发言，避免跨频道误参与
        msg_channel_id = str(_extract_msg_channel_id(msg) or '')
        lottery_channel_id = str(state.get('channel_id') or '')
        if not msg_channel_id or msg_channel_id != lottery_channel_id:
            return

        uid = str(getattr(msg, 'author_id', '') or getattr(getattr(msg, 'author', None), 'id', '') or '')
        if not uid:
            return
        state['participants'].add(uid)
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
