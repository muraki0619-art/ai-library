from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import stripe

# Stripeのテスト用秘密鍵（Stripeダッシュボードから取得したものに後で置き換えます）
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_51P...') 

# --- 有料プラン決済セッションの作成 ---
@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        # Stripeの決済ページを作成
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'jpy',
                    'product_data': {'name': '電脳図書館 プロプラン'},
                    'unit_amount': 2980, # 金額（円）
                },
                'quantity': 1,
            }],
            mode='payment',
            # 決済成功時とキャンセル時の戻り先URL
            success_url=url_for('payment_success', _external=True),
            cancel_url=url_for('index', _external=True),
            # 誰が支払ったか判別するためにユーザーIDを渡す
            client_reference_id=str(current_user.id),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)

# --- 決済成功時の仮ページ ---
@app.route('/payment-success')
@login_required
def payment_success():
    # 本来はここでWebhook（通知）を受けてDBを更新しますが、
    # まずはテストとして自分を手動で有料化する処理を入れます
    current_user.is_paid = True
    db.session.commit()
    return "🚀 決済が承認されました！あなたの権限が「プロプラン」にアップグレードされました。<a href='/'>トップへ戻る</a>"

app = Flask(__name__)

# --- 1. データベース設定 (先に定義) ---
# 環境変数 DATABASE_URL を取得。なければ SQLite を使う
uri = os.environ.get('DATABASE_URL', 'sqlite:///ai_library.db')

# postgres:// を postgresql:// に変換 (SQLAlchemyの仕様対策)
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-cyber-secret-key' # 本番用シークレットキー

# --- 2. データベース初期化 (設定の後に実行) ---
db = SQLAlchemy(app)

# --- カスタムフィルター: 相対時間表示 ---
@app.template_filter('time_since')
def time_since(dt):
    now = datetime.utcnow()
    diff = now - dt
    second_diff = diff.total_seconds()
    day_diff = diff.days
    if day_diff < 0: return "たった今"
    if day_diff == 0:
        if second_diff < 60: return "たった今"
        if second_diff < 3600: return f"{int(second_diff / 60)}分前"
        return f"{int(second_diff / 3600)}時間前"
    if day_diff < 7: return f"{day_diff}日前"
    return dt.strftime('%Y/%m/%d')

# --- データベースモデル ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_paid = db.Column(db.Boolean, default=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    genre = db.Column(db.String(50))
    ai_model = db.Column(db.String(50))
    prompt = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- ログイン管理 ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ルート設定 ---
@app.route('/')
def index():
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    hot_posts = Post.query.filter(Post.created_at >= three_days_ago).order_by(Post.views.desc()).limit(5).all()
    if not hot_posts: hot_posts = Post.query.order_by(Post.views.desc()).limit(5).all()
    new_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    evergreen_posts = Post.query.order_by(Post.views.desc()).limit(5).all()

    genres = ['小説', 'エッセイ', '論文', '詩', 'その他']
    genre_data = {g: Post.query.filter_by(genre=g).order_by(Post.views.desc()).limit(4).all() for g in genres}

    return render_template('index.html', hot_posts=hot_posts, new_posts=new_posts, evergreen_posts=evergreen_posts, genre_data=genre_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        elif not user:
            is_admin_flag = (username == "iorin") # 管理者ユーザー名
            new_user = User(
                username=username, 
                password=generate_password_hash(password, method='pbkdf2:sha256'),
                is_admin=is_admin_flag,
                is_paid=is_admin_flag
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('index'))
        return "パスワードが違います"
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/post', methods=['GET', 'POST'])
@login_required
def post_work():
    if request.method == 'POST':
        new_post = Post(
            username=current_user.username,
            title=request.form['title'],
            genre=request.form['genre'],
            ai_model=request.form['ai_model'],
            prompt=request.form['prompt'],
            content=request.form['content']
        )
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('post.html')

@app.route('/view/<int:post_id>')
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.views += 1
    db.session.commit()
    return render_template('view.html', post=post)

@app.route('/genre/<name>')
def genre_view(name):
    posts = Post.query.filter_by(genre=name).order_by(Post.created_at.desc()).all()
    return render_template('genre.html', genre_name=name, posts=posts)

@app.route('/mypage/<username>')
@login_required
def mypage(username):
    if current_user.username != username:
        return "権限がありません", 403
    posts = Post.query.filter_by(username=username).all()
    return render_template('mypage.html', username=username, posts=posts)

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.username != current_user.username:
        return "権限がありません", 403
    if request.method == 'POST':
        post.title = request.form['title']
        post.genre = request.form['genre']
        post.prompt = request.form['prompt']
        post.content = request.form['content']
        db.session.commit()
        return redirect(url_for('mypage', username=current_user.username))
    return render_template('edit.html', post=post)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin and not current_user.is_paid:
        return render_template('upgrade.html'), 403
    total_posts = Post.query.count()
    top_posts = Post.query.order_by(Post.views.desc()).limit(3).all()
    all_posts = Post.query.all()
    ai_stats = {}
    for p in all_posts:
        ai_stats[p.ai_model] = ai_stats.get(p.ai_model, 0) + 1
    return render_template('admin.html', total_posts=total_posts, top_posts=top_posts, ai_stats=ai_stats)

@app.route('/update_user', methods=['POST'])
@login_required
def update_user():
    old_name = request.form['old_username']
    new_name = request.form['new_username']
    if current_user.username != old_name:
        return "権限がありません", 403
    current_user.username = new_name
    user_posts = Post.query.filter_by(username=old_name).all()
    for post in user_posts:
        post.username = new_name
    db.session.commit()
    return redirect(url_for('mypage', username=new_name))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/tokusho')
def tokusho():
    return render_template('tokusho.html')

# データベース初期化
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.static_folder = 'static' 
    app.run(debug=True)