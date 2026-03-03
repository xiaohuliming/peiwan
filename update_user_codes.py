from app import create_app, db
from app.models.user import User, generate_user_code

app = create_app()

with app.app_context():
    users = User.query.filter(User.user_code == None).all()
    for user in users:
        user.user_code = generate_user_code()
        print(f"Updated user {user.username} with code {user.user_code}")
    
    if users:
        db.session.commit()
        print("All users updated.")
    else:
        print("No users needed update.")
