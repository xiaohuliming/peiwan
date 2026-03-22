from datetime import datetime
from app.extensions import db


class Gift(db.Model):
    """礼物配置表"""
    __tablename__ = 'gifts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    image = db.Column(db.String(500))
    status = db.Column(db.Boolean, default=True)  # 开启/关闭
    gift_type = db.Column(db.String(20), default='standard')  # standard/crown (标准/冠名)
    broadcast_template = db.Column(db.Text)  # 播报模板, 支持变量替换
    crown_broadcast_template = db.Column(db.Text)  # 冠名礼物播报模板, 优先于通用礼物模板
    sort_order = db.Column(db.Integer, default=0, nullable=False, index=True)  # 列表排序(越小越靠前)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)  # 软删除时间(非空=已删除)
    sender_kook_role_id = db.Column(db.String(50), nullable=True)    # 赠送人获得的KOOK标签ID
    receiver_kook_role_id = db.Column(db.String(50), nullable=True)  # 被赠送人获得的KOOK标签ID

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    orders = db.relationship('GiftOrder', backref='gift', lazy='dynamic')

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def __repr__(self):
        return f'<Gift {self.name}>'


class GiftOrder(db.Model):
    """礼物订单表"""
    __tablename__ = 'gift_orders'

    id = db.Column(db.Integer, primary_key=True)

    boss_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    gift_id = db.Column(db.Integer, db.ForeignKey('gifts.id'), nullable=False, index=True)

    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), default=0)  # 单价(来自Gift.price)
    total_price = db.Column(db.Numeric(10, 2), default=0)  # 总价 = unit_price * quantity

    # 分成
    commission_rate = db.Column(db.Numeric(5, 2), default=80)  # 佣金比例%
    player_earning = db.Column(db.Numeric(10, 2), default=0)   # 陪玩收益
    shop_earning = db.Column(db.Numeric(10, 2), default=0)     # 平台营收

    # 老板支付拆分（用于原路退款）
    boss_paid_coin = db.Column(db.Numeric(10, 2), default=0)   # 从嗯呢币支付的部分
    boss_paid_gift = db.Column(db.Numeric(10, 2), default=0)   # 从赠金支付的部分

    # 状态
    status = db.Column(db.String(20), default='paid', index=True)  # paid/refunded
    freeze_status = db.Column(db.String(20), default='normal')  # normal/frozen

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    refund_time = db.Column(db.DateTime)

    # Relationships
    boss = db.relationship('User', foreign_keys=[boss_id], backref='gift_orders_as_boss')
    player = db.relationship('User', foreign_keys=[player_id], backref='gift_orders_as_player')
    staff = db.relationship('User', foreign_keys=[staff_id], backref='gift_orders_as_staff')

    @property
    def status_label(self):
        labels = {
            'paid': '已完成',
            'refunded': '已退款',
        }
        return labels.get(self.status, self.status)

    @property
    def is_frozen(self):
        return self.freeze_status == 'frozen'

    def __repr__(self):
        return f'<GiftOrder {self.id}>'
