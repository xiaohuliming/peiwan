"""
AI 助理小呢 — SiliconFlow MiniMax-M2.5 对接服务
"""
import json
import requests
from decimal import Decimal
from datetime import datetime, timedelta
from flask import current_app
from flask_login import current_user

from app.extensions import db
from app.models.user import User
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.finance import WithdrawRequest
from app.services.assistant_queries import detect_and_query

SILICONFLOW_API_URL = 'https://api.siliconflow.cn/v1/chat/completions'
SILICONFLOW_API_KEY = 'sk-obelmguwyjrhsifohvmryzgsknvmkaodwcclznhyqnyecqwi'
SILICONFLOW_MODEL = 'Pro/MiniMaxAI/MiniMax-M2.5'


def _build_system_prompt(user):
    """构建包含平台上下文的系统提示词（按权限区分）"""
    # 角色检测顺序: 高级管理 > 管理 > 客服 > 老板 > 陪玩 > 用户
    if user.is_superadmin:
        role_label = '高级管理'
    elif user.is_admin:
        role_label = '管理员'
    elif user.has_role('staff'):
        role_label = '客服'
    elif user.is_god:
        role_label = '老板'
    elif user.is_player:
        role_label = '陪玩'
    else:
        role_label = '用户'

    display_name = user.nickname or user.username
    user_code = getattr(user, 'user_code', '') or ''

    base = f"""你是"助理小呢"，嗯呢呗电竞陪玩店的智能助理。你性格温柔可爱、专业靠谱。
当前用户: {display_name} (角色: {role_label}, 编号: {user_code}, ID: {user.id})

平台介绍:
- 嗯呢呗电竞是一个基于KOOK的游戏陪玩店中控管理系统
- 支持常规陪玩、护航、代练三种订单类型
- 老板通过充值嗯呢币下单，陪玩通过接单赚取小猪粮

回答规则:
- 用中文简洁回复，善用emoji让回复更生动
- 数据查询时给出准确数字
- 如果问到你无法确定的数据，诚实说明
- 不要编造数据

重要: 你没有任何工具(tool)或函数调用(function call)能力。不要输出任何XML标签、tool_call或函数调用格式。所有需要的数据已在下方上下文中提供，直接基于这些数据用自然语言回答。

严格禁止输出以下格式:
- <minimax:tool_call> 或任何类似的XML标签
- <invoke> 或 <parameter> 标签
- 任何 tool_call、function_call 格式
你的回复必须是纯自然语言文本，不包含任何XML或代码调用格式。如果上下文中没有相关数据，就直接说"这个信息我暂时无法查到"。"""

    # 按角色添加权限说明
    if user.is_admin or user.has_role('staff'):
        base += """

你的权限: 完整平台数据访问
你可以帮助:
1. 查询平台整体数据（用户数、订单统计、财务概况、待处理事项等）
2. 查询任意用户信息和订单详情
3. 解答运营问题、提供运营建议
4. 解释平台功能和操作流程"""
    elif user.is_god:
        base += """

你的权限: 仅限当前用户个人数据
你可以帮助:
1. 查询当前用户的余额、订单记录
2. 解答下单、充值等使用问题
3. 介绍平台功能

严格禁止:
- 不可透露平台总用户数、总订单数等整体运营数据
- 不可透露其他用户的信息
- 如果用户询问平台整体数据，礼貌告知"抱歉，这些信息仅管理人员可查看哦~" """
    elif user.is_player:
        base += """

你的权限: 仅限当前用户个人数据
你可以帮助:
1. 查询当前用户的收益、提现记录
2. 解答接单、提现等使用问题
3. 介绍平台功能

严格禁止:
- 不可透露平台总用户数、总订单数等整体运营数据
- 不可透露其他用户的信息
- 如果用户询问平台整体数据，礼貌告知"抱歉，这些信息仅管理人员可查看哦~" """
    else:
        base += """

你的权限: 仅公开信息
你可以帮助:
1. 解答平台使用问题
2. 介绍平台功能
严格禁止透露任何平台内部数据。"""

    return base


