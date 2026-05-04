from app import create_app, db
from app.models import (
    User, Order, BalanceLog, CommissionLog, WithdrawRequest,
    Project, ProjectItem, ClockRecord,
    Gift, GiftOrder, Intimacy, OperationLog, BroadcastConfig,
    VipLevel, UpgradeRecord, MiniGameRecord
)

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {
        'db': db, 'User': User, 'Order': Order,
        'BalanceLog': BalanceLog, 'CommissionLog': CommissionLog,
        'WithdrawRequest': WithdrawRequest,
        'Project': Project, 'ProjectItem': ProjectItem,
        'ClockRecord': ClockRecord,
        'Gift': Gift, 'GiftOrder': GiftOrder,
        'Intimacy': Intimacy, 'OperationLog': OperationLog,
        'BroadcastConfig': BroadcastConfig,
        'VipLevel': VipLevel, 'UpgradeRecord': UpgradeRecord,
        'MiniGameRecord': MiniGameRecord,
    }

if __name__ == '__main__':
    app.run(debug=True, port=5000)
