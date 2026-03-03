from datetime import datetime
from app.extensions import db


class ClockRecord(db.Model):
    __tablename__ = 'clock_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    clock_in = db.Column(db.DateTime, nullable=False)       # 打卡上班时间
    clock_out = db.Column(db.DateTime)                       # 打卡下班时间
    duration_minutes = db.Column(db.Integer, default=0)      # 工时(分钟)
    status = db.Column(db.String(20), default='clocked_in')  # clocked_in / clocked_out / auto_timeout
    remark = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='clock_records')

    @property
    def status_label(self):
        labels = {
            'clocked_in': '工作中',
            'clocked_out': '正常下班',
            'auto_timeout': '自动超时',
        }
        return labels.get(self.status, self.status)

    @property
    def duration_display(self):
        """格式化工时显示"""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        return f'{hours}h {minutes}m'

    def __repr__(self):
        return f'<ClockRecord {self.id} user={self.user_id} status={self.status}>'
