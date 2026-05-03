import json
from datetime import datetime

from app.extensions import db


DEFAULT_MILESTONE_REWARDS = {
    10: {'title': '十日连签', 'badge': '打卡10天'},
    30: {'title': '月度坚持者', 'badge': '打卡30天'},
    60: {'title': '双月守护者', 'badge': '打卡60天'},
    100: {'title': '百日打卡王', 'badge': '打卡100天'},
}


class ChatStatConfig(db.Model):
    """KOOK 发言统计机器人配置。"""
    __tablename__ = 'chat_stat_configs'

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    channel_ids = db.Column(db.Text)
    whitelist_kook_ids = db.Column(db.Text)
    duplicate_limit = db.Column(db.Integer, default=2, nullable=False)
    rank_limit = db.Column(db.Integer, default=10, nullable=False)
    daily_title = db.Column(db.String(80), default='话痨', nullable=False)
    weekly_title = db.Column(db.String(80), default='本周话痨', nullable=False)
    daily_broadcast_channel_id = db.Column(db.String(100))
    weekly_broadcast_channel_id = db.Column(db.String(100))
    checkin_broadcast_channel_id = db.Column(db.String(100))
    rank_broadcast_enabled = db.Column(db.Boolean, default=True, nullable=False)
    checkin_broadcast_enabled = db.Column(db.Boolean, default=True, nullable=False)
    milestone_rewards = db.Column(db.Text)
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
    def channel_id_list(self):
        return self._load_json_list(self.channel_ids)

    @channel_id_list.setter
    def channel_id_list(self, value):
        self.channel_ids = self._dump_json_list(value)

    @property
    def whitelist_kook_id_list(self):
        return self._load_json_list(self.whitelist_kook_ids)

    @whitelist_kook_id_list.setter
    def whitelist_kook_id_list(self, value):
        self.whitelist_kook_ids = self._dump_json_list(value)

    def get_milestone_rewards(self):
        if not self.milestone_rewards:
            return dict(DEFAULT_MILESTONE_REWARDS)
        try:
            data = json.loads(self.milestone_rewards)
        except (TypeError, json.JSONDecodeError):
            return dict(DEFAULT_MILESTONE_REWARDS)
        rewards = {}
        for key, value in (data or {}).items():
            try:
                day = int(key)
            except (TypeError, ValueError):
                continue
            if day <= 0 or not isinstance(value, dict):
                continue
            rewards[day] = {
                'title': str(value.get('title') or '').strip(),
                'badge': str(value.get('badge') or '').strip(),
            }
        return rewards or dict(DEFAULT_MILESTONE_REWARDS)

    def set_milestone_rewards(self, rewards):
        cleaned = {}
        for day, value in (rewards or {}).items():
            try:
                day_int = int(day)
            except (TypeError, ValueError):
                continue
            if day_int <= 0:
                continue
            value = value or {}
            cleaned[str(day_int)] = {
                'title': str(value.get('title') or '').strip(),
                'badge': str(value.get('badge') or '').strip(),
            }
        self.milestone_rewards = json.dumps(cleaned, ensure_ascii=False)


class ChatBotProfile(db.Model):
    """KOOK 用户在发言统计/签到机器人中的档案。"""
    __tablename__ = 'chat_bot_profiles'

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    display_name = db.Column(db.String(120))
    title = db.Column(db.String(80))
    badge = db.Column(db.String(80))
    sign_in_streak = db.Column(db.Integer, default=0, nullable=False)
    total_checkins = db.Column(db.Integer, default=0, nullable=False)
    last_checkin_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='chat_bot_profiles')

    @property
    def name(self):
        if self.user:
            for candidate in (
                self.user.player_nickname,
                self.user.kook_username,
                self.user.nickname,
                self.user.username,
            ):
                if candidate:
                    return candidate
        return self.display_name or self.kook_id


class ChatDailyUserStat(db.Model):
    """按北京时间自然日 + 频道 + KOOK ID 聚合的发言统计。"""
    __tablename__ = 'chat_daily_user_stats'
    __table_args__ = (
        db.UniqueConstraint('stat_date', 'channel_id', 'kook_id', name='uq_chat_daily_user_channel'),
    )

    id = db.Column(db.Integer, primary_key=True)
    stat_date = db.Column(db.Date, nullable=False, index=True)
    channel_id = db.Column(db.String(100), nullable=False, index=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_username = db.Column(db.String(100))
    total_count = db.Column(db.Integer, default=0, nullable=False)
    valid_count = db.Column(db.Integer, default=0, nullable=False)
    filtered_count = db.Column(db.Integer, default=0, nullable=False)
    duplicate_filtered_count = db.Column(db.Integer, default=0, nullable=False)
    meaningless_filtered_count = db.Column(db.Integer, default=0, nullable=False)
    last_message_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='chat_daily_stats')

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


class ChatDailyContentStat(db.Model):
    """用于判断复制粘贴重复发言的每日内容计数。"""
    __tablename__ = 'chat_daily_content_stats'
    __table_args__ = (
        db.UniqueConstraint('stat_date', 'channel_id', 'kook_id', 'content_hash', name='uq_chat_daily_content'),
    )

    id = db.Column(db.Integer, primary_key=True)
    stat_date = db.Column(db.Date, nullable=False, index=True)
    channel_id = db.Column(db.String(100), nullable=False, index=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    content_sample = db.Column(db.String(200))
    count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatRankSettlement(db.Model):
    """每日/每周排行榜结算结果。"""
    __tablename__ = 'chat_rank_settlements'
    __table_args__ = (
        db.UniqueConstraint('period_type', 'period_start', 'period_end', 'rank_no', name='uq_chat_rank_period_rank'),
    )

    id = db.Column(db.Integer, primary_key=True)
    period_type = db.Column(db.String(20), nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False, index=True)
    rank_no = db.Column(db.Integer, nullable=False)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_username = db.Column(db.String(100))
    valid_count = db.Column(db.Integer, default=0, nullable=False)
    title = db.Column(db.String(80))
    badge = db.Column(db.String(80))
    settled_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='chat_rank_settlements')

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


class ChatCheckinRecord(db.Model):
    """KOOK 签到记录。"""
    __tablename__ = 'chat_checkin_records'
    __table_args__ = (
        db.UniqueConstraint('checkin_date', 'kook_id', name='uq_chat_checkin_date_kook'),
    )

    id = db.Column(db.Integer, primary_key=True)
    checkin_date = db.Column(db.Date, nullable=False, index=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_username = db.Column(db.String(100))
    channel_id = db.Column(db.String(100))
    streak_after = db.Column(db.Integer, default=1, nullable=False)
    total_after = db.Column(db.Integer, default=1, nullable=False)
    reward_title = db.Column(db.String(80))
    reward_badge = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='chat_checkin_records')

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
