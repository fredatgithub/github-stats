# coding: utf-8

from datetime import datetime
from datetime import timedelta
import json

import flask
from google.appengine.ext import ndb
from google.appengine.ext import deferred
from google.appengine.api import urlfetch
import github

from api import helpers
import auth
import config
import model
import util
import task

from main import app


@app.route('/<username>/<path:repo>')
@app.route('/<username>')
def gh_account(username, repo=None):
  username_ = username.lower()
  account_db = model.Account.get_by_id(username_)

  if not account_db:
    g = github.Github(config.CONFIG_DB.github_username, config.CONFIG_DB.github_password)
    try:
      account = g.get_user(username_)
    except github.GithubException as error:
      return flask.abort(error.status)

    account_db = model.Account.get_or_insert(
        account.login,
        avatar_url=account.avatar_url.split('?')[0],
        email=account.email or '',
        followers=account.followers,
        joined=account.created_at,
        name=account.name or account.login,
        organization=account.type == 'Organization',
        public_repos=account.public_repos,
        username=account.login,
      )

  if account_db.username != username or repo:
    return flask.redirect(flask.url_for('gh_account', username=account_db.username))

  task.queue_account(account_db)
  repo_dbs, repo_cursor = account_db.get_repo_dbs()

  return flask.render_template(
      'account/view.html',
      html_class='gh-view',
      title=account_db.name,
      account_db=account_db,
      repo_dbs=repo_dbs,
      next_url=util.generate_next_url(repo_cursor),
      username=account_db.username,
    )

###############################################################################
# Cron Stuff
###############################################################################
@app.route('/admin/cron/repo/')
def gh_admin_top():
  if config.PRODUCTION and 'X-Appengine-Cron' not in flask.request.headers:
    flask.abort(403)
  stars = util.param('stars', int) or 10000
  page = util.param('page', int) or 1
  per_page = util.param('per_page', int) or 100
  # TODO: fix formatting
  result = urlfetch.fetch('https://api.github.com/search/repositories?q=stars:>=%s&sort=stars&order=asc&page=%d&per_page=%d' % (stars, page, per_page))
  if result.status_code == 200:
    repos = json.loads(result.content)
  else:
    flask.abort(result.status_code)

  for repo in repos['items']:
    account = repo['owner']
    account_db = model.Account.get_or_insert(
        account['login'],
        avatar_url=account['avatar_url'].split('?')[0],
        email=account['email'] if 'email' in account else '',
        name=account['login'],
        followers=account['followers'] if 'followers' in account else 0,
        organization=account['type'] == 'Organization',
        username=account['login'],
      )

  return 'OK %d of %d' % (len(repos['items']), repos['total_count'])


@app.route('/admin/cron/sync/')
def admin_cron():
  if config.PRODUCTION and 'X-Appengine-Cron' not in flask.request.headers:
    flask.abort(403)
  account_dbs, account_cursor = model.Account.get_dbs(
      order=util.param('order') or 'modified',
      status=util.param('status'),
    )

  for account_db in account_dbs:
    task.queue_account(account_db)

  return 'OK'


@app.route('/admin/cron/repo/cleanup/')
def admin_repo_cleanup():
  if config.PRODUCTION and 'X-Appengine-Cron' not in flask.request.headers:
    flask.abort(403)
  task.queue_repo_cleanup(util.param('days', int) or 5)
  return 'OK'