def _get_platform_context(user):
    """获取平台实时数据作为上下文（按权限区分）"""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    context_parts = []

    try:
        # 管理员/客服: 基础概览数据（详细查询由意图系统处理）
        if user.is_admin or user.has_role('staff'):
            total_users = User.query.count()
            total_orders = Order.query.filter(Order.status == 'paid').count()
            today_count = Order.query.filter(
                Order.created_at >= today_start
            ).count()
            pending_orders = Order.query.filter(Order.status.in_(['pending_report', 'pending_confirm'])).count()
            frozen_orders = Order.query.filter(Order.freeze_status == 'frozen', Order.status == 'paid').count()
            pending_withdraws = WithdrawRequest.query.filter_by(status='pending').count()

            context_parts.append(f"""📊 平台概览:
- 总用户数: {total_users}
- 已完成订单: {total_orders}
- 今日订单: {today_count}
- 待处理订单: {pending_orders}
- 冻结中订单: {frozen_orders}
- 待审提现: {pending_withdraws}""")

        # 老板: 仅个人余额和订单数
        if user.is_god:
            my_orders = Order.query.filter_by(boss_id=user.id, status='paid').count()
            context_parts.append(f"""💰 你的账户信息:
- 嗯呢币: {user.m_coin}
- 赠金: {user.m_coin_gift}
- 历史订单数: {my_orders}""")

        # 陪玩: 仅个人收益和订单数
        elif user.is_player:
            my_orders = Order.query.filter_by(player_id=user.id, status='paid').count()
            context_parts.append(f"""💰 你的账户信息:
- 小猪粮: {user.m_bean}
- 冻结小猪粮: {user.m_bean_frozen}
- 已完成订单数: {my_orders}""")

    except Exception as e:
        current_app.logger.warning(f'[Assistant] 获取平台数据失败: {e}')
        context_parts.append('(数据暂时无法获取)')

    return '\n'.join(context_parts)


def chat(user_message, conversation_history=None):
    """
    调用 SiliconFlow API 进行对话
    conversation_history: [{"role": "user/assistant", "content": "..."}]
    返回: (success, reply_text, error_msg)
    """
    user = current_user._get_current_object()

    system_prompt = _build_system_prompt(user)
    platform_context = _get_platform_context(user)

    # 意图识别: 根据用户消息自动查询相关数据
    query_results = detect_and_query(user, user_message)
    if query_results:
        platform_context += '\n' + query_results

    messages = [
        {'role': 'system', 'content': system_prompt + '\n\n' + platform_context}
    ]

    # 加入对话历史（最多保留最近 10 轮）
    if conversation_history:
        messages.extend(conversation_history[-20:])

    messages.append({'role': 'user', 'content': user_message})

    try:
        resp = requests.post(
            SILICONFLOW_API_URL,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {SILICONFLOW_API_KEY}',
            },
            json={
                'model': SILICONFLOW_MODEL,
                'messages': messages,
                'max_tokens': 2048,
                'temperature': 0.7,
                'top_p': 0.9,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            current_app.logger.error(f'[Assistant] API error {resp.status_code}: {resp.text[:500]}')
            return False, None, f'AI 服务暂时不可用 (HTTP {resp.status_code})'

        data = resp.json()
        reply = data['choices'][0]['message']['content']

        # 后处理: 去除模型可能输出的 XML tool_call 标签
        import re
        reply = re.sub(r'</?minimax:[^>]*>', '', reply)
        reply = re.sub(r'</?invoke[^>]*>', '', reply)
        reply = re.sub(r'</?parameter[^>]*>', '', reply)
        reply = re.sub(r'</?tool_call[^>]*>', '', reply)
        reply = reply.strip()

        if not reply:
            reply = '让我看看... 这个信息我暂时无法查到，请换个方式问问我哦~'

        return True, reply, None

    except requests.Timeout:
        return False, None, '请求超时，请稍后重试 ⏳'
    except Exception as e:
        current_app.logger.error(f'[Assistant] Unexpected error: {e}')
        return False, None, '助理出了点小问题，请稍后再试 😢'
