"""
KOOK Bot 推送服务
所有推送函数都接收 bot 实例用于发送消息
"""
import logging

logger = logging.getLogger(__name__)


async def _send_text(bot, channel_id, text):
    """向指定频道发送普通消息"""
    try:
        ch = await bot.client.fetch_public_channel(channel_id)
        await ch.send(text)
    except Exception as e:
        logger.error(f'推送失败 channel={channel_id}: {e}')


def _build_card(title, content, color='#7C3AED'):
    """构建普通消息文本"""
    if title:
        return f'**{title}**\n{content}'
    return content


async def push_order_dispatch(bot, channel_id, order):
    """新订单派单通知"""
    content = (
        f"**新订单来啦!**\n"
        f"订单号: `{order.order_no}`\n"
        f"老板: {order.boss.nickname or order.boss.username}\n"
        f"陪玩: {order.player.player_nickname or order.player.nickname}\n"
        f"项目: {order.project_display}\n"
    )
    card = _build_card('📋 新订单通知', content, '#7C3AED')
    await _send_text(bot, channel_id, card)


async def push_order_report(bot, channel_id, order):
    """订单申报通知"""
    content = (
        f"订单号: `{order.order_no}`\n"
        f"陪玩: {order.player.player_nickname or order.player.nickname}\n"
        f"时长: {order.duration}h\n"
        f"金额: {order.total_price} 嗯呢币\n"
        f"24h后自动确认"
    )
    card = _build_card('⏰ 订单已申报', content, '#3B82F6')
    await _send_text(bot, channel_id, card)


async def push_order_confirm(bot, channel_id, order):
    """订单确认通知"""
    content = (
        f"订单号: `{order.order_no}`\n"
        f"金额: {order.total_price} 嗯呢币\n"
        f"陪玩收益: {order.player_earning} 小猪粮 已到账"
    )
    card = _build_card('✅ 订单已确认', content, '#10B981')
    await _send_text(bot, channel_id, card)


async def push_gift_send(bot, channel_id, gift_order):
    """赠送礼物通知"""
    content = (
        f"**{gift_order.boss.nickname or gift_order.boss.username}** 送给 "
        f"**{gift_order.player.player_nickname or gift_order.player.nickname}**\n"
        f"礼物: {gift_order.gift.name} x{gift_order.quantity}\n"
        f"总价: {gift_order.total_price} 嗯呢币"
    )
    card = _build_card('🎁 礼物播报', content, '#EC4899')
    await _send_text(bot, channel_id, card)


async def push_upgrade(bot, channel_id, user, from_level, to_level):
    """VIP升级播报"""
    content = (
        f"恭喜 **{user.nickname or user.username}**\n"
        f"等级升级: {from_level} → **{to_level}**\n"
        f"当前经验: {user.experience}"
    )
    card = _build_card('🎉 等级升级', content, '#F59E0B')
    await _send_text(bot, channel_id, card)


async def push_recharge_broadcast(bot, channel_id, user, amount, template=None):
    """充值播报"""
    if template:
        content = template.replace('{user}', user.nickname or user.username).replace('{amount}', str(amount))
    else:
        content = f"**{user.nickname or user.username}** 充值了 **{amount}** 嗯呢币"
    card = _build_card('💰 充值播报', content, '#10B981')
    await _send_text(bot, channel_id, card)
