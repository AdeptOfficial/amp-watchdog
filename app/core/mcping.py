"""Minecraft server-list-ping (SLP) liveness probe.

Why this exists: AMP's wake-on-connect sleep listener can wedge — it keeps
the game port open (TCP connect succeeds) but never answers the status
handshake, while AMP still reports AppState 50/Sleeping. GetInstances is
structurally blind to that, so the AMP checker cross-checks the player-facing
port with a real SLP exchange. A healthy instance answers whether online OR
sleeping (the sleep listener serves a cached MOTD), and a status ping does
NOT wake a sleeping instance — only a join does (verified on AMP 2.8.0.8,
2026-10-17; re-verify after AMP upgrades).

A plain TCP connect is NOT a valid probe here — the wedged listener accepts
connects. Only a completed handshake + status response counts as alive.
"""

import asyncio
import json
import struct


def _varint(n: int) -> bytes:
    out = b""
    while True:
        byte = n & 0x7F
        n >>= 7
        out += bytes([byte | (0x80 if n else 0)])
        if not n:
            return out


async def _read_varint(reader: asyncio.StreamReader) -> int:
    num = 0
    for i in range(5):
        byte = (await reader.readexactly(1))[0]
        num |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return num
    raise ValueError("varint too long")


async def probe(host: str, port: int, timeout: float = 5.0) -> bool:
    """True iff the server completes the SLP status exchange within timeout.

    Never raises: timeouts, refusals, resets and protocol garbage all mean
    "not alive" — the caller only needs the boolean.
    """

    async def _exchange() -> bool:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            addr = host.encode()
            # Handshake: id 0x00, protocol version (any), addr, port, next_state=1
            handshake = _varint(0) + _varint(772) + _varint(len(addr)) + addr
            handshake += struct.pack(">H", port) + _varint(1)
            writer.write(_varint(len(handshake)) + handshake)
            writer.write(b"\x01\x00")  # status request
            await writer.drain()

            length = await _read_varint(reader)
            # Bound the response and parse only inside its declared frame.
            # A socket accepting bytes is not evidence of a valid SLP response.
            if not 2 <= length <= 1_048_576:
                return False
            frame = asyncio.StreamReader()
            frame.feed_data(await reader.readexactly(length))
            frame.feed_eof()
            packet_id = await _read_varint(frame)
            if packet_id != 0x00:
                return False
            payload_len = await _read_varint(frame)
            if not 0 < payload_len <= length:
                return False
            payload = await frame.readexactly(payload_len)
            if await frame.read(1):
                return False
            return isinstance(json.loads(payload.decode("utf-8")), dict)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    try:
        return await asyncio.wait_for(_exchange(), timeout=timeout)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError):
        return False
