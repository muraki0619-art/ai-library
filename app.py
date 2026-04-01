from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ai_library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    # 権限フラグ
    is_admin = db.Column(db.Boolean, default=False) # 管理者権限
    is_paid = db.Column(db.Boolean, default=False)  # 有料会員権限

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
    
    # --- 既存の3列用データ ---
    hot_posts = Post.query.filter(Post.created_at >= three_days_ago).order_by(Post.views.desc()).limit(5).all()
    if not hot_posts: hot_posts = Post.query.order_by(Post.views.desc()).limit(5).all()
    new_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    evergreen_posts = Post.query.order_by(Post.views.desc()).limit(5).all()

    # --- ジャンル別データ (辞書にまとめて送ると管理が楽です) ---
    genres = ['小説', 'エッセイ', '論文', '詩', 'その他']
    genre_data = {}
    for g in genres:
        # 各ジャンル最大4件ずつ、閲覧数が多い順に取得
        genre_data[g] = Post.query.filter_by(genre=g).order_by(Post.views.desc()).limit(4).all()

    return render_template('index.html', 
                           hot_posts=hot_posts, 
                           new_posts=new_posts, 
                           evergreen_posts=evergreen_posts,
                           genre_data=genre_data) # まとめて渡す

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
            # 💡 初回登録時に自分を管理者に設定するロジック
            is_admin_flag = (username == "iorin") # ← あなたの希望するユーザー名に変えてください
            new_user = User(
                username=username, 
                password=generate_password_hash(password, method='pbkdf2:sha256'),
                is_admin=is_admin_flag,
                is_paid=is_admin_flag # 管理者は有料機能も開放
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

# --- 特定のジャンルの全作品を表示する格納庫 ---
@app.route('/genre/<name>')
def genre_view(name):
    # そのジャンルに一致する全投稿を、新しい順（created_at.desc()）に取得
    posts = Post.query.filter_by(genre=name).order_by(Post.created_at.desc()).all()
    # 存在しないジャンルが叩かれた場合でも、空のリストが渡るだけでエラーにはなりません
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
    # 🔒 権限チェック: 管理者でも有料ユーザーでもなければリダイレクト
    if not current_user.is_admin and not current_user.is_paid:
        return render_template('upgrade.html'), 403

    total_posts = Post.query.count()
    top_posts = Post.query.order_by(Post.views.desc()).limit(3).all()
    all_posts = Post.query.all()
    ai_stats = {}
    for p in all_posts:
        ai_stats[p.ai_model] = ai_stats.get(p.ai_model, 0) + 1
    return render_template('admin.html', total_posts=total_posts, top_posts=top_posts, ai_stats=ai_stats)

# --- ユーザー名の変更処理を追加 ---
@app.route('/update_user', methods=['POST'])
@login_required
def update_user():
    old_name = request.form['old_username']
    new_name = request.form['new_username']
    
    # ログイン中のユーザー本人か確認
    if current_user.username != old_name:
        return "権限がありません", 403

    # 1. ユーザーテーブルの名前を更新
    current_user.username = new_name
    
    # 2. 過去の全ての投稿の作成者名も一括で更新
    user_posts = Post.query.filter_by(username=old_name).all()
    for post in user_posts:
        post.username = new_name
        
    db.session.commit()
    # 新しい名前のマイページへリダイレクト
    return redirect(url_for('mypage', username=new_name))

# データベース初期化
with app.app_context():
    db.create_all()

    # app.py の一番下付近
if __name__ == "__main__":
    # staticフォルダの場所を明示的に指定（必要な場合）
    app.static_folder = 'static' 
    app.run(debug=True)