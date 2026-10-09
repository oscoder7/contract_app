import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'enterprise-secret-key-change-in-prod'
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'app.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploaded_templates')
    FASTAPI_BASE_URL = os.environ.get('FASTAPI_BASE_URL') or 'http://localhost:8000'
    
    LDAP_SERVER = os.environ.get('LDAP_SERVER') or 'ldap://127.0.0.1:389'
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN') or 'dc=example,dc=com'
