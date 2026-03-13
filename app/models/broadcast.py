from datetime import datetime
from app.extensions import db


class BroadcastConfig(db.Model):
    """播报配置表"""
    __tablename__ = 'broadcast_configs'

    id = db.Column(db.Integer, primary_key=True)
    broadcast_type = db.Column(db.String(30), nullable=False, index=True)
    # recharge / gift / upgrade

    threshold = db.Column(db.Numeric(12, 2), default=0)
    # 充值播报: 触发金额档位 (500, 1000, 3000 等)
    # 礼物/升级: 可为0表示始终触发

    template = db.Column(db.Text)
    # 模板内容, 支持变量: {user}, {amount}, {level}, {gift_name}, {player} 等

    target_level = db.Column(db.String(50), nullable=True)  # 升级播报: 目标VIP等级（空=通用）
    channel_id = db.Column(db.String(100))  # KOOK频道ID
    image_url = db.Column(db.Text, nullable=True)  # 卡片附带图片URL
    schedule_weekday = db.Column(db.Integer, nullable=True)  # 定时任务: 周几(0=周一,6=周日)
    schedule_time = db.Column(db.String(5), nullable=True)   # 定时任务: HH:MM
    mention_role_ids = db.Column(db.Text, nullable=True)     # 定时任务: 角色ID列表（逗号分隔）
    last_sent_at = db.Column(db.DateTime, nullable=True)     # 定时任务: 最近发送时间（防重复）
    status = db.Column(db.Boolean, default=True)  # 启用/禁用

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<BroadcastConfig {self.broadcast_type} threshold={self.threshold}>'
