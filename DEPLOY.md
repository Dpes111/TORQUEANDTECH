# 🚀 Free Deployment Guide — Torque and Tech

Three solid free options, ordered easiest → most powerful.

---

## Option 1 — PythonAnywhere (Easiest, Recommended for Beginners)

**Free tier:** 1 web app, 512 MB storage, always-on

### Steps

1. **Create account** → https://www.pythonanywhere.com (free plan)

2. **Upload your project**
   - Go to **Files** tab
   - Create a folder: `/home/<yourusername>/printcraft3d/`
   - Upload all your project files there (or use the ZIP upload)

3. **Install Flask** in a Bash console:
   ```bash
   pip3.10 install --user flask werkzeug
   ```

4. **Create the Web App**
   - Go to **Web** tab → Add a new web app
   - Choose **Manual configuration** → Python 3.10
   - Set **Source code:** `/home/<yourusername>/printcraft3d`
   - Set **Working directory:** `/home/<yourusername>/printcraft3d`

5. **Edit the WSGI file** (link shown on Web tab):
   ```python
   import sys
   import os
   sys.path.insert(0, '/home/<yourusername>/printcraft3d')
   os.chdir('/home/<yourusername>/printcraft3d')
   from app import app, init_db
   init_db()
   application = app
   ```

6. **Reload** the web app → visit `<yourusername>.pythonanywhere.com` ✅

### Important notes
- Replace `<yourusername>` with your actual PythonAnywhere username
- Free accounts get: `<yourusername>.pythonanywhere.com`
- Uploaded files (STL, screenshots) go in `/home/<yourusername>/printcraft3d/uploads/`

---

## Option 2 — Render (More Power, Auto-Deploy from GitHub)

**Free tier:** 750 hrs/month, spins down after 15 min inactivity (cold start ~30s)

### Steps

1. **Push your code to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   # Create repo on github.com, then:
   git remote add origin https://github.com/yourusername/printcraft3d.git
   git push -u origin main
   ```

2. **Create these two files** in your project root:

   **`requirements.txt`** (already included):
   ```
   flask>=3.0.0
   werkzeug>=3.0.0
   gunicorn>=21.0.0
   ```

   **`render.yaml`** (create this file):
   ```yaml
   services:
     - type: web
       name: printcraft3d
       env: python
       buildCommand: pip install -r requirements.txt
       startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
       envVars:
         - key: FLASK_ENV
           value: production
   ```

3. **Deploy on Render**
   - Go to https://render.com → New → Web Service
   - Connect your GitHub repo
   - Render auto-detects Python
   - Click **Deploy**

4. **Add startup DB init** — edit `app.py` bottom:
   ```python
   if __name__ == "__main__":
       init_db()
       app.run(debug=True, port=5000)
   ```
   Also add after `app = Flask(__name__)`:
   ```python
   # Auto-init DB on first request (for Render)
   with app.app_context():
       init_db()
   ```

5. Visit your `https://printcraft3d.onrender.com` URL ✅

### ⚠️ Persistent Storage on Render Free
Free Render disks reset on redeploy. For uploads (STL files, screenshots) to persist:
- **Option A:** Use Render's persistent disk ($7/mo) — not free
- **Option B (Free):** Use Cloudinary for image storage (see below)
- **Option C:** Use Supabase Storage (free 1GB)

---

## Option 3 — Railway (Best Free Tier for Flask)

**Free tier:** $5 credit/month (usually covers a small app all month)

### Steps

1. Go to https://railway.app → Login with GitHub

2. New Project → Deploy from GitHub repo

3. Railway auto-detects Python/Flask

4. Add environment variable:
   - `SECRET_KEY` = any random string

5. Add **`Procfile`** to your project:
   ```
   web: gunicorn app:app
   ```

6. Add `gunicorn` to `requirements.txt`:
   ```
   gunicorn>=21.0.0
   ```

7. Deploy → Railway gives you a `https://yourapp.up.railway.app` URL ✅

---

## Pre-Deployment Checklist

Before going live, do these in `app.py`:

```python
# 1. Change secret key (IMPORTANT for security)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-production")

# 2. Change admin password after first login
# Go to /admin → there is no change password UI yet,
# but you can run this in Python shell:
from werkzeug.security import generate_password_hash
import sqlite3
db = sqlite3.connect('database.db')
db.execute("UPDATE admin SET password=? WHERE username='admin'",
           (generate_password_hash('your_new_password'),))
db.commit()
```

---

## Adding a Real QR Code (eSewa / Khalti)

Replace the placeholder in `checkout.html` with your actual QR image:

1. Generate your eSewa/Khalti QR code from their merchant portal
2. Save it as `static/images/payment_qr.png`
3. In `checkout.html`, replace the `<div class="qr-placeholder">` with:
   ```html
   <img src="{{ url_for('static', filename='images/payment_qr.png') }}"
        alt="Payment QR Code" style="width:180px;height:180px;margin:0 auto;display:block;">
   ```

---

## Custom Domain (Free)

1. Get a free `.is-a.dev` subdomain at https://is-a.dev
2. Or use Freenom for a `.tk` / `.ml` domain
3. Point the domain's CNAME to your PythonAnywhere/Render URL

---

## Summary Table

| Platform | Free Tier | Always On | Custom Domain | Best For |
|----------|-----------|-----------|---------------|----------|
| PythonAnywhere | ✅ | ✅ | ❌ (paid) | Beginners |
| Render | ✅ (750h/mo) | ❌ (sleeps) | ✅ | GitHub users |
| Railway | ✅ ($5 credit) | ✅ | ✅ | Best overall |

**Recommendation:** Start with **PythonAnywhere** (simplest), migrate to **Railway** when you need more.
