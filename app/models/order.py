from datetime import datetime
from app.extensions import db


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # 关联用户
    boss_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)   # 老板
    player_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)  # 陪玩
    staff_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)                   # 派单客服

    # 关联项目
    project_item_id = db.Column(db.Integer, db.ForeignKey('project_items.id'), index=True)

    # 定价信息
    price_tier = db.Column(db.String(20))                      # casual/tech/god/peak/devil(兼容pro)
    base_price = db.Column(db.Numeric(10, 2), default=0)       # 基础单价
    extra_price = db.Column(db.Numeric(10, 2), default=0)      # 补充单价
    addon_desc = db.Column(db.String(200))                     # 附加项目描述
    addon_price = db.Column(db.Numeric(10, 2), default=0)      # 附加项目价格
    boss_discount = db.Column(db.Numeric(5, 2), default=100)   # 老板折扣 (100=无折扣)
    total_price = db.Column(db.Numeric(10, 2), default=0)      # 订单总额

    # 分成信息
    commission_rate = db.Column(db.Numeric(5, 2), default=80)  # 佣金比例%
    player_earning = db.Column(db.Numeric(10, 2), default=0)   # 陪玩收益 (小猪粮)
    shop_earning = db.Column(db.Numeric(10, 2), default=0)     # 平台营收

    # 订单类型与时长
    order_type = db.Column(db.String(20), default='normal')    # normal/escort/training
    duration = db.Column(db.Numeric(10, 2), default=0)         # 时长(小时)或局数

    # 状态
    status = db.Column(db.String(20), default='pending_report', index=True)
    # pending_report → pending_confirm → pending_pay → paid → refunded
    freeze_status = db.Column(db.String(20), default='normal')  # normal/frozen

    remark = db.Column(db.String(500))

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    fill_time = db.Column(db.DateTime)        # 陪玩开始时间
    report_time = db.Column(db.DateTime)      # 申报时间
    confirm_time = db.Column(db.DateTime)     # 确认时间
    pay_time = db.Column(db.DateTime)         # 支付/结算时间
    refund_time = db.Column(db.DateTime)      # 退款时间
    auto_confirm_at = db.Column(db.DateTime)  # 自动确认截止时间

    # Relationships
    boss = db.relationship('User', foreign_keys=[boss_id], backref='boss_orders')
    player = db.relationship('User', foreign_keys=[player_id], backref='player_orders')
    staff = db.relationship('User', foreign_keys=[staff_id], backref='staff_orders')
    project_item = db.relationship('ProjectItem', backref='orders')

    @property
    def project_display(self):
        """显示游戏项目名"""
        if self.project_item:
            return f"{self.project_item.project.name} - {self.project_item.name}"
        return '未知项目'

    @property
    def game_name(self):
        """获取游戏名"""
        if self.project_item:
            return self.project_item.project.name
        return '未知'

    @property
    def item_name(self):
        """获取子项目名"""
        if self.project_item:
            return self.project_item.name
        return '未知'

    @property
    def status_label(self):
        labels = {
            'pending_report': '待申报',
            'pending_confirm': '待确认',
            'pending_pay': '待结算',
            'paid': '已结算',
            'refunded': '已退款',
        }
        return labels.get(self.status, self.status)

    @property
    def status_color(self):
        colors = {
            'pending_report': 'orange',
            'pending_confirm': 'blue',
            'pending_pay': 'purple',
            'paid': 'green',
            'refunded': 'red',
        }
        return colors.get(self.status, 'gray')

    @property
    def is_frozen(self):
        return self.freeze_status == 'frozen'

    def __repr__(self):
        return f'<Order {self.order_no}>'
