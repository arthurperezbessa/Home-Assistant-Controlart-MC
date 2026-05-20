"""Camada de protocolo TCP para os módulos cabeados ControlArt.

Os módulos MD-ETH-MCRL2 / MD-ETH-MCDM2 expõem um servidor TCP. Comandos são
strings ASCII terminadas em ``\\r\\n``. As respostas (``setcmd``, ``setdmmd``,
``setbmcb0md`` ...) e os eventos de keypad (``setcankpfb``) chegam pela mesma
conexão, então a integração mantém um socket persistente com reconexão
automática e um laço de leitura que despacha cada linha recebida.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

_TERMINATOR = "\r\n"
_RECONNECT_DELAYS = (1, 2, 5, 10, 20, 30)
_READ_CHUNK = 1024


class ControlArtProtocol:
    """Mantém uma conexão TCP persistente com um módulo ControlArt."""

    def __init__(
        self,
        host: str,
        port: int,
        message_callback: Callable[[str], None] | None = None,
        connect_callback: Callable[[], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._message_callback = message_callback
        self._connect_callback = connect_callback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._run_task: asyncio.Task | None = None
        self._closing = False
        self._connected = asyncio.Event()
        self._waiters: list[tuple[Callable[[str], bool], asyncio.Future]] = []
        self._write_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """True quando o socket está conectado."""
        return self._connected.is_set()

    @property
    def host(self) -> str:
        return self._host

    # ------------------------------------------------------------------ ciclo
    async def async_start(self) -> None:
        """Inicia o supervisor e aguarda a primeira conexão."""
        self._closing = False
        self._run_task = asyncio.create_task(self._supervisor())
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10)
        except asyncio.TimeoutError as err:
            await self.async_stop()
            raise ConnectionError(
                f"Sem resposta de {self._host}:{self._port}"
            ) from err

    async def async_stop(self) -> None:
        """Encerra a conexão e cancela o supervisor."""
        self._closing = True
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            self._run_task = None
        await self._close_socket()
        for _pred, fut in self._waiters:
            if not fut.done():
                fut.cancel()
        self._waiters.clear()

    async def _supervisor(self) -> None:
        """Conecta, lê e reconecta com backoff até o encerramento."""
        attempt = 0
        while not self._closing:
            try:
                self._reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
                attempt = 0
                self._connected.set()
                _LOGGER.debug("Conectado a %s:%s", self._host, self._port)
                if self._connect_callback is not None:
                    try:
                        self._connect_callback()
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Erro no connect_callback")
                await self._reader_loop()
            except (OSError, ConnectionError, asyncio.IncompleteReadError) as err:
                _LOGGER.debug("Conexão com %s caiu: %s", self._host, err)
            finally:
                self._connected.clear()
                await self._close_socket()
            if self._closing:
                break
            delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
            attempt += 1
            _LOGGER.debug("Reconectando a %s em %ss", self._host, delay)
            await asyncio.sleep(delay)

    async def _reader_loop(self) -> None:
        """Lê o stream, separa linhas por ``\\n`` e despacha."""
        assert self._reader is not None
        buffer = ""
        while not self._closing:
            data = await self._reader.read(_READ_CHUNK)
            if not data:
                raise ConnectionError("Conexão encerrada pelo módulo")
            buffer += data.decode("ascii", errors="ignore")
            while "\n" in buffer:
                raw, buffer = buffer.split("\n", 1)
                line = raw.strip("\r").strip()
                if line:
                    self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        _LOGGER.debug("RX %s: %s", self._host, line)
        for pred, fut in list(self._waiters):
            if not fut.done() and pred(line):
                fut.set_result(line)
                if (pred, fut) in self._waiters:
                    self._waiters.remove((pred, fut))
        if self._message_callback is not None:
            try:
                self._message_callback(line)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Erro processando linha: %s", line)

    # --------------------------------------------------------------- comandos
    async def async_send(self, command: str) -> None:
        """Envia um comando (best-effort)."""
        if not self.connected or self._writer is None:
            _LOGGER.warning(
                "Sem conexão com %s; comando descartado: %s", self._host, command
            )
            return
        async with self._write_lock:
            _LOGGER.debug("TX %s: %s", self._host, command)
            self._writer.write((command + _TERMINATOR).encode("ascii"))
            await self._writer.drain()

    async def async_query(
        self,
        command: str,
        predicate: Callable[[str], bool],
        timeout: float = 5.0,
    ) -> str:
        """Envia um comando e aguarda a primeira linha que satisfaça ``predicate``."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._waiters.append((predicate, fut))
        try:
            await self.async_send(command)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            for entry in list(self._waiters):
                if entry[1] is fut:
                    self._waiters.remove(entry)

    async def _close_socket(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass
        self._reader = None
        self._writer = None
