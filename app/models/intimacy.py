from datetime import datetime
from app.extensions import db


class Intimacy(db.Model):
    """亲密度表"""
    __tablename__ = 'intimacies'

    id = db.Column(db.Integer, primary_key=True)
    boss_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    value = db.Column(db.Numeric(12, 2), default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Unique constraint: 一对老板-陪玩只有一条亲密度记录
    __table_args__ = (
        db.UniqueConstraint('boss_id', 'player_id', name='uq_boss_player_intimacy'),
    )

    boss = db.relationship('User', foreign_keys=[boss_id], backref='intimacies_as_boss')
    player = db.relationship('User', foreign_keys=[player_id], backref='intimacies_as_player')

    def __repr__(self):
        return f'<Intimacy boss={self.boss_id} player={self.player_id} value={self.value}>'
