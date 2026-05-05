from datetime import datetime

from app.extensions import db


class MiniGameRecord(db.Model):
    """KOOK 小游戏对局战绩。"""
    __tablename__ = 'mini_game_records'

    id = db.Column(db.Integer, primary_key=True)
    game = db.Column(db.String(40), nullable=False, index=True)
    game_label = db.Column(db.String(40), nullable=False)
    channel_id = db.Column(db.String(100), index=True)

    player1_kook_id = db.Column(db.String(50), index=True)
    player1_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    player1_name = db.Column(db.String(120))
    player2_kook_id = db.Column(db.String(50), index=True)
    player2_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    player2_name = db.Column(db.String(120))

    winner_kook_id = db.Column(db.String(50), index=True)
    winner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    winner_name = db.Column(db.String(120))

    result = db.Column(db.String(20), nullable=False, index=True)
    end_reason = db.Column(db.String(50))
    abandoned_by_kook_id = db.Column(db.String(50), index=True)
    moves = db.Column(db.Integer, default=0, nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    duration_seconds = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    player1_user = db.relationship('User', foreign_keys=[player1_user_id], backref='mini_game_records_as_player1')
    player2_user = db.relationship('User', foreign_keys=[player2_user_id], backref='mini_game_records_as_player2')
    winner_user = db.relationship('User', foreign_keys=[winner_user_id], backref='mini_game_wins')


class MiniGameRating(db.Model):
    """KOOK 小游戏排位分(目前用于 21 点)。"""
    __tablename__ = 'mini_game_ratings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    game = db.Column(db.String(40), nullable=False, index=True)
    rating = db.Column(db.Integer, default=1000, nullable=False)
    peak_rating = db.Column(db.Integer, default=1000, nullable=False)
    win_streak = db.Column(db.Integer, default=0, nullable=False)
    games_played = db.Column(db.Integer, default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='mini_game_ratings')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'game', name='uq_minigame_rating_user_game'),
    )
