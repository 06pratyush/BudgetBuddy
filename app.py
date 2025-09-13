from flask import Flask, request, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import csv
import io
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'c79a54f375cd20aaa254dae9d164b457'  # Change this to a secure random key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///budgetbuddy.db'  # Use PostgreSQL for production
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Predefined categories and tips
CATEGORIES = ['Food & Dining', 'Travel & Transport', 'Study Materials', 'Entertainment', 'Shopping', 'Health & Medical', 'Other']
TIPS = [
    "Track your daily expenses to identify spending patterns and save more effectively!",
    "Set a weekly limit for eating out to cut down on unnecessary spending.",
    "Use public transport instead of rideshares to save on travel costs.",
    "Buy used textbooks or share with friends to reduce study material expenses.",
    "Limit entertainment subscriptions to one or two essentials.",
    "Shop with a list to avoid impulse buys.",
    "Prioritize preventive health to avoid costly medical bills."
]

# Predefined challenges (can be stored in DB for dynamism)
CHALLENGES = [
    {'id': 1, 'title': 'Save ₹100 this week', 'description': 'Avoid spending on non-essentials for 7 days.', 'category': 'Savings', 'points': 100},
    {'id': 2, 'title': 'No coffee for 3 days', 'description': 'Skip buying coffee for 3 consecutive days.', 'category': 'Habits', 'points': 50},
    # Add more as needed
]

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    university = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    monthly_budget = db.Column(db.Float, default=5000.0)
    streak = db.Column(db.Integer, default=0)
    reward_points = db.Column(db.Integer, default=0)
    challenges_won = db.Column(db.Integer, default=0)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Challenge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    points = db.Column(db.Integer, nullable=False)

class UserChallenge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenge.id'), nullable=False)
    status = db.Column(db.String(20), default='active')  # active, completed
    progress = db.Column(db.Float, default=0.0)  # 0-100%

from flask import render_template

@app.route('/')
def serve_index():
    return render_template('index.html')

# Create DB tables if not exist
with app.app_context():
    db.create_all()
    # Seed challenges if empty
    if Challenge.query.count() == 0:
        for ch in CHALLENGES:
            db.session.add(Challenge(**ch))
        db.session.commit()

# Auth decorator
def login_required(f):
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400
    hashed_pw = generate_password_hash(data['password'])
    user = User(name=data['name'], email=data['email'], university=data['university'], password_hash=hashed_pw)
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Account created'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    if user and check_password_hash(user.password_hash, data['password']):
        session['user_id'] = user.id
        return jsonify({'message': 'Logged in'})
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    session.pop('user_id')
    return jsonify({'message': 'Logged out'})

@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    expenses = Expense.query.filter_by(user_id=user.id).filter(Expense.date >= month_start).all()
    total_spent = sum(e.amount for e in expenses)
    remaining = user.monthly_budget - total_spent
    return jsonify({
        'monthly_budget': user.monthly_budget,
        'total_spent': total_spent,
        'remaining': remaining,
        'challenges_won': user.challenges_won,
        'reward_points': user.reward_points,
        'streak': user.streak
    })

@app.route('/api/expenses', methods=['POST'])
@login_required
def add_expense():
    data = request.json
    if data['category'] not in CATEGORIES:
        return jsonify({'error': 'Invalid category'}), 400
    expense = Expense(user_id=session['user_id'], amount=data['amount'], category=data['category'], description=data.get('description'))
    db.session.add(expense)
    db.session.commit()
    return jsonify({'message': 'Expense added'})

@app.route('/api/expenses/recent', methods=['GET'])
@login_required
def recent_expenses():
    expenses = Expense.query.filter_by(user_id=session['user_id']).order_by(Expense.date.desc()).limit(10).all()
    return jsonify([{'id': e.id, 'amount': e.amount, 'category': e.category, 'description': e.description, 'date': e.date.isoformat()} for e in expenses])

@app.route('/api/expenses/export', methods=['GET'])
@login_required
def export_csv():
    expenses = Expense.query.filter_by(user_id=session['user_id']).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Amount', 'Category', 'Description'])
    for e in expenses:
        writer.writerow([e.date.isoformat(), e.amount, e.category, e.description])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='expenses.csv')

