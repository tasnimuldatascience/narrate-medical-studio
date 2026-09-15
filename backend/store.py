"""Local project persistence. A transaction serializes each project revision."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('NARRATE_DATA', ROOT / 'data')).resolve()

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'studio.sqlite3', timeout=30)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        with db:
            yield db
    finally:
        db.close()

def list_projects():
    with connect() as db:
        return sorted([json.loads(r[0]) for r in db.execute('SELECT body FROM projects')], key=lambda p:p['updated_at'], reverse=True)

def get(project_id):
    with connect() as db:
        row = db.execute('SELECT body FROM projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise KeyError(project_id)
        return json.loads(row[0])

def create(project):
    with connect() as db:
        db.execute('INSERT INTO projects VALUES (?,?)', (project['id'], json.dumps(project)))

@contextmanager
def edit(project_id):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT body FROM projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise KeyError(project_id)
        project = json.loads(row[0])
        yield project
        project['updated_at'] = now()
        db.execute('UPDATE projects SET body=? WHERE id=?', (json.dumps(project), project_id))

def event(project, action, detail):
    project['history'].append({'at':now(), 'action':action, 'detail':detail})

def directory(project_id):
    # Only IDs persisted in the database can resolve to a directory.
    get(project_id)
    return DATA / project_id
