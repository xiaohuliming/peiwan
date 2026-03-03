from datetime import datetime
from app.extensions import db

class BalanceLog(db.Model):
    __tablename__ = 'balance_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    change_type = db.Column(db.String(20), nullable=False) # recharge, consume, gift_send, refund, admin_adjust
    amount = db.Column(db.Numeric(12, 2), nullable=False) # 变动金额 (+/-)
    balance_after = db.Column(db.Numeric(12, 2), nullable=False) # 变动后余额
    
    reason = db.Column(db.String(255))
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id')) # 操作人 (如果是管理员变账)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='balance_logs')

class CommissionLog(db.Model):
    __tablename__ = 'commission_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    change_type = db.Column(db.String(20), nullable=False) # order_income, gift_income, withdraw, refund_deduct
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    balance_after = db.Column(db.Numeric(12, 2), nullable=False)
    
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id')) # 关联订单
    reason = db.Column(db.String(255))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='commission_logs')
    order = db.relationship('Order', backref='commission_logs')

class WithdrawRequest(db.Model):
    __tablename__ = 'withdraw_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    amount = db.Column(db.Numeric(12, 2), nullable=False) # 提现金额
    payment_method = db.Column(db.String(50), default='wechat') # wechat, alipay
    payment_account = db.Column(db.String(100)) # 收款账号
    payment_image = db.Column(db.String(500)) # 收款码图片
    
    status = db.Column(db.String(20), default='pending', index=True) # pending, approved, rejected, paid
    
    audit_remark = db.Column(db.String(255)) # 审核备注
    auditor_id = db.Column(db.Integer, db.ForeignKey('users.id')) # 审核人
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    audit_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='withdraw_requests')
    auditor = db.relationship('User', foreign_keys=[auditor_id], backref='reviewed_withdrawals')
