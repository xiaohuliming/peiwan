from app.extensions import db
from app.models.operation_log import OperationLog
from app.models.user import User


def _resolve_operator_id(operator_id):
    """解析并兜底有效操作人ID，避免外键失败影响业务。"""
    uid = None
    try:
        if operator_id is not None:
            uid = int(operator_id)
    except Exception:
        uid = None

    if uid and db.session.get(User, uid):
        return uid

    # 优先管理员
    admin = User.query.filter(User.role.in_(['admin', 'superadmin'])).order_by(User.id.asc()).first()
    if admin:
        return admin.id

    # 其次任意有效用户
    any_user = User.query.order_by(User.id.asc()).first()
    if any_user:
        return any_user.id

    return None


def log_operation(operator_id, action_type, target_type=None, target_id=None, detail=None):
    """记录后台操作日志"""
    resolved_operator_id = _resolve_operator_id(operator_id)
    if not resolved_operator_id:
        return

    log = OperationLog(
        operator_id=resolved_operator_id,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.session.add(log)
