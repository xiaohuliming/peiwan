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
    lottery_mode = db.Column(db.String(20), default='reaction', nullable=False, index=True)

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
    participants = db.relationship('LotteryParticipant', backref='lottery', lazy='dynamic',
                                   cascade='all, delete-orphan')
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

    @property
    def is_interactive(self):
        return self.lottery_mode == 'interactive'

    @property
    def mode_label(self):
        return {
            'reaction': '卡片抽奖',
            'interactive': '互动抽奖',
        }.get(self.lottery_mode, self.lottery_mode or '-')

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


class LotteryParticipant(db.Model):
    """互动抽奖参与记录"""
    __tablename__ = 'lottery_participants'
    __table_args__ = (
        db.UniqueConstraint('lottery_id', 'kook_id', name='uq_lottery_participants_lottery_kook'),
    )

    id = db.Column(db.Integer, primary_key=True)
    lottery_id = db.Column(db.Integer, db.ForeignKey('lotteries.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    kook_username = db.Column(db.String(100))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='lottery_participations')

    @property
    def display_name(self):
        if self.user:
            for candidate in (
                self.user.player_nickname,
                self.user.kook_username,
                self.user.nickname,
                self.user.username,
            ):
                if candidate:
                    return candidate
        return self.kook_username or self.kook_id

    def __repr__(self):
        return f'<LotteryParticipant lottery={self.lottery_id} kook={self.kook_id}>'


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
