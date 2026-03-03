"""
数据导出服务 (基于 openpyxl)
"""
import io
from datetime import datetime

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from app.models.user import User
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.finance import WithdrawRequest
from app.models.clock import ClockRecord


def _style_header(ws, headers):
    """样式化表头"""
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='7C3AED', end_color='7C3AED', fill_type='solid')
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[cell.column_letter].width = max(len(str(h)) * 2, 12)


def export_users(query=None):
    """导出用户列表"""
    if not HAS_OPENPYXL:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = '用户列表'
    headers = ['ID', '用户名', '昵称', '陪玩昵称', 'KOOK ID', '角色', '嗯呢币', '赠金', '小猪粮', '冻结小猪粮',
               '经验值', 'VIP等级', '注册时间']
    _style_header(ws, headers)

    users = query.all() if query else User.query.all()
    for i, u in enumerate(users, 2):
        ws.cell(row=i, column=1, value=u.id)
        ws.cell(row=i, column=2, value=u.username)
        ws.cell(row=i, column=3, value=u.nickname)
        ws.cell(row=i, column=4, value=u.player_nickname)
        ws.cell(row=i, column=5, value=u.kook_id)
        ws.cell(row=i, column=6, value=u.role_name)
        ws.cell(row=i, column=7, value=float(u.m_coin))
        ws.cell(row=i, column=8, value=float(u.m_coin_gift))
        ws.cell(row=i, column=9, value=float(u.m_bean))
        ws.cell(row=i, column=10, value=float(u.m_bean_frozen))
        ws.cell(row=i, column=11, value=u.experience)
        ws.cell(row=i, column=12, value=u.vip_level)
        ws.cell(row=i, column=13, value=u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else '')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_orders(query=None):
    """导出订单列表"""
    if not HAS_OPENPYXL:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = '订单列表'
    headers = ['订单号', '老板', '陪玩', '项目', '时长', '总价', '陪玩收益', '平台收入',
               '状态', '冻结', '创建时间', '客服']
    _style_header(ws, headers)

    orders = query.all() if query else Order.query.all()
    for i, o in enumerate(orders, 2):
        ws.cell(row=i, column=1, value=o.order_no)
        ws.cell(row=i, column=2, value=o.boss.nickname if o.boss else '')
        ws.cell(row=i, column=3, value=(o.player.player_nickname or o.player.nickname) if o.player else '')
        ws.cell(row=i, column=4, value=o.project_display)
        ws.cell(row=i, column=5, value=float(o.duration or 0))
        ws.cell(row=i, column=6, value=float(o.total_price or 0))
        ws.cell(row=i, column=7, value=float(o.player_earning or 0))
        ws.cell(row=i, column=8, value=float(o.shop_earning or 0))
        ws.cell(row=i, column=9, value=o.status_label)
        ws.cell(row=i, column=10, value='是' if o.is_frozen else '否')
        ws.cell(row=i, column=11, value=o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else '')
        ws.cell(row=i, column=12, value=o.staff.staff_display_name if o.staff else '')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_gift_orders(query=None):
    """导出礼物记录"""
    if not HAS_OPENPYXL:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = '礼物记录'
    headers = ['ID', '老板', '陪玩', '礼物', '数量', '总价', '陪玩收益', '状态', '时间', '客服']
    _style_header(ws, headers)

    records = query.all() if query else GiftOrder.query.all()
    for i, g in enumerate(records, 2):
        ws.cell(row=i, column=1, value=g.id)
        ws.cell(row=i, column=2, value=g.boss.nickname if g.boss else '')
        ws.cell(row=i, column=3, value=(g.player.player_nickname or g.player.nickname) if g.player else '')
        ws.cell(row=i, column=4, value=g.gift.name if g.gift else '')
        ws.cell(row=i, column=5, value=g.quantity)
        ws.cell(row=i, column=6, value=float(g.total_price))
        ws.cell(row=i, column=7, value=float(g.player_earning))
        ws.cell(row=i, column=8, value=g.status)
        ws.cell(row=i, column=9, value=g.created_at.strftime('%Y-%m-%d %H:%M') if g.created_at else '')
        ws.cell(row=i, column=10, value=g.staff.staff_display_name if g.staff else '')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_withdrawals(query=None):
    """导出提现记录"""
    if not HAS_OPENPYXL:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = '提现记录'
    headers = ['ID', '用户', '金额', '状态', '申请时间', '审批人', '审批时间', '备注']
    _style_header(ws, headers)

    records = query.all() if query else WithdrawRequest.query.all()
    for i, w in enumerate(records, 2):
        ws.cell(row=i, column=1, value=w.id)
        ws.cell(row=i, column=2, value=w.user.nickname if w.user else '')
        ws.cell(row=i, column=3, value=float(w.amount))
        ws.cell(row=i, column=4, value=w.status)
        ws.cell(row=i, column=5, value=w.created_at.strftime('%Y-%m-%d %H:%M') if w.created_at else '')
        ws.cell(row=i, column=6, value=w.auditor.nickname if w.auditor else '')
        ws.cell(row=i, column=7, value=w.audit_at.strftime('%Y-%m-%d %H:%M') if w.audit_at else '')
        ws.cell(row=i, column=8, value=w.audit_remark or '')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_clock_records(query=None):
    """导出打卡记录"""
    if not HAS_OPENPYXL:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = '打卡记录'
    headers = ['ID', '用户', '上班时间', '下班时间', '时长(小时)', '状态']
    _style_header(ws, headers)

    records = query.all() if query else ClockRecord.query.all()
    for i, c in enumerate(records, 2):
        ws.cell(row=i, column=1, value=c.id)
        ws.cell(row=i, column=2, value=c.user.nickname if c.user else '')
        ws.cell(row=i, column=3, value=c.clock_in.strftime('%Y-%m-%d %H:%M') if c.clock_in else '')
        ws.cell(row=i, column=4, value=c.clock_out.strftime('%Y-%m-%d %H:%M') if c.clock_out else '')
        ws.cell(row=i, column=5, value=round((c.duration_minutes or 0) / 60, 2))
        ws.cell(row=i, column=6, value=c.status or '')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
