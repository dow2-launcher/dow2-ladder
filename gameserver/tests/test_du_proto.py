#!/usr/bin/env python3
"""du_proto.DuCore end to end in one process (05.11.2026): python3 gameserver/tests/test_du_proto.py
Two cores joined by an in-memory 'network' (delay, loss, faults), real time:
 1. 5 % loss both ways, ~25 s of game-like traffic + a 300 KB burst: every byte arrives in order, resends stay within the
    budget, no storm, no dead connection;
 2. a packet lost forever (its own datagram and every copy of it): the sender gives up after 10 resends (ev=dead), it does
    not keep resending;
 3. every ACK of one side lost: the same - dead, with a bounded number of packets;
 4. the receiver's acks come back, the sender's game floods 2000 small writes/s: packets/s on the wire stay paced (<= 250
    fresh + budget), the bytes coalesce into bigger packets, all delivered."""
import asyncio, os, random, struct, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import du_proto as dp

LOG = []


class Net:
    def __init__(self, delay=0.015, loss=0.0, drop=None):
        self.delay, self.loss, self.drop = delay, loss, drop or (lambda side, pkt: False)
        self.count = {0: 0, 1: 0}

    def link(self, side, peer_core):
        loop = asyncio.get_running_loop()
        def out(pkt):
            self.count[side] += 1
            if random.random() < self.loss or self.drop(side, pkt): return
            loop.call_later(self.delay * random.uniform(0.8, 1.2), lambda: peer_core[0] and peer_core[0].datagram(pkt[2], pkt[7:]))
        return out


async def pair(net, secs, feed_a=None, feed_b=None):
    got = {0: bytearray(), 1: bytearray()}; cores = [[None], [None]]
    a = dp.DuCore(1, 2, net.link(0, cores[1]), lambda d: got[0].extend(d), log=lambda ev, **k: LOG.append(('A', ev, k)))
    b = dp.DuCore(1, 2, net.link(1, cores[0]), lambda d: got[1].extend(d), log=lambda ev, **k: LOG.append(('B', ev, k)))
    cores[0][0], cores[1][0] = a, b
    sent = {0: bytearray(), 1: bytearray()}
    end = time.monotonic() + secs
    async def ticker():
        while time.monotonic() < end + 3:
            a.tick(); b.tick(); await asyncio.sleep(0.01)
    async def feeder(core, side, feed):
        k = 0
        while time.monotonic() < end and not core.closed:
            for chunk in feed(k):
                while not core.room() and not core.closed: await asyncio.sleep(0.005)
                core.write(chunk); sent[side].extend(chunk)
            k += 1; await asyncio.sleep(0.01)
    game = lambda k: [struct.pack('<I', k) + bytes([k % 251]) * 40] if k % 5 == 0 else []
    await asyncio.gather(ticker(), feeder(a, 0, feed_a or game), feeder(b, 1, feed_b or game))
    return a, b, sent, got


def check(name, cond, info=''):
    print(('ok   ' if cond else 'FAIL ') + name, info); return cond


async def main():
    ok = True
    # 1. loss 5 %, normal traffic + a burst
    burst = lambda k: ([struct.pack('<I', k) + b'B' * 1196] * 250 if k == 300 else []) + ([struct.pack('<I', k) + b'g' * 40] if k % 5 == 0 else [])
    net = Net(loss=0.05)
    a, b, sent, got = await pair(net, 25, feed_a=burst)
    ok &= check('loss 5%: all bytes A->B in order', bytes(got[1]) == bytes(sent[0][:len(got[1])]) and len(got[1]) == len(sent[0]), '%d/%d' % (len(got[1]), len(sent[0])))
    ok &= check('loss 5%: all bytes B->A in order', bytes(got[0]) == bytes(sent[1]), '%d/%d' % (len(got[0]), len(sent[1])))
    ok &= check('loss 5%: no storm, not dead', not a.fuse_tripped and not b.fuse_tripped and not a.closed and not b.closed, str(a.stats))
    ok &= check('loss 5%: resends within the budget', a.stats['resent'] <= 20 * 28 + 0.25 * a.stats['tx'] + 50, 'resent %d tx %d' % (a.stats['resent'], a.stats['tx']))
    # 2. one packet of A lost forever (its datagram and all copies)
    target = {}
    def eternal(side, pkt):
        if side != 0 or pkt[2] not in (3, 8, 9): return False
        if pkt[2] != 9:
            seq = struct.unpack('<I', pkt[7:11])[0]
            if 'seq' not in target and seq >= 20: target['seq'] = seq
            if target.get('seq') == seq: return True
        if pkt[2] in (8, 9):                                    # its copies, in data packets and in ACK2s
            o = 20 if pkt[2] == 8 else 16; k = pkt[o - 1]
            for _ in range(k):
                s, n = struct.unpack('<IH', pkt[o:o + 6])
                if s == target.get('seq'): return True
                o += 6 + n
        return False
    LOG.clear(); net = Net(drop=eternal)
    a, b, sent, got = await pair(net, 30)
    ok &= check('eternal loss: the sender ends the connection (ev=dead)', a.closed and a.closed_by == 'dead', a.closed_by)
    ok &= check('eternal loss: resends bounded', a.stats['resent'] <= 12, 'resent %d' % a.stats['resent'])
    # 3. all of B's acks lost (B sends no data: feed nothing)
    LOG.clear(); net = Net(drop=lambda side, pkt: side == 1 and pkt[2] in (4, 9))
    a, b, sent, got = await pair(net, 30, feed_b=lambda k: [])
    ok &= check('acks lost: the sender ends the connection (ev=dead)', a.closed and a.closed_by == 'dead', a.closed_by)
    ok &= check('acks lost: packets on the wire bounded', net.count[0] < 400, 'A sent %d datagrams' % net.count[0])
    # 4. the game floods 2000 writes/s of 30 bytes
    LOG.clear(); net = Net(loss=0.01)
    flood = lambda k: [struct.pack('<I', k) + bytes([i]) * 26 for i in range(20)]
    a, b, sent, got = await pair(net, 15, feed_a=flood)
    rate = net.count[0] / 15
    ok &= check('flood: everything delivered in order', bytes(got[1]) == bytes(sent[0]), '%d/%d' % (len(got[1]), len(sent[0])))
    ok &= check('flood: datagrams/s paced', rate < dp.PACE + 60, '%.0f/s for %d writes/s' % (rate, 2000))
    print('ALL OK' if ok else 'SOME FAILED'); return ok

if __name__ == '__main__':
    sys.exit(0 if asyncio.run(main()) else 1)
