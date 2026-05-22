# Ad Insight Manager

A Flask-based analytics dashboard for ad accounts, ad copy review, competitor tracking, and data-driven recommendations.

## Features
- password login and admin user management
- group ads by ad account
- analyze ad copy for tone, style, awareness level, keywords, hooks, and score
- compare ad performance using ROI and CTR
- competitor ad tracking window
- dark/light theme toggle
- admin-only user creation and deletion
- scaffolded connector for external ad account APIs

## Project structure
- `app.py`: main Flask application
- `models.py`: database models for users, accounts, ads, analyses, and competitors
- `forms.py`: Flask-WTF forms for login, users, accounts, ads, and competitors
- `analysis.py`: ad text analysis and recommendation logic
- `services/ad_provider.py`: extension stub for actual ad platform connectors
- `templates/`: Jinja2 pages for login, dashboard, account views, and admin pages
- `static/`: UI styling and theme toggle scripts

## Setup
1. Create a Python virtual environment and activate it:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
4. Edit `.env` and set a secure `SECRET_KEY`.
5. Run the app:
   ```bash
   flask run
   ```
6. Open `http://127.0.0.1:5000` in your browser.

## Admin access
- A default admin user is created automatically when the app first runs:
  - username: `admin`
  - password: `admin123`
- Change this password immediately in the database or extend the app to support password updates.

## How to use
1. Login as admin.
2. Create ad accounts on the `Ad accounts` page.
3. Open an account to add ads and automatically analyze copy.
4. Use the `Competitor ads` page to add running competitor ads with source and status.
5. View the dashboard for quick ROI and recommendation summaries.

## Connecting real ad accounts
The app currently stores accounts and ad data locally, plus includes a connector stub in `services/ad_provider.py`.
To connect real ad platforms:
- implement OAuth / API key flows for Facebook, Google, TikTok, or other networks
- map each external ad to the local `AdAccount` and `Ad` models
- use `services/ad_provider.fetch_ads()` to sync live creatives and metrics

### Example flow
1. Add account in the app and store provider credentials securely.
2. Use `connect_account(provider, credentials)` in `services/ad_provider.py`.
3. Fetch ads with `fetch_ads(account_config)` and save them in local models.
4. Use the same analysis logic in `analysis.py` to evaluate each ad.

## Deployment hints
- Use a production WSGI server like `gunicorn`:
  ```bash
  pip install gunicorn
  gunicorn app:create_app
  ```
- Configure a real database for production (`postgresql://`, `mysql://`, etc.) via `DATABASE_URL`.
- Use a reverse proxy like Nginx to serve static files and secure HTTPS.
- Keep `.env` private and never commit secrets to Git.

## Git push workflow
```bash
git init
git add .
git commit -m "Initial Ad Insight Manager scaffold"
git branch -M main
git remote add origin https://github.com/youruser/your-repo.git
git push -u origin main
```

## Extending the project
To add new sections or analysis blocks:
- add new models in `models.py`
- create new forms in `forms.py`
- add routes in `app.py`
- create templates under `templates/`
- update `analysis.py` with new scoring or AI-style insights

## Notes
- The app is intentionally extensible; each new block can be added by creating a route + template + data model.
- Use the account grouping view to keep separate ad accounts organized.
- The AI-style recommendations are built from heuristic copywriting signals and can be expanded with real NLP models later.
