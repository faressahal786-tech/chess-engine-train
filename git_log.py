"""Show git log (replacement for git log --oneline)."""
import os
from dulwich.repo import Repo
repo = Repo(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.git'))
c = repo.get_object(repo.head())
n = 0
while c and n < 20:
    print(f'  {c.id.decode()[:16]}  {c.message.decode().strip()[:60]}')
    c = repo.get_object(c.parents[0]) if c.parents else None
    n += 1
