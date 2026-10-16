import os
import requests
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, send_file,current_app
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from config import Config
from database import db, init_db
from models import User, Role, ContractTemplate
from sqlalchemy.exc import IntegrityError

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

app = Flask(__name__)
app.config.from_object(Config)

init_db(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def template_permission_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow access if user is super admin OR has the "Template Manager" role
        has_template_role = any(r.name == 'Template Manager' for r in current_user.roles)
        if not (current_user.is_admin or has_template_role):
            flash('Access denied: You do not have permission to maintain templates.', 'danger')
            return redirect(url_for('user_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def authenticate_ldap(dn, password):
    try:
        import ldap
        ldap_client = ldap.initialize(app.config['LDAP_SERVER'])
        ldap_client.set_option(ldap.OPT_REFERRALS, 0)
        ldap_client.simple_bind_s(dn, password)
        return True
    except Exception as e:
        app.logger.error(f"LDAP Exception: {e}")
        return False

# Smart Versioning Calculation
def generate_next_version(template_name, base_version, is_active):
    """
    Calculates a unique next version string by querying all existing versions for template_name.
    - If duplicating from an ACTIVE version: increments the minor/patch digit (e.g., 1.1 -> 1.2).
    - If duplicating from an INACTIVE/DELETED version: branches down a level (e.g., 1.2 -> 1.2.1).
    Ensures the generated version string never collides with an existing record.
    """
    # Fetch all existing version numbers for this template name
    existing_versions = set(
        v[0] for v in db.session.query(ContractTemplate.version_number)
        .filter_by(template_name=template_name).all()
    )

    parts = base_version.split('.')
    
    if is_active:
        # Standard increment on the last component
        try:
            last_num = int(parts[-1])
        except ValueError:
            last_num = 0
            
        candidate_num = last_num + 1
        while True:
            candidate_parts = parts[:-1] + [str(candidate_num)]
            candidate_version = '.'.join(candidate_parts)
            if candidate_version not in existing_versions:
                return candidate_version
            candidate_num += 1
    else:
        # Branch down a level (e.g., 1.2 -> 1.2.1)
        branch_prefix = f"{base_version}."
        branch_num = 1
        while True:
            candidate_version = f"{branch_prefix}{branch_num}"
            if candidate_version not in existing_versions:
                return candidate_version
            branch_num += 1

# --- AUTH ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('Invalid credentials', 'danger')
            return redirect(url_for('login'))
        
        authenticated = False
        if user.is_ldap_user and user.ldap_dn:
            authenticated = authenticate_ldap(user.ldap_dn, password)
            if not authenticated and user.password_hash:
                authenticated = user.check_password(password)
        else:
            authenticated = user.check_password(password)
            
        if authenticated:
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard'))
        else:
            flash('Invalid credentials', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- USER ROUTES ---

@app.route('/')
@login_required
def user_dashboard():
    # Show active templates assigned through user roles
    if current_user.is_admin:
        accessible_templates = ContractTemplate.query.filter_by(is_active=True).all()
    else:
        template_ids = set()
        for role in current_user.roles:
            for tmpl in role.templates:
                if tmpl.is_active:
                    template_ids.add(tmpl.id)
        accessible_templates = ContractTemplate.query.filter(ContractTemplate.id.in_(template_ids)).all()
        
    return render_template('user_dashboard.html', templates=accessible_templates)

@app.route('/api/lookup', methods=['POST'])
@login_required
def api_lookup():
    data = request.get_json() or {}
    app_ref = data.get('application_ref')
    process_code = data.get('process_code')
    if not app_ref or not process_code:
        return jsonify({'error': 'Application reference and Process Code required'}), 400
        
    try:
        # FastAPI container service URL (or set FASTAPI_BASE_URL in Flask config)
        fastapi_url = f"{app.config.get('FASTAPI_BASE_URL', 'http://doc_service:8000')}/api/data-lookup"
        
        response = requests.post(
            fastapi_url, 
            json={'application_ref': app_ref, 'process_code': process_code}, 
            timeout=10
        )
        
        response.raise_for_status()
        return jsonify(response.json())
        
    except requests.exceptions.HTTPError as he:
        err_detail = he.response.json().get('detail', str(he)) if he.response else str(he)
        return jsonify({'error': err_detail}), he.response.status_code if he.response else 500
        
    except Exception as e:
        current_app.logger.error(f"API Lookup failed for {process_code} (Ref: {app_ref}): {e}")
        return jsonify({'error': f'Lookup service error: {str(e)}'}), 500

from datetime import datetime

@app.route('/api/download-contract', methods=['POST'])
@login_required
def download_contract():
    data = request.get_json()
    template_id = data.get('template_id')
    payload = data.get('data', {}) # Returned lookup JSON payload
    
    tmpl = ContractTemplate.query.get_or_404(template_id)
    
    # Extract application reference (fallback to UNKNOWN if missing)
    app_ref = payload.get('application_ref', 'NO_REF')
    
    # Generate timestamp formatted as YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Construct filename: TEMPLATENAME_vVERSION_APPREF_TIMESTAMP.docx
    clean_tmpl_name = tmpl.template_name.replace(" ", "_")
    clean_app_ref = str(app_ref).replace(" ", "_")
    formatted_filename = f"{clean_tmpl_name}_v{tmpl.version_number}_{clean_app_ref}_{timestamp}.docx"
    
    try:
        fastapi_url = f"{app.config['FASTAPI_BASE_URL']}/api/generate-docx"
        res = requests.post(fastapi_url, json={
            'template_name': tmpl.template_name,
            'version_number': tmpl.version_number,
            'application_ref': clean_app_ref,
            'context': payload
        }, stream=True, timeout=15)
        
        if res.status_code == 200:
            return Response(
                res.iter_content(chunk_size=1024),
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                headers={'Content-Disposition': f'attachment; filename="{formatted_filename}"'}
            )
        else:
            return jsonify({'error': 'FastAPI rendering failed'}), 400
    except Exception as e:
        return jsonify({'error': f'FastAPI connection error: {str(e)}'}), 500

# --- ADMIN ROUTES ---

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
    return render_template('admin/dashboard.html')

# USER CRUD
@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form
        is_ldap = 'is_ldap' in request.form
        ldap_dn = request.form.get('ldap_dn') if is_ldap else None
        role_ids = request.form.getlist('roles')
        
        user = User(username=username, is_ldap_user=is_ldap, is_admin=is_admin,ldap_dn=ldap_dn)
        if password:
            user.set_password(password)
            
        user.roles = Role.query.filter(Role.id.in_(role_ids)).all()
        db.session.add(user)
        db.session.commit()
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('admin_users'))
        
    users = User.query.all()
    roles = Role.query.all()
    return render_template('admin/users.html', users=users, roles=roles)

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
    user = User.query.get_or_404(user_id)
    roles = Role.query.all()
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.is_ldap_user = 'is_ldap' in request.form
        user.ldap_dn = request.form.get('ldap_dn') if user.is_ldap_user else None
        new_password = request.form.get('password')
        if user.username == 'admin': 
            user.is_admin = True
            user.username = 'admin'  # Ensure the super admin username remains unchanged
        else:
            user.is_admin = 'is_admin' in request.form
        if new_password:
            user.set_password(new_password)
        role_ids = request.form.getlist('roles')
        user.roles = Role.query.filter(Role.id.in_(role_ids)).all()
        db.session.commit()
        flash(f'User {user.username} updated', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin/edit_user.html', user=user, roles=roles)

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
    if user_id == current_user.id:
        flash('Cannot delete active logged-in user', 'danger')
        return redirect(url_for('admin_users'))
    user = User.query.get_or_404(user_id)
    # RESTRICTION 1: Cannot delete the default 'admin' user or any Admin user
    if user.username == 'admin' or user.is_admin:
        flash(f'Error: Account "{user.username}" is an Administrator and cannot be deleted.', 'danger')
        return redirect(url_for('admin_users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted', 'warning')
    return redirect(url_for('admin_users'))

# ROLE CRUD
@app.route('/admin/roles', methods=['GET', 'POST'])
@login_required
def admin_roles():
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        template_ids = request.form.getlist('templates')
        
        role = Role(name=name, description=description)
        role.templates = ContractTemplate.query.filter(ContractTemplate.id.in_(template_ids)).all()
        
        db.session.add(role)
        db.session.commit()
        flash(f'Role {name} created', 'success')
        return redirect(url_for('admin_roles'))
        
    roles = Role.query.all()
    templates = ContractTemplate.query.order_by(ContractTemplate.template_name, ContractTemplate.version_number.desc()).all()
    return render_template('admin/roles.html', roles=roles, templates=templates)

@app.route('/admin/roles/edit/<int:role_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_role(role_id):
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
    role = Role.query.get_or_404(role_id)
    templates = ContractTemplate.query.order_by(ContractTemplate.template_name, ContractTemplate.version_number.desc()).all()
    if request.method == 'POST':
        role.name = request.form.get('name')
        role.description = request.form.get('description')
        template_ids = request.form.getlist('templates')
        role.templates = ContractTemplate.query.filter(ContractTemplate.id.in_(template_ids)).all()
        db.session.commit()
        flash(f'Role {role.name} updated', 'success')
        return redirect(url_for('admin_roles'))
    return render_template('admin/edit_role.html', role=role, templates=templates)

@app.route('/admin/roles/delete/<int:role_id>', methods=['POST'])
@login_required
def admin_delete_role(role_id):
    if not current_user.is_admin:
        return redirect(url_for('user_dashboard'))
    role = Role.query.get_or_404(role_id)
    db.session.delete(role)
    db.session.commit()
    flash('Role deleted', 'warning')
    return redirect(url_for('admin_roles'))

# TEMPLATE CRUD & MAINTENANCE
@app.route('/admin/templates', methods=['GET', 'POST'])
@login_required
@template_permission_required
def admin_templates():
    has_template_role = any(r.name == 'Template Manager' for r in current_user.roles)
    if not (current_user.is_admin or has_template_role):
        return redirect(url_for('user_dashboard'))
        
    if request.method == 'POST':
        template_name = request.form.get('template_name')
        version_number = request.form.get('version_number')
        process_code = request.form.get('process_code')
        is_active = 'is_active' in request.form
        # 1. Fetch templates at the very start so the variable is always defined
        templates = ContractTemplate.query.order_by(ContractTemplate.template_name, ContractTemplate.version_number.desc()).all()
        # 1. Check if a template with the same name and version already exists
        existing_template = ContractTemplate.query.filter_by(
            template_name=template_name, 
            version_number=version_number
        ).first()

        if existing_template:
            flash(f"A template named '{template_name}' with version '{version_number}' already exists!", "danger")
            return render_template('admin/templates.html', templates=templates, form_data=request.form)
        
        file = request.files.get('file')
        file_path = ""
        if file and file.filename != '':
            filename = f"{template_name}_{version_number}_{file.filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
        # Ensure only one template with the same name is active
        if is_active:
            ContractTemplate.query.filter_by(template_name=template_name).update({'is_active': False})
        try:        
            now = datetime.utcnow()
            tmpl = ContractTemplate(
                template_name=template_name,
                version_number=version_number,
                process_code=process_code,
                file_path=file_path,
                is_active=is_active,
                status_changed_at=now,
                status_changed_by_id=current_user.id,
                updated_at=now,
                updated_by_id=current_user.id
            )
            db.session.add(tmpl)
            db.session.commit()
            flash('Template created successfully', 'success')
            return redirect(url_for('admin_templates'))
        except IntegrityError:
            db.session.rollback()
            flash(f"Database error: A template with name '{template_name}' and version '{version_number}' already exists.", "danger")
            templates = ContractTemplate.query.order_by(ContractTemplate.template_name, ContractTemplate.version_number.desc()).all()
            return render_template('admin/templates.html', templates=templates, form_data=request.form)

    templates = ContractTemplate.query.order_by(ContractTemplate.template_name, ContractTemplate.version_number.desc()).all()
    return render_template('admin/templates.html', templates=templates)

@app.route('/admin/templates/download/<int:template_id>')
@login_required
@template_permission_required
def download_raw_template(template_id):
    if not (current_user.is_admin or any(r.name == 'Template Manager' for r in current_user.roles)):
        return redirect(url_for('user_dashboard'))
    tmpl = ContractTemplate.query.get_or_404(template_id)
    if os.path.exists(tmpl.file_path):
        return send_file(tmpl.file_path, as_attachment=True, download_name=os.path.basename(tmpl.file_path))
    flash('File not found on server.', 'danger')
    return redirect(url_for('admin_templates'))

@app.route('/admin/templates/edit/<int:template_id>', methods=['GET', 'POST'])
@login_required
@template_permission_required
def admin_edit_template(template_id):
    if not (current_user.is_admin or any(r.name == 'Template Manager' for r in current_user.roles)):
        return redirect(url_for('user_dashboard'))
        
    tmpl = ContractTemplate.query.get_or_404(template_id)
    
    if request.method == 'POST':
        tmpl.process_code = request.form.get('process_code')
        new_active = 'is_active' in request.form
        
        now = datetime.utcnow()
        if new_active != tmpl.is_active:
            tmpl.status_changed_at = now
            tmpl.status_changed_by_id = current_user.id
            if new_active:
                # Deactivate other versions of same template
                ContractTemplate.query.filter_by(template_name=tmpl.template_name).update({'is_active': False})
            tmpl.is_active = new_active

        tmpl.updated_at = now
        tmpl.updated_by_id = current_user.id
        
        file = request.files.get('file')
        if file and file.filename != '':
            filename = f"{tmpl.template_name}_{tmpl.version_number}_{file.filename}"
            new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(new_file_path)
            if os.path.exists(tmpl.file_path):
                try: os.remove(tmpl.file_path)
                except Exception: pass
            tmpl.file_path = new_file_path
            
        db.session.commit()
        flash('Template updated successfully', 'success')
        return redirect(url_for('admin_templates'))
        
    return render_template('admin/edit_template.html', template=tmpl)

@app.route('/admin/templates/duplicate/<int:template_id>', methods=['POST'])
@login_required
@template_permission_required
def duplicate_template(template_id):
    if not (current_user.is_admin or any(r.name == 'Template Manager' for r in current_user.roles)):
        return redirect(url_for('user_dashboard'))
        
    orig = ContractTemplate.query.get_or_404(template_id)
    
    # Passes 3 positional arguments: template_name, version_number, is_active
    new_version = generate_next_version(orig.template_name, orig.version_number, orig.is_active)
    
    # Deactivate other versions of the same template
    ContractTemplate.query.filter_by(template_name=orig.template_name).update({'is_active': False})
    
    now = datetime.utcnow()
    dup = ContractTemplate(
        template_name=orig.template_name,
        version_number=new_version,
        process_code=orig.process_code,
        file_path=orig.file_path,
        is_active=True,
        status_changed_at=now,
        status_changed_by_id=current_user.id,
        updated_at=now,
        updated_by_id=current_user.id
    )
    db.session.add(dup)
    db.session.commit()
    
    flash(f'Duplicated to unique Version {new_version} and set to Active', 'info')
    return redirect(url_for('admin_templates'))

@app.route('/admin/templates/delete/<int:template_id>', methods=['POST'])
@login_required
@template_permission_required
def admin_delete_template(template_id):
    if not (current_user.is_admin or any(r.name == 'Template Manager' for r in current_user.roles)):
        return redirect(url_for('user_dashboard'))
    tmpl = ContractTemplate.query.get_or_404(template_id)
    if os.path.exists(tmpl.file_path):
        try: os.remove(tmpl.file_path)
        except Exception: pass
    db.session.delete(tmpl)
    db.session.commit()
    flash('Template deleted', 'warning')
    return redirect(url_for('admin_templates'))

# TEST JINJA MAPPING IN ADMIN
@app.route('/admin/templates/test-render', methods=['POST'])
@login_required
@template_permission_required
def test_render_template():
    if not (current_user.is_admin or any(r.name == 'Template Manager' for r in current_user.roles)):
        return jsonify({'error': 'Unauthorized'}), 403
        
    template_id = request.form.get('template_id')
    custom_json = request.form.get('custom_json')
    
    tmpl = ContractTemplate.query.get_or_404(template_id)
    
    import json
    try:
        context_data = json.loads(custom_json)
    except Exception as e:
        return jsonify({'error': f'Invalid JSON payload: {str(e)}'}), 400
        
    try:
        fastapi_url = f"{app.config['FASTAPI_BASE_URL']}/api/generate-docx"
        res = requests.post(fastapi_url, json={
            'template_name': tmpl.template_name,
            'version_number': tmpl.version_number,
            'context': context_data
        }, stream=True, timeout=15)
        
        if res.status_code == 200:
            filename = f"TEST_{tmpl.template_name}_{tmpl.version_number}.docx"
            return Response(
                res.iter_content(chunk_size=1024),
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                headers={'Content-Disposition': f'attachment; filename="{filename}"'}
            )
    except Exception:
        pass
        
    if os.path.exists(tmpl.file_path):
        return send_file(tmpl.file_path, as_attachment=True, download_name=f"TEST_{tmpl.template_name}.docx")
        
    return jsonify({'error': 'Failed to render document'}), 500
@app.route('/sso')
def sso_login():
    # 1. Read authenticated username passed automatically by IIS / Nginx / Apache module
    sso_user = request.headers.get('REMOTE_USER') or request.environ.get('REMOTE_USER')
    
    if not sso_user:
        # Fallback check for custom headers if behind reverse proxy
        sso_user = request.headers.get('X-Remote-User')
    # 2. Mock fallback for local/non-domain testing
    if not sso_user and app.debug:
        # Allow passing ?mock_user=admin in debug mode for local testing
        sso_user = request.args.get('mock_user', 'admin')
    if sso_user:
        # Normalize username (e.g., DOMAIN\username -> username)
        username = sso_user.split('\\')[-1]
        
        # 2. Look up user in SQLite database
        user = User.query.filter((User.username == username) | (User.ldap_dn.like(f"%{username}%"))).first()
        
        if user and user.is_ldap_user:
            login_user(user)
            flash(f'Welcome, {user.username}! Logged in via SSO.', 'success')
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard'))
            
    flash('Unable to detect your Windows SSO session. Please log in with credentials.', 'warning')
    return redirect(url_for('login'))
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
