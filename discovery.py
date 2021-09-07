#!/usr/bin/python3

import socket
import struct

from uuid import getnode


def escape(data):
    return data.decode('latin-1').encode('unicode-escape').decode()

def screen(data):
    return ''.join((_ if _.isprintable() else '.') for _ in data.decode('latin-1'))


def iodata(addr):
    macaddr = struct.pack('!q', getnode())[2:]

    netaddr = tuple(int(_) for _ in addr.split('.'))

    gateway = tuple(int(_) for _ in addr.split('.'))
    netmask = (0xff, 0xff, 0xff, 0xff)

    msginfo = (
        ('16s', b'STR_BCAST'),
        ( '8s', b'RS1.0.1'),
        ( '2s', b'\x00\x00'),
        ('10s', b''),
        ('16s', b'TSP100LAN'),
        ( '8s', b'V2.1'),
        ( '8s', b'V2.1'),
        ('10s', b''),
        ('10s', bytes(macaddr)),
        ( '4s', bytes(netaddr)),
        ('16s', b'DHCP'),
        (' 4s', bytes(netmask)),
        (' 4s', bytes(gateway)),
        ('24s', b''),
        ('32s', b'Star'),
        ('32s', b'STAR'),
        ('64s', b'TSP143 (STR_T-001)'),
        ('32s', b'PRINTER'),
        (' 2s', b''),
    )

    msgdata = bytearray(b''.join(struct.pack(*_) for _ in msginfo))

    msgdata[24:26] = struct.pack('!h', len(msgdata))

    return msgdata


def thread():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(('', 22222))

    while True:
        data, rqaddr = server.recvfrom(1024)

        print('Discovery RQ: @%s:%s %s %s' % (*rqaddr, len(data), screen(data)))

        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.connect(rqaddr)
        rsaddr = client.getsockname()
        client.close()

        data = iodata(rsaddr[0])

        print('Discovery RS: @%s:%s %s %s' % (*rsaddr, len(data), screen(data)))

        server.sendto(data, rqaddr)


if __name__ == '__main__':
    thread()