@app.route('/api/spending', methods=['GET'])
@login_required
def spending_overview():
    period = request.args.get('period', 'month')
    chart_type = request.args.get('type', 'category')  # New param: 'category' (default) or 'line'
    now = datetime.utcnow()
    if period == 'week':
        start = now - timedelta(days=7)
    elif period == 'month':
        start = now.replace(day=1)
    else:  # all
        start = datetime.min
    expenses = Expense.query.filter_by(user_id=session['user_id']).filter(Expense.date >= start).all()
    
    if chart_type == 'line':
        # Group by day for line chart (date: total amount)
        daily_spending = {}
        for e in expenses:
            day = e.date.date().isoformat()  # YYYY-MM-DD
            daily_spending[day] = daily_spending.get(day, 0) + e.amount
        # Sort by date and prepare labels/data
        sorted_days = sorted(daily_spending.keys())
        return jsonify({
            'labels': sorted_days,
            'data': [daily_spending[day] for day in sorted_days]
        })
    else:
        # Existing by-category logic
        by_category = {}
        for e in expenses:
            by_category[e.category] = by_category.get(e.category, 0) + e.amount
        return jsonify({'by_category': by_category})

@app.route('/api/tips', methods=['GET'])
@login_required
def get_tip():
    return jsonify({'tip': random.choice(TIPS)})

@app.route('/api/challenges/available', methods=['GET'])
@login_required
def available_challenges():
    category = request.args.get('category', 'all')
    if category == 'all':
        challenges = Challenge.query.all()
    else:
        challenges = Challenge.query.filter_by(category=category.capitalize()).all()
    return jsonify([{'id': c.id, 'title': c.title, 'description': c.description, 'category': c.category, 'points': c.points} for c in challenges])

@app.route('/api/challenges/join', methods=['POST'])
@login_required
def join_challenge():
    data = request.json
    challenge = Challenge.query.get(data['challenge_id'])
    if not challenge:
        return jsonify({'error': 'Challenge not found'}), 404
    existing = UserChallenge.query.filter_by(user_id=session['user_id'], challenge_id=challenge.id).first()
    if existing:
        return jsonify({'error': 'Already joined'}), 400
    uc = UserChallenge(user_id=session['user_id'], challenge_id=challenge.id)
    db.session.add(uc)
    db.session.commit()
    return jsonify({'message': 'Joined challenge'})

@app.route('/api/challenges/active', methods=['GET'])
@login_required
def active_challenges():
    ucs = UserChallenge.query.filter_by(user_id=session['user_id'], status='active').all()
    return jsonify([{'id': uc.id, 'challenge_id': uc.challenge_id, 'progress': uc.progress} for uc in ucs])

@app.route('/api/challenges/update', methods=['POST'])
@login_required
def update_challenge():
    data = request.json
    uc = UserChallenge.query.get(data['user_challenge_id'])
    if not uc or uc.user_id != session['user_id']:
        return jsonify({'error': 'Not found'}), 404
    uc.progress = data['progress']
    if uc.progress >= 100:
        uc.status = 'completed'
        user = User.query.get(uc.user_id)
        challenge = Challenge.query.get(uc.challenge_id)
        user.challenges_won += 1
        user.reward_points += challenge.points
        user.streak += 1  # Simplistic streak update
    db.session.commit()
    return jsonify({'message': 'Updated'})

@app.route('/api/leaderboard', methods=['GET'])
@login_required
def leaderboard():
    users = User.query.order_by(User.reward_points.desc()).limit(4).all()  # Top 3 + user
    current_user = User.query.get(session['user_id'])
    lb = [{'name': u.name, 'challenges_won': u.challenges_won, 'points': u.reward_points} for u in users]
    lb.append({'name': 'You', 'challenges_won': current_user.challenges_won, 'points': current_user.reward_points})
    return jsonify(lb)

@app.route('/api/budget/goal', methods=['GET'])
@login_required
def get_budget_goal():
    user = User.query.get(session['user_id'])
    now = datetime.utcnow()
    month_start = now.replace(day=1)
    expenses = Expense.query.filter_by(user_id=user.id).filter(Expense.date >= month_start).all()
    total_spent = sum(e.amount for e in expenses)
    progress = (total_spent / user.monthly_budget) * 100 if user.monthly_budget > 0 else 0
    return jsonify({'budget': user.monthly_budget, 'progress': progress})

@app.route('/api/budget/update', methods=['POST'])
@login_required
def update_budget():
    data = request.json
    user = User.query.get(session['user_id'])
    user.monthly_budget = data['budget']
    db.session.commit()
    return jsonify({'message': 'Budget updated'})

if __name__ == '__main__':
    app.run(debug=False)