"""数据导出路由"""
from datetime import datetime
from flask import Blueprint, send_file, flash, redirect, url_for, render_template, request
from flask_login import login_required

from app.utils.permissions import admin_required
from app.services import export_service
from app.models.user import User
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.finance import WithdrawRequest
from app.models.clock import ClockRecord

export_bp = Blueprint('export', __name__, template_folder='../templates')


def _send_excel(output, filename):
    if output is None:
        flash('导出失败，请安装 openpyxl: pip install openpyxl', 'error')
        return redirect(url_for('dashboard.index'))
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)


@export_bp.route('/all', methods=['GET', 'POST'])
@login_required
@admin_required
def export_all():
    if request.method == 'GET':
        return render_template(
            'export/all.html',
            section_options=export_service.EXPORT_SECTION_OPTIONS,
            selected_sections=[item['key'] for item in export_service.EXPORT_SECTION_OPTIONS],
        )

    selected_sections = request.form.getlist('sections')
    if not selected_sections:
        flash('请至少勾选一项导出内容', 'error')
        return redirect(url_for('export.export_all'))

    date_from = request.form.get('date_from', '').strip()
    date_to = request.form.get('date_to', '').strip()

    output = export_service.export_all_tables_workbook(
        include_sections=selected_sections,
        date_from=date_from or None,
        date_to=date_to or None,
    )

    date_suffix = ''
    if date_from or date_to:
        date_suffix = f'_{date_from or ""}至{date_to or ""}'
    return _send_excel(output, f'数据导出{date_suffix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')


@export_bp.route('/users')
@login_required
@admin_required
def export_users():
    output = export_service.export_users(User.query)
    return _send_excel(output, f'用户列表_{datetime.now().strftime("%Y%m%d")}.xlsx')


@export_bp.route('/orders')
@login_required
@admin_required
def export_orders():
    output = export_service.export_orders(Order.query.order_by(Order.created_at.desc()))
    return _send_excel(output, f'订单列表_{datetime.now().strftime("%Y%m%d")}.xlsx')


@export_bp.route('/gifts')
@login_required
@admin_required
def export_gifts():
    output = export_service.export_gift_orders(GiftOrder.query.order_by(GiftOrder.created_at.desc()))
    return _send_excel(output, f'礼物记录_{datetime.now().strftime("%Y%m%d")}.xlsx')


@export_bp.route('/withdrawals')
@login_required
@admin_required
def export_withdrawals():
    output = export_service.export_withdrawals(WithdrawRequest.query.order_by(WithdrawRequest.created_at.desc()))
    return _send_excel(output, f'提现记录_{datetime.now().strftime("%Y%m%d")}.xlsx')


@export_bp.route('/clock')
@login_required
@admin_required
def export_clock():
    output = export_service.export_clock_records(ClockRecord.query.order_by(ClockRecord.clock_in.desc()))
    return _send_excel(output, f'打卡记录_{datetime.now().strftime("%Y%m%d")}.xlsx')
