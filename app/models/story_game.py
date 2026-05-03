import json
from datetime import datetime

from app.extensions import db


def _load_json(raw, default):
    if not raw:
        return default() if callable(default) else default
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default() if callable(default) else default
    return data


def _dump_json(value):
    return json.dumps(value or [], ensure_ascii=False)


class StoryPlayerState(db.Model):
    """KOOK AI 剧情游戏玩家档案。"""
    __tablename__ = 'story_player_states'

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    kook_username = db.Column(db.String(100))
    story_world = db.Column(db.String(50), nullable=False)
    background = db.Column(db.String(50), nullable=False)
    chapter = db.Column(db.Integer, default=0, nullable=False)
    current_scene = db.Column(db.String(120), default='sealed_training_room', nullable=False)
    status_label = db.Column(db.String(120), default='基地二级警戒目标')
    last_npc = db.Column(db.String(50), default='jett')
    flags = db.Column(db.Text)
    traits = db.Column(db.Text)
    current_choices = db.Column(db.Text)
    summary = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='story_player_states')

    @property
    def flag_list(self):
        data = _load_json(self.flags, list)
        return data if isinstance(data, list) else []

    @flag_list.setter
    def flag_list(self, value):
        cleaned = []
        seen = set()
        for item in value or []:
            text = str(item).strip()
            if text and text not in seen:
                cleaned.append(text)
                seen.add(text)
        self.flags = _dump_json(cleaned)

    @property
    def trait_map(self):
        data = _load_json(self.traits, dict)
        return data if isinstance(data, dict) else {}

    @trait_map.setter
    def trait_map(self, value):
        self.traits = json.dumps(value or {}, ensure_ascii=False)

    @property
    def choice_list(self):
        data = _load_json(self.current_choices, list)
        return data if isinstance(data, list) else []

    @choice_list.setter
    def choice_list(self, value):
        self.current_choices = _dump_json([str(x).strip() for x in (value or []) if str(x).strip()])


class StoryCharacterRelation(db.Model):
    """玩家与剧情角色的信任和羁绊进度。"""
    __tablename__ = 'story_character_relations'
    __table_args__ = (
        db.UniqueConstraint('kook_id', 'character_id', name='uq_story_relation_kook_character'),
    )

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    character_id = db.Column(db.String(50), nullable=False, index=True)
    character_name = db.Column(db.String(50), nullable=False)
    trust = db.Column(db.Integer, default=0, nullable=False)
    bond_level = db.Column(db.Integer, default=0, nullable=False)
    relationship_status = db.Column(db.String(160))
    triggered_events = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='story_character_relations')

    @property
    def event_list(self):
        data = _load_json(self.triggered_events, list)
        return data if isinstance(data, list) else []

    @event_list.setter
    def event_list(self, value):
        cleaned = []
        seen = set()
        for item in value or []:
            text = str(item).strip()
            if text and text not in seen:
                cleaned.append(text)
                seen.add(text)
        self.triggered_events = _dump_json(cleaned)


class StoryMemoryFragment(db.Model):
    """玩家解锁的主线记忆碎片。"""
    __tablename__ = 'story_memory_fragments'
    __table_args__ = (
        db.UniqueConstraint('kook_id', 'memory_id', name='uq_story_memory_kook_memory'),
    )

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    memory_id = db.Column(db.String(100), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    source_event = db.Column(db.String(120))
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='story_memory_fragments')


class StoryDirectMessage(db.Model):
    """剧情角色发给玩家的 KOOK 私信记录。"""
    __tablename__ = 'story_direct_messages'

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    character_id = db.Column(db.String(50), nullable=False, index=True)
    character_name = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    reply_allowed = db.Column(db.Boolean, default=True, nullable=False)
    trigger_event = db.Column(db.String(120))
    kook_msg_id = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    replied_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='story_direct_messages')


class StoryTurnLog(db.Model):
    """剧情回合日志，用于后续后台审计与复盘。"""
    __tablename__ = 'story_turn_logs'

    id = db.Column(db.Integer, primary_key=True)
    kook_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    channel_id = db.Column(db.String(100))
    input_text = db.Column(db.Text)
    visible_text = db.Column(db.Text)
    state_updates = db.Column(db.Text)
    llm_used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='story_turn_logs')
