import json
from datetime import datetime

from app.extensions import db


class VoiceStatConfig(db.Model):
    """语音(挂机)统计配置。单例。"""
    __tablename__ = 'voice_stat_configs'

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    min_session_seconds = db.Column(db.Integer, default=30, nullable=False)
    truncate_hours = db.Column(db.Integer, default=12, nullable=False)
    whitelist_channel_ids = db.Column(db.Text)
    blacklist_channel_ids = db.Column(db.Text)
    whitelist_kook_ids = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def _load_json_list(raw):
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [str(item).strip() for item in data if str(item).strip()]

    @staticmethod
    def _dump_json_list(items):
        cleaned = []
        seen = set()
        for item in items or []:
            text = str(item).strip()
            if text and text not in seen:
                cleaned.append(text)
                seen.add(text)
        return json.dumps(cleaned, ensure_ascii=False)

    @property
    def whitelist_channel_id_list(self):
        return self._load_json_list(self.whitelist_channel_ids)

    @whitelist_channel_id_list.setter
    def whitelist_channel_id_list(self, value):
        self.whitelist_channel_ids = self._dump_json_list(value)

    @property
    def blacklist_channel_id_list(self):
        return self._load_json_list(self.blacklist_channel_ids)

    @blacklist_channel_id_list.setter
    def blacklist_channel_id_list(self, value):
        self.blacklist_channel_ids = self._dump_json_list(value)

    @property
    def whitelist_kook_id_list(self):
        return self._load_json_list(self.whitelist_kook_ids)

    @whitelist_kook_id_list.setter
    def whitelist_kook_id_list(self, value):
        self.whitelist_kook_ids = self._dump_json_list(value)


class VoiceSession(db.Model):
    """单条进出语音频道的会话记录。"""
    __tablename__ = 'voice_sessions'

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_username = db.Column(db.String(100))
    channel_id = db.Column(db.String(100), nullable=False, index=True)
    channel_name = db.Column(db.String(120))

    joined_at = db.Column(db.DateTime, nullable=False, index=True)
    left_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)

    # active / closed / truncated / cross_day
    status = db.Column(db.String(20), default='active', nullable=False, index=True)
    stat_date = db.Column(db.Date, index=True)
    note = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='voice_sessions')

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


class VoiceDailyStat(db.Model):
    """按北京时间自然日 + 频道 + KOOK ID 聚合的语音挂机时长。"""
    __tablename__ = 'voice_daily_stats'
    __table_args__ = (
        db.UniqueConstraint('stat_date', 'channel_id', 'kook_id', name='uq_voice_daily_user_channel'),
    )

    id = db.Column(db.Integer, primary_key=True)
    stat_date = db.Column(db.Date, nullable=False, index=True)
    channel_id = db.Column(db.String(100), nullable=False, index=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_username = db.Column(db.String(100))
    sessions_count = db.Column(db.Integer, default=0, nullable=False)
    total_seconds = db.Column(db.Integer, default=0, nullable=False)
    last_left_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='voice_daily_stats')

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
