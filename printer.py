#!/usr/bin/python

import time
import asyncio


class StarArgSpec(object):
    def __init__(self, n):
        self.n = n

class Sized(StarArgSpec): pass

class Exact(StarArgSpec): pass

class Until(StarArgSpec):
    def __init__(self, n=None):
        if n is None:
            self.n = b'\x00'
        else:
            self.n = n


class StarPrinter(object):
    def __init__(self, directory):
        self.etb_count = 0
        self.directory = directory
        self.timestamp = None

        self.file = None
        self.buffer = []

        self._protocol = {
            b'\x00': ('do nothing', None),
            b'\x07': ('ext device 1 command 1', None),
            b'\x1a': ('ext device 2 command 1', None),
            b'\x17': ('update etb', self.update),
            b'\x62': ('dump bytes', self.output, Sized(2)),
            b'\x1b\x06\x01': ('real-time status', None),
            b'\x1b\x07': ('set ext device 1 pulse', None, Exact(1), Exact(1)),
            b'\x1b\x0c\x00': ('execute ff mode', None),
            b'\x1b\x0c\x19': ('execute em mode', None),
            b'\x1b\x1e\x45': ('reset normal etb', self.normal, Exact(1)),
            b'\x1b\x2a\x72\x41': ('enter raster mode', None),
            b'\x1b\x2a\x72\x42': ('quit raster mode', None),
            b'\x1b\x2a\x72\x45': ('set raster iot mode', None, Until()),
            b'\x1b\x2a\x72\x46': ('set raster ff mode', None, Until()),
            b'\x1b\x2a\x72\x50': ('set raster page length', None, Until()),
            b'\x1b\x2a\x72\x52': ('initialize raster mode', None),
            b'\x1b\x2a\x72\x51': ('set raster print quality', None, Until()),
            b'\x1b\x2a\x72\x54': ('set raster top margin', None, Until()),
            b'\x1b\x2a\x72\x59': ('move vertical position', self.scroll, Until()),
            b'\x1b\x2a\x72\x65': ('set raster em mode', None, Until()),
            b'\x1b\x2a\x72\x6d': ('set raster side margin', None, Exact(1), Until()),
            b'\x1b\x1d\x03\x03': ('start document', None, Exact(1), Exact(1)),
            b'\x1b\x1d\x03\x04': ('end document', None, Exact(1), Exact(1)),
        }

    def __enter__(self):
        if self.timestamp:
            raise RuntimeError()

        self.timestamp = time.localtime(time.time())

        cmds = {}

        for code in self._protocol:
            node = cmds
            for byte in code[:-1]:
                node = node.setdefault(byte, {})
            node[code[-1]] = self._protocol[code]

        return cmds

    def __exit__(self, exc_val, exc_type, exc_tb):
        if self.buffer:
            width = 72

            filename = '%s/%s.raw' % (
                self.directory or '.',
                time.strftime('%Y-%m-%d-%H-%M-%S', self.timestamp))
            with open(filename, 'w') as f:
                for line in self.buffer:
                    f.buffer.write(line.ljust(width, b'\x00'))

            self.buffer.clear()

        time.sleep(1)
        self.timestamp = None

    def output(self, data):
        self.buffer.append(data)

    def scroll(self, dots):
        dots, _, _ = dots.partition(b'\x00')
        dots = int(dots)
        self.buffer.extend(b'' for _ in range(dots))

    def update(self):
        self.etb_count += 1
        self.etb_count %= 32

    def normal(self, dummy):
        self.etb_count = 0

    def status(self):
        data = bytearray(b'\x23\x86\x00\x00\x00\x00\x00\x00\x00')
        data[7] = (((self.etb_count & 0x07) << 1) | ((self.etb_count & 0x18) << 2))
        return data


class StarService(object):
    def __init__(self, directory):
        self.printer = StarPrinter(directory)


    async def queue_handle(self, reader, writer):
        with self.printer as command_tree:
            addr = writer.get_extra_info('peername')

            print('PrintQueue @%s:%s + ' % (*addr,))

            command_node = command_tree
            command_code = bytearray()
            byte = b'\x00'
            while byte:
                byte = await reader.read(1)
                if not byte:
                    continue

                command_code.append(byte[0])
                command_info = command_node.get(byte[0])
                if isinstance(command_info, tuple):
                    command_name = command_info[0]
                    command_func = command_info[1]
                    command_spec = command_info[2:]

                    command_dump = '%s:' % (command_code.hex(),)
                    command_args = list()
                    for _ in command_spec:
                        if not _:
                            pass
                        elif isinstance(_, Exact):
                            data = await reader.readexactly(_.n)
                            command_args.append(data)
                            command_dump += ' %s' % (data.hex(),)
                        elif isinstance(_, Until):
                            size = len(_.n)
                            data = await reader.readuntil(_.n)
                            command_args.append(data)
                            command_dump += ' %s (%s)' % (data[:-size].hex(), data[:-size].decode())
                        elif isinstance(_, Sized):
                            size = int.from_bytes(await reader.readexactly(_.n), 'little')
                            data = await reader.readexactly(size)
                            command_args.append(data)
                            command_dump += ' (%s bytes)' % (size,)

                    print('PrintQueue @%s:%s = %s %s' % (*addr, command_dump, command_name))

                    if command_func:
                        command_func(*command_args)

                    command_node = command_tree
                    command_code = bytearray()
                elif isinstance(command_info, dict):
                    command_node = command_info
                elif command_node:
                    print('PrintQueue @%s:%s ! %s' % (*addr, command_code.hex()), end=' ')
                    command_node = {}
                else:
                    print('%s' % byte.hex(), end='-')

            writer.close()
            await writer.wait_closed()

            print('PrintQueue @%s:%s - ' % (*addr,))


    async def state_handle(self, reader, writer):
        addr = writer.get_extra_info('peername')

        print('PrintState @%s:%s + ' % (*addr,))

        code = bytearray()
        byte = b'\x00'
        while byte:
            byte = await reader.read(1)

            if not byte:
                continue

            if byte[0] == 0x32:
                data = self.printer.status()
                print('PrintState @%s:%s = %s %s' % (*addr, byte.hex(), data.hex()))
                writer.write(data)
                await writer.drain()
            elif byte[0]:
                print('PrintState @%s:%s ! %s' % (*addr, byte.hex()))

        writer.close()
        await writer.wait_closed()

        print('PrintState @%s:%s - ' % (*addr,))


    async def __call__(self):
        state_server = await asyncio.start_server(self.state_handle, '0.0.0.0', 9101)

        queue_server = await asyncio.start_server(self.queue_handle, '0.0.0.0', 9100)

        tasks = {
            asyncio.create_task(state_server.serve_forever()),
            asyncio.create_task(queue_server.serve_forever()),
        }

        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        queue_server.cancel()
        state_server.cancel()


if __name__ == '__main__':
    try:
        asyncio.run(StarService(None)())
    except KeyboardInterrupt:
        pass
