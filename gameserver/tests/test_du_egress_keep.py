#!/usr/bin/env python3
"""Moscow DU egress (22.11.2026, timeweb lost its network 20:19 UTC): python3 gameserver/tests/test_du_egress_keep.py [path/to/du_egress.py]
Before, the first OSError ("Network is unreachable") while opening a warm UDP socket ended Egress.keep() for good: the egress
stayed DOWN with no sockets until du-egress was restarted, so every Relic connection fell back to straight TCP from Russia.
Checks, on a local UDP endpoint with PING_EVERY 0.05 s:
- 6 failed socket opens in a row: keep() is still running and then holds SOCKS sockets; the outage is logged once
  (egress_sock_failed) and its end once (egress_sock_ok);
- a round that raises: logged as egress_round_error, keep() goes on."""
import asyncio, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'egress', 'du_egress.py')
sys.path.insert(0, os.path.dirname(os.path.abspath(SRC))); sys.path.insert(0, os.path.join(HERE, '..'))
import importlib.util
spec = importlib.util.spec_from_file_location('du_egress', SRC); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
logs = []; m.log = lambda **k: logs.append(k); m.PING_EVERY = 0.05
fails = []


def check(name, ok, info=''):
    print('  %-70s %s' % (name, 'ok' if ok else 'FAIL %s' % info), flush=True)
    if not ok: fails.append(name)


async def main():
    tr, _ = await asyncio.get_running_loop().create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=('127.0.0.1', 0))
    e = m.Egress('x', ('127.0.0.1', tr.get_extra_info('sockname')[1])); real = e.new_sock; n = {'f': 0}

    async def flaky():
        if n['f'] < 6: n['f'] += 1; raise OSError(101, 'Network is unreachable')
        return await real()
    e.new_sock = flaky
    task = asyncio.ensure_future(e.keep())
    await asyncio.sleep(0.6)
    check('keep() survives 6 failed socket opens', not task.done())
    check('then holds SOCKS sockets', len(e.socks) == m.SOCKS, len(e.socks))
    evs = [l['ev'] for l in logs]
    check('the outage logged once, its end once', evs.count('egress_sock_failed') == 1 and evs.count('egress_sock_ok') == 1, evs)
    good = e.round

    async def boom(): raise RuntimeError('test')
    e.round = boom; await asyncio.sleep(0.2); e.round = good; await asyncio.sleep(0.1)
    check('a failing round is logged and keep() goes on', not task.done() and any(l['ev'] == 'egress_round_error' for l in logs))
    task.cancel(); tr.close()

asyncio.run(main())
print('FAILED: %s' % ', '.join(fails) if fails else 'all ok')
sys.exit(1 if fails else 0)
