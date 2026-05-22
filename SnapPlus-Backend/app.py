from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)  # لتمكين لوحة التحكم من الاتصال بالـ API

DB_FILE = 'database.json'

def load_db():
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

@app.route('/')
def index():
    return jsonify({"message": "Snap Plus API is Running", "status": "Online"})

# 1. التحقق من مفتاح التفعيل
@app.route('/api/validate_key', methods=['POST'])
def validate_key():
    data = request.json
    key_to_check = data.get('key')
    
    db = load_db()
    for k in db['keys']:
        if k['key'] == key_to_check:
            if k['status'] == 'active':
                return jsonify({
                    "valid": True,
                    "type": k['type'],
                    "expires_at": k['expires_at'],
                    "message": "تم تفعيل المفتاح بنجاح"
                })
            else:
                return jsonify({"valid": False, "message": "هذا المفتاح منتهي الصلاحية"}), 403
                
    return jsonify({"valid": False, "message": "مفتاح تفعيل غير صالح"}), 404

# 2. جلب حالة الحماية من الحظر
@app.route('/api/protection_status', methods=['GET'])
def get_protection():
    db = load_db()
    return jsonify(db['protection_status'])

# 3. إحصائيات لوحة التحكم (Admin Stats)
@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    db = load_db()
    total_users = len(db['users'])
    active_keys = len([k for k in db['keys'] if k['status'] == 'active'])
    
    return jsonify({
        "total_users": total_users,
        "active_keys": active_keys,
        "protection_level": "99.9%",
        "current_version": db['protection_status']['version']
    })

# 4. تسجيل دخول المدير
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    db = load_db()
    for user in db['users']:
        if user['username'] == username and user['password'] == password:
            return jsonify({
                "success": True, 
                "message": "تم تسجيل الدخول بنجاح",
                "role": user['role']
            })
            
    return jsonify({"success": False, "message": "اسم المستخدم أو كلمة المرور خطأ"}), 401

# 5. رابط تحميل المشروع الكامل
@app.route('/download/bundle', methods=['GET'])
def download_bundle():
    bundle_path = r'c:\Users\IT\Documents\GitHub\ashm-abo-nwaf\SnapPlus_Final_Bundle.zip'
    if os.path.exists(bundle_path):
        from flask import send_file
        return send_file(bundle_path, as_attachment=True)
    else:
        return jsonify({"success": False, "message": "الملف غير موجود"}), 404

# 6. رابط تحميل ملف الـ CSR
@app.route('/download/csr', methods=['GET'])
def download_csr():
    csr_path = r'c:\Users\IT\Documents\GitHub\ashm-abo-nwaf\SnapPlus-App\ios.csr'
    if os.path.exists(csr_path):
        from flask import send_file
        return send_file(csr_path, as_attachment=True)
    else:
        return jsonify({"success": False, "message": "الملف غير موجود"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
