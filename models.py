from database import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

role_templates = db.Table('role_templates',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True),
    db.Column('template_id', db.Integer, db.ForeignKey('contract_template.id'), primary_key=True)
)

user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_ldap_user = db.Column(db.Boolean, default=False)
    ldap_dn = db.Column(db.String(255), nullable=True)
    
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))

    def set_password(self, password):
        if password:
            self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    
    templates = db.relationship('ContractTemplate', secondary=role_templates, backref=db.backref('roles', lazy='dynamic'))

class ContractTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_name = db.Column(db.String(120), nullable=False)
    version_number = db.Column(db.String(40), nullable=False)
    process_code = db.Column(db.String(80), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Audit trail fields
    status_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    status_changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    status_changed_by = db.relationship('User', foreign_keys=[status_changed_by_id])
    updated_by = db.relationship('User', foreign_keys=[updated_by_id])

    __table_args__ = (
        db.UniqueConstraint('template_name', 'version_number', name='uix_name_version'),
    )
