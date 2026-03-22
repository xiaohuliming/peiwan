import json
from datetime import datetime, date
import uuid
from sqlalchemy import or_, event
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

def generate_user_code():
    return str(uuid.uuid4())[:8].upper()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    DEFAULT_IDENTITY_TAGS = ('老板',)

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    role = db.Column(db.String(20), default='god', nullable=False, index=True) # god, player, staff, admin, superadmin
    nickname = db.Column(db.String(100), index=True)
    player_nickname = db.Column(db.String(100), index=True)
    avatar = db.Column(db.String(500))
    badge = db.Column(db.String(50))
    user_code = db.Column(db.String(20), unique=True, default=generate_user_code)

    kook_id = db.Column(db.String(50), index=True)
    kook_username = db.Column(db.String(100))
    kook_bound = db.Column(db.Boolean, default=False)

    wechat_openid = db.Column(db.String(100))
    wechat_bound = db.Column(db.Boolean, default=False)

    m_coin = db.Column(db.Numeric(12, 2), default=0.00)
    m_coin_gift = db.Column(db.Numeric(12, 2), default=0.00)
    m_bean = db.Column(db.Numeric(12, 2), default=0.00)
    m_bean_frozen = db.Column(db.Numeric(12, 2), default=0.00)

    experience = db.Column(db.Integer, default=0)
    vip_level = db.Column(db.String(50), default='GOD')
    vip_discount = db.Column(db.Numeric(5, 2), default=100.00)

    anonymous_recharge = db.Column(db.Boolean, default=False)
    anonymous_consume = db.Column(db.Boolean, default=False)
    anonymous_gift_send = db.Column(db.Boolean, default=False)
    anonymous_gift_recv = db.Column(db.Boolean, default=False)
    anonymous_upgrade = db.Column(db.Boolean, default=False)
    anonymous_ranking = db.Column(db.Boolean, default=False)
    commission_rate = db.Column(db.Numeric(5, 2))  # 陪玩分成比例(NULL=走项目默认, 如80=80%)
    broadcast_channel = db.Column(db.String(100))

    referrer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    tags = db.Column(db.Text) # JSON string
    benefits = db.Column(db.Text) # JSON string
    status = db.Column(db.Boolean, default=True)
    register_type = db.Column(db.String(20), default='kook') # kook, wechat, manual
    birthday = db.Column(db.Date)  # 生日日期
    birthday_notified_year = db.Column(db.Integer, default=0)  # 生日祝福已发送年份（防重复）

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def tag_list(self):
        """返回标签列表"""
        if not self.tags:
            return list(self.DEFAULT_IDENTITY_TAGS)
        try:
            parsed = json.loads(self.tags)
        except (json.JSONDecodeError, TypeError):
            parsed = []
        return self._normalize_tags(parsed)

    @tag_list.setter
    def tag_list(self, value):
        self.tags = json.dumps(self._normalize_tags(value), ensure_ascii=False)

    @classmethod
    def _normalize_tags(cls, tags):
        items = tags if isinstance(tags, list) else []
        seen = set()
        cleaned = []
        for t in items:
            s = str(t).strip()
            if s and s not in seen:
                cleaned.append(s)
                seen.add(s)
        for default_tag in cls.DEFAULT_IDENTITY_TAGS:
            if default_tag not in seen:
                cleaned.append(default_tag)
                seen.add(default_tag)
        return cleaned

    @property
    def has_player_tag(self):
        """是否有陪玩身份标签"""
        return self.role == 'player' or '陪玩' in self.tag_list

    @property
    def anonymous_broadcast_all(self):
        """是否开启全部匿名播报（充值/消费/礼物/升级）"""
        return all([
            bool(self.anonymous_recharge),
            bool(self.anonymous_consume),
            bool(self.anonymous_gift_send),
            bool(self.anonymous_gift_recv),
            bool(self.anonymous_upgrade),
        ])

    def set_anonymous_broadcast_all(self, enabled: bool):
        """一键设置全部匿名播报开关"""
        state = bool(enabled)
        self.anonymous_recharge = state
        self.anonymous_consume = state
        self.anonymous_gift_send = state
        self.anonymous_gift_recv = state
        self.anonymous_upgrade = state

    @staticmethod
    def _role_to_identity(role_key):
        return {
            'god': '老板',
            'player': '陪玩',
            'staff': '客服',
        }.get(role_key)

    def has_role(self, role_key):
        """支持主角色 + 身份标签的角色判断"""
        if self.role == role_key:
            return True
        identity = self._role_to_identity(role_key)
        return bool(identity and identity in self.tag_list)

    @classmethod
    def role_filter_expr(cls, role_key):
        """支持主角色 + 身份标签的查询表达式"""
        identity = cls._role_to_identity(role_key)
        if identity:
            return or_(cls.role == role_key, cls.tags.ilike(f'%"{identity}"%'))
        return cls.role == role_key

    @property
    def staff_display_name(self):
        """客服展示名：优先使用陪玩昵称"""
        return self.player_nickname or self.nickname or self.username

    @property
    def avatar_url(self):
        """优先使用 KOOK 头像，否则回退到 DiceBear 生成"""
        if self.avatar:
            return self.avatar
        return f'https://api.dicebear.com/7.x/notionists/svg?seed={self.username}&backgroundColor=e8eaf6'

    @property
    def birthday_month_day(self):
        """生日月日展示文本（忽略年份）。"""
        if not self.birthday:
            return ''
        return self.birthday.strftime('%m-%d')

    @property
    def is_god(self):
        return self.has_role('god')
    
    @property
    def is_player(self):
        return self.has_role('player')
    
    @property
    def is_staff(self):
        return self.has_role('staff') or self.role in ['admin', 'superadmin']
        
    @property
    def is_admin(self):
        return self.role in ['admin', 'superadmin']
    
    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    @property
    def role_name(self):
        roles = {
            'god': 'GOD (老板)',
            'player': '小猪崽 (陪玩)',
            'staff': '客服宝宝',
            'admin': '管理宝宝',
            'superadmin': '高级管理'
        }
        return roles.get(self.role, '未知身份')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


@event.listens_for(User, 'before_insert')
@event.listens_for(User, 'before_update')
def _ensure_default_identity_tags(mapper, connection, target):
    target.tag_list = target.tag_list
