#!/usr/bin/env python3
# 24.11.2026 (owner, launcher 1.6.32): "@all" in the players' chat tags everybody in the launcher - the translator keeps it as it is
# (masked like a player's @name, community._mask_mentions), "@allies" is a word, not the tag; a message of "@all" alone is not
# translated at all.
# usage: python3 -I ladder/tests/test_chat_at_all.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import os, shutil, sys, tempfile
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_atall_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
C = L.community
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-70s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
check('"@all" masked', C._mask_mentions('@all go 3v3'), ('@M1 go 3v3', ['@all']))
check('"@ALL," masked as written', C._mask_mentions('кто играет, @ALL, заходите'), ('кто играет, @M1, заходите', ['@ALL']))
check('"@allies" is a word', C._mask_mentions('@allies win'), ('@allies win', []))
check('put back after the translation', C._unmask_mentions('@M1 who plays?', ['@all']), '@all who plays?')
C._nanogpt_key = lambda: 'k'
check('"@all" alone: not translated', C.translate('@all'), (None, '@all', '@all'))
shutil.rmtree(T, ignore_errors=True)
print('FAIL: %d' % len(fails) if fails else 'all ok'); sys.exit(1 if fails else 0)
