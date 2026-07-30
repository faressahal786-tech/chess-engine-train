"""Commit all changes to git (pure-Python, no git CLI needed)."""
import os, sys, stat, time
from dulwich.repo import Repo
from dulwich.objects import Blob, Tree, Commit

proj = os.path.dirname(os.path.abspath(__file__))
repo = Repo(os.path.join(proj, '.git'))

exclude = {'.git', '__pycache__', '.venv', 'checkpoints', 'logs', 'node_modules'}
files = []
for root, dirs, fnames in os.walk(proj):
    rel = os.path.relpath(root, proj)
    if exclude & set(rel.split(os.sep)): continue
    for f in fnames:
        if f.endswith(('.pyc', '.pyo')): continue
        files.append(os.path.relpath(os.path.join(root, f), proj))

entries = {}
for p in sorted(files):
    blob = Blob.from_string(open(os.path.join(proj, p), 'rb').read())
    repo.object_store.add_object(blob)
    entries[p.encode()] = (stat.S_IFREG | 0o644, blob.id)

tree = Tree()
for name, (mode, sha) in entries.items(): tree[name] = (mode, sha)
repo.object_store.add_object(tree)

t, msg = int(time.time()), (sys.argv[1] if len(sys.argv) > 1 else 'update').encode()
commit = Commit()
commit.tree = tree.id
commit.parents = [repo.refs[b'refs/heads/master']] if repo.refs[b'refs/heads/master'] else []
commit.author = commit.committer = b'opencode <opencode@localhost>'
commit.author_time = commit.commit_time = t
commit.author_timezone = commit.commit_timezone = 0
commit.message = msg
repo.object_store.add_object(commit)
repo.refs[b'refs/heads/master'] = commit.id
repo[b'HEAD'] = commit.id
print(f'  {commit.id.decode()}  {msg.decode()}')
