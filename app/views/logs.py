from flask import Blueprint, render_template, request
from flask_login import login_required

from app.models.operation_log import OperationLog
from app.models.user import User
from app.utils.permissions import admin_required

logs_bp = Blueprint('logs', __name__, template_folder='../templates')


@logs_bp.route('/')
@login_required
@admin_required
def index():
    page = request.args.get('page', 1, type=int)
    action_type = request.args.get('action_type', '').strip()
    operator_name = request.args.get('operator_name', '').strip()

    query = OperationLog.query
    if action_type:
        query = query.filter(OperationLog.action_type == action_type)
    if operator_name:
        query = query.join(User, OperationLog.operator_id == User.id).filter(
            User.nickname.contains(operator_name)
        )

    logs = query.order_by(OperationLog.created_at.desc()).paginate(page=page, per_page=30)

    # 收集所有 action_type 用于筛选下拉框
    action_types = [r[0] for r in OperationLog.query.with_entities(
        OperationLog.action_type).distinct().all()]

    return render_template('admin/logs.html',
                           logs=logs,
                           action_type=action_type,
                           operator_name=operator_name,
                           action_types=sorted(action_types))
