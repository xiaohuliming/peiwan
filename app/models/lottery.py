from datetime import datetime
from app.extensions import db


class Lottery(db.Model):
    """抽奖活动"""
    __tablename__ = 'lotteries'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    prize = db.Column(db.String(500), nullable=False)
    winner_count = db.Column(db.Integer, nullable=False, default=1)

    channel_id = db.Column(db.String(100), nullable=False)
    kook_msg_id = db.Column(db.String(100))
    emoji = db.Column(db.String(50), default='🎉')

    eligible_roles = db.Column(db.Text)       # JSON list: ["god", "player", ...]  空=不限
    min_vip_level = db.Column(db.String(50))   # 最低 VIP 等级名称，空=不限

    draw_time = db.Column(db.DateTime, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    rigged_user_ids = db.Column(db.Text)       # JSON list: [1, 2, ...]

    # pending → published → drawn / cancelled
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by], backref='lotteries')
    winners = db.relationship('LotteryWinner', backref='lottery', lazy='dynamic',
                              cascade='all, delete-orphan')

    @property
    def status_label(self):
        return {
            'pending': '待发布',
            'published': '已发布',
            'drawn': '已开奖',
            'cancelled': '已取消',
        }.get(self.status, self.status)

    def get_rigged_ids(self):
        import json
        if not self.rigged_user_ids:
            return []
        try:
            return json.loads(self.rigged_user_ids)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_eligible_roles(self):
        import json
        if not self.eligible_roles:
            return []
        try:
            return json.loads(self.eligible_roles)
        except (json.JSONDecodeError, TypeError):
            return []

    def __repr__(self):
        return f'<Lottery {self.id} {self.title}>'


class LotteryWinner(db.Model):
    """抽奖中奖记录"""
    __tablename__ = 'lottery_winners'

    id = db.Column(db.Integer, primary_key=True)
    lottery_id = db.Column(db.Integer, db.ForeignKey('lotteries.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    kook_id = db.Column(db.String(50), nullable=False)
    is_rigged = db.Column(db.Boolean, default=False)
    notified = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='lottery_wins')

    def __repr__(self):
        return f'<LotteryWinner lottery={self.lottery_id} kook={self.kook_id}>'
