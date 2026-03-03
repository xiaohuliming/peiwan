from datetime import datetime
from app.extensions import db


class OperationLog(db.Model):
    """后台操作日志"""
    __tablename__ = 'operation_logs'

    id = db.Column(db.Integer, primary_key=True)
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    action_type = db.Column(db.String(50), nullable=False, index=True)
    # 常见 action_type:
    # order_freeze, order_unfreeze, order_dispatch, order_delete, order_refund
    # balance_recharge, balance_deduct, balance_gift
    # gift_send, gift_freeze, gift_unfreeze, gift_refund
    # user_role_change, user_password_reset, user_delete
    # withdraw_approve, withdraw_reject
    # intimacy_clear

    target_type = db.Column(db.String(50))   # user / order / gift_order / withdraw 等
    target_id = db.Column(db.Integer)         # 目标对象 ID
    detail = db.Column(db.Text)               # 操作详情描述

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    operator = db.relationship('User', foreign_keys=[operator_id], backref='operation_logs')

    def __repr__(self):
        return f'<OperationLog {self.action_type} by {self.operator_id}>'
