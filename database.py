from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    db.init_app(app)
    with app.app_context():
        import os
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(os.path.join(app.root_path, 'instance'), exist_ok=True)
        
        db.create_all()
        
        from models import User
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                is_admin=True,
                is_ldap_user=True,
                ldap_dn='cn=admin,dc=example,dc=com'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print(">>> Seeded initial admin user (username: admin / pass: admin123)")

