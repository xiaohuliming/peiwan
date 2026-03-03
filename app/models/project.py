from datetime import datetime
from app.extensions import db


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, default=0)
    status = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('ProjectItem', backref='project', lazy='dynamic', order_by='ProjectItem.sort_order')

    def __repr__(self):
        return f'<Project {self.name}>'


class ProjectItem(db.Model):
    __tablename__ = 'project_items'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)

    # 不同档位定价
    price_casual = db.Column(db.Numeric(10, 2), default=0)   # 娱乐档
    price_tech = db.Column(db.Numeric(10, 2), default=0)     # 技术档
    price_god = db.Column(db.Numeric(10, 2), default=0)      # 大神档
    price_pro = db.Column(db.Numeric(10, 2), default=0)      # 巅峰档(兼容旧 pro 字段)
    price_devil = db.Column(db.Numeric(10, 2), default=0)    # 魔王档

    commission_rate = db.Column(db.Numeric(5, 2), default=80.00)  # 佣金比例 (默认80%)
    billing_type = db.Column(db.String(20), default='hour')       # hour=按小时, round=按局
    project_type = db.Column(db.String(20), default='normal')     # normal=陪玩, escort=护航, training=代练

    sort_order = db.Column(db.Integer, default=0)
    status = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_price_by_tier(self, tier):
        """根据档位获取价格"""
        devil_price = self.price_devil if (self.price_devil or 0) > 0 else self.price_pro
        tier_map = {
            'casual': self.price_casual,
            'tech': self.price_tech,
            'god': self.price_god,
            'peak': self.price_pro,
            'pro': self.price_pro,
            'devil': devil_price,
        }
        return tier_map.get(tier, self.price_casual)

    @property
    def tier_prices(self):
        """返回所有档位价格字典"""
        devil_price = self.price_devil if (self.price_devil or 0) > 0 else self.price_pro
        return {
            'casual': float(self.price_casual or 0),
            'tech': float(self.price_tech or 0),
            'god': float(self.price_god or 0),
            'peak': float(self.price_pro or 0),
            'devil': float(devil_price or 0),
            # 兼容历史前端/历史订单值
            'pro': float(self.price_pro or 0),
        }

    def __repr__(self):
        return f'<ProjectItem {self.name}>'
