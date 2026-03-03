from datetime import datetime
from app.extensions import db


class VipLevel(db.Model):
    """VIP等级配置表"""
    __tablename__ = 'vip_levels'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # GOD, VIP1, VIP2, 总裁sama 等
    min_experience = db.Column(db.Integer, nullable=False, default=0)  # 升级所需最低经验值
    discount = db.Column(db.Numeric(5, 2), default=100.00)  # 折扣 (100=无折扣, 95=95折)
    sort_order = db.Column(db.Integer, default=0)  # 排序, 数值越小等级越低
    benefits = db.Column(db.Text)  # JSON: 权益描述列表

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<VipLevel {self.name}>'


class UpgradeRecord(db.Model):
    """用户升级记录表"""
    __tablename__ = 'upgrade_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    from_level = db.Column(db.String(50))  # 升级前等级
    to_level = db.Column(db.String(50))    # 升级后等级

    benefit_status = db.Column(db.String(20), default='pending')  # pending / granted
    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # 确认发放权益的客服/管理员
    granted_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='upgrade_records')
    granter = db.relationship('User', foreign_keys=[granted_by])

    @property
    def benefit_status_label(self):
        labels = {
            'pending': '待发放',
            'granted': '已发放',
        }
        return labels.get(self.benefit_status, self.benefit_status)

    def __repr__(self):
        return f'<UpgradeRecord user={self.user_id} {self.from_level} → {self.to_level}>'
