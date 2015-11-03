"""
Main views of PSKB app
"""

from flask import redirect, url_for, session, request, render_template, flash, json
from flask_oauthlib.client import OAuth

from . import app, db
from .models import Article, User, Tag

oauth = OAuth(app)

github = oauth.remote_app(
    'github',
    consumer_key=app.config['GITHUB_CLIENT_ID'],
    consumer_secret=app.config['GITHUB_SECRET'],
    request_token_params={'scope': ['gist', 'user:email']},
    base_url='https://api.github.com/',
    request_token_url=None,
    access_token_method='POST',
    access_token_url='https://github.com/login/oauth/access_token',
    authorize_url='https://github.com/login/oauth/authorize'
)


GIST_FILE = 'article.md'

@app.route('/')
def index():
    #if 'github_token' in session:
        #return redirect(url_for('user_profile'))

    # FIXME: This should only fetch the most recent x number.
    articles = Article.query.all()

    return render_template('index.html', articles=articles)


@app.route('/login')
def login():
    return github.authorize(callback=url_for('authorized', _external=True))


@app.route('/logout')
def logout():
    session.pop('github_token', None)
    return redirect(url_for('index'))


@app.route('/github/authorized')
def authorized():
    resp = github.authorized_response()
    if resp is None:
        return 'Access denied: reason=%s error=%s' % (
            request.args['error'], request.args['error_description'])

    session['github_token'] = (resp['access_token'], '')

    return redirect(url_for('user_profile'))


@app.route('/user/')
def user_profile():
    if 'github_token' not in session:
        return redirect(url_for('login'))

    # FIXME: Error handling
    me = github.get('user').data
    email = get_primary_github_email_of_logged_in()

    user = User.query.filter_by(github_username=me['login']).first()
    if user is None:
        user = User(me['login'], email)
        db.session.add(user)
        db.session.commit()
    elif user.email != email:
        user.email = email
        db.session.add(user)
        db.session.commit()

    if me['name']:
        session['name'] = me['name']

    if me['login']:
        session['login'] = me['login']

    return render_template('profile.html', body=me)


@app.route('/write/<github_id>')
@app.route('/write/', defaults={'github_id': None})
def write(github_id):
    article_text = ''
    title = ''

    if github_id is None:
        github_id = ''
    else:
        article = Article.query.filter_by(github_id=github_id).first()
        if article is None:
            raise ValueError('No article found in database')

        title = article.title

        resp = github.get('gists/%s' % (github_id))
        if resp.status == 200:
            article_text = resp.data['files'][GIST_FILE]['content']

    # The path here tells the Epic Editor what the name of the local storage
    # file is called.  The file is overwritten if it exists so doesn't really
    # matter what name we use here.
    return render_template('editor.html', path='myfile', github_id=github_id,
                           article_text=article_text, title=title)


@app.route('/save/', methods=['POST'])
def save():
    # Update content on github
    if not request.form['github_id']:
        pass
    # Create content on github
    else:
        pass

    # FIXME: We should create this gist as pluralsight not as this user but
    # with this user as the author.

    # Commit article to our db first so we can rollback if the github api call
    # fails...
    user = User.query.filter_by(github_username=session['login']).first()
    if user is None:
        # FIXME: Handle this, maybe get_or_404()
        raise ValueError('No user found in session')

    # Data is stored in form with input named content which holds json. The
    # json has the 'real' data in the 'content' key.
    content = json.loads(request.form['content'])['content']
    gist_info = {'files':  {GIST_FILE: {'content': content}}}

    resp = github.post('gists', data=gist_info, format='json')

    if resp.status == 201:
        try:
            gist_url = 'https://gist.github.com/%s/%s' % (session['login'],
                                                          resp.data['id'])
        except KeyError:
            gist_url = ''

        article = Article(title=request.form['title'], author_id=user.id,
                          github_id=resp.data['id'])
        db.session.add(article)
        db.session.commit()

        return render_template('article.html', gist_url=gist_url)
    else:
        # FIXME: Handle errors
        flash('Failed creating gist: %d' % (resp.status))
        return redirect(url_for('index'))


def get_primary_github_email_of_logged_in():
    """Get primary email address of logged in user"""

    resp = github.get('user/emails')
    if resp.status != 200:
        flash('Failed reading user email addresses: %s' % (resp.status))
        return None

    for email_data in resp.data:
        if email_data['primary']:
            return email_data['email']

    flash('No primary email address found')
    return None


@github.tokengetter
def get_github_oauth_token():
    return session.get('github_token')
