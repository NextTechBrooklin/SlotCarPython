"""Bluetooth LE transport for the RN4870 Transparent UART timing module.

All BLE work runs on a single background asyncio loop. Results are posted to a
thread-safe ``queue.Queue`` as :class:`LinkEvent` objects which the GUI drains
on its own thread - no Tk calls are ever made from the BLE thread.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bleak import BleakClient, BleakScanner

from . import protocol


# Scan filter: timing modules are named "Slot..." (e.g. "SlotCarMasters").
DEVICE_NAME_PREFIX = "slot"


def is_slot_device(name: str | None) -> bool:
    """True if the advertised name starts with "slot", ignoring case and leading spaces."""
    return bool(name) and name.strip().lower().startswith(DEVICE_NAME_PREFIX)


class ConnState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    address: str
    rssi: int | None
    is_uart: bool  # advertises the Transparent UART service


@dataclass(frozen=True)
class LinkEvent:
    """kind: 'log' | 'state' | 'frame' | 'scan_result' | 'scan_done'."""

    kind: str
    data: Any = None
    level: str = "info"  # for 'log': info | ok | warn | error | rx | tx


class BleManager:
    """Owns the asyncio loop, the scanner and the GATT client."""

    def __init__(self, events: queue.Queue) -> None:
        self.events = events
        self.state = ConnState.DISCONNECTED
        self.device_name = ""
        self._client: BleakClient | None = None
        self._notify_uuid = protocol.UART_TX_NOTIFY_UUID
        self._write_uuid = protocol.UART_RX_WRITE_UUID
        self._assembler = protocol.FrameAssembler()
        self._scan_stop: asyncio.Event | None = None
        self._scanning = False
        self._user_disconnect = False
        self._connect_task: asyncio.Task | None = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble-loop", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ infra
    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _emit(self, kind: str, data: Any = None, level: str = "info") -> None:
        self.events.put(LinkEvent(kind, data, level))

    def _log(self, text: str, level: str = "info") -> None:
        self._emit("log", text, level)

    def _set_state(self, state: ConnState) -> None:
        self.state = state
        self._emit("state", state)

    @property
    def scanning(self) -> bool:
        return self._scanning

    @property
    def connected(self) -> bool:
        return self.state is ConnState.CONNECTED

    # --------------------------------------------------------------- public API
    def scan(self, duration: float = 8.0) -> None:
        if not self._scanning:
            self._submit(self._scan(duration))

    def stop_scan(self) -> None:
        if self._scan_stop is not None:
            self._loop.call_soon_threadsafe(self._scan_stop.set)

    def connect(self, address: str, name: str = "") -> None:
        self._submit(self._connect(address, name))

    def disconnect(self) -> None:
        self._submit(self._disconnect(user=True))

    def send(self, payload: bytes) -> None:
        self._submit(self._send(payload))

    def shutdown(self, timeout: float = 4.0) -> None:
        try:
            self.stop_scan()
            self._submit(self._disconnect(user=True)).result(timeout=timeout)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    # ----------------------------------------------------------------- scanning
    async def _scan(self, duration: float) -> None:
        self._scanning = True
        self._scan_stop = asyncio.Event()
        seen: dict[str, DeviceInfo] = {}

        def on_adv(device, adv) -> None:
            address = (device.address or "").strip()
            if not address:
                return
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            prev = seen.get(address)
            name = (adv.local_name or device.name or "").strip() or (prev.name if prev else "")
            info = DeviceInfo(
                name=name,
                address=address,
                rssi=adv.rssi,
                is_uart=protocol.UART_SERVICE_UUID in uuids or bool(prev and prev.is_uart),
            )
            changed = (
                prev is None
                or prev.name != info.name
                or prev.is_uart != info.is_uart
                or abs((prev.rssi or 0) - (info.rssi or 0)) >= 4
            )
            seen[address] = info
            if changed:
                self._emit("scan_result", info)

        self._log("Scanning for Bluetooth LE devices...")
        try:
            scanner = BleakScanner(detection_callback=on_adv)
            await scanner.start()
            try:
                await asyncio.wait_for(self._scan_stop.wait(), timeout=duration)
            except asyncio.TimeoutError:
                pass
            finally:
                await scanner.stop()
            self._log(f"Scan finished - {len(seen)} device(s) found", "ok")
        except Exception as exc:
            self._log(f"Scan failed: {exc}", "error")
        finally:
            self._scanning = False
            self._scan_stop = None
            self._emit("scan_done", len(seen))

    # --------------------------------------------------------------- connection
    async def _connect(self, address: str, name: str) -> None:
        if self._client is not None:
            await self._disconnect(user=True)

        self.device_name = name or address
        self._user_disconnect = False
        self._assembler.clear()
        self._set_state(ConnState.CONNECTING)
        self._log(f"Connecting to {self.device_name} [{address}]...")

        client = BleakClient(address, disconnected_callback=self._on_link_lost)
        self._connect_task = asyncio.current_task()
        try:
            await client.connect(timeout=20.0)
            self._client = client
            await self._negotiate_mtu(client)
            self._resolve_characteristics(client)
            await client.start_notify(self._notify_uuid, self._on_notify)
            self._set_state(ConnState.CONNECTED)
            self._log(f"Connected to {self.device_name} (Transparent UART ready)", "ok")
        except (Exception, asyncio.CancelledError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError)
            self._log("Connection cancelled" if cancelled else f"Connection failed: {exc}",
                      "warn" if cancelled else "error")
            self._user_disconnect = True
            try:
                await client.disconnect()
            except BaseException:
                pass
            self._client = None
            self._set_state(ConnState.DISCONNECTED)
        finally:
            self._connect_task = None

    async def _negotiate_mtu(self, client: BleakClient) -> None:
        try:
            set_mtu = getattr(client, "set_mtu", None)
            if callable(set_mtu):
                await set_mtu(protocol.REQUESTED_MTU)
            else:
                backend = getattr(client, "_backend", None)
                acquire = getattr(backend, "_acquire_mtu", None)  # BlueZ
                if callable(acquire):
                    await acquire()
            self._log(f"MTU {client.mtu_size} bytes ({client.mtu_size - 3} byte payload)")
        except Exception as exc:
            self._log(f"MTU negotiation skipped: {exc}", "warn")

    def _resolve_characteristics(self, client: BleakClient) -> None:
        services = client.services
        service = services.get_service(protocol.UART_SERVICE_UUID)
        if service is None:
            raise RuntimeError(f"Transparent UART service {protocol.UART_SERVICE_UUID} not found")

        def props(ch) -> set[str]:
            return {p.lower() for p in getattr(ch, "properties", [])}

        notify = services.get_characteristic(protocol.UART_TX_NOTIFY_UUID)
        write = services.get_characteristic(protocol.UART_RX_WRITE_UUID)
        chars = list(service.characteristics)

        if notify is None or not props(notify) & {"notify", "indicate"}:
            notify = next((c for c in chars if props(c) & {"notify", "indicate"}), None)
            if notify is not None:
                self._log(f"Notify characteristic auto-selected: {notify.uuid}", "warn")
        if write is None or not props(write) & {"write", "write-without-response"}:
            write = next((c for c in chars if props(c) & {"write", "write-without-response"}), None)
            if write is not None:
                self._log(f"Write characteristic auto-selected: {write.uuid}", "warn")

        if notify is None:
            raise RuntimeError("No notify/indicate characteristic in UART service")
        if write is None:
            raise RuntimeError("No writable characteristic in UART service")

        self._notify_uuid = str(notify.uuid).lower()
        self._write_uuid = str(write.uuid).lower()
        self._log(
            f"TX notify {self._notify_uuid} ({','.join(sorted(props(notify)))}) | "
            f"RX write {self._write_uuid} ({','.join(sorted(props(write)))})"
        )

    async def _disconnect(self, user: bool) -> None:
        task = self._connect_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()  # abort an in-flight connect; its handler cleans up
            return
        client, self._client = self._client, None
        self._user_disconnect = user
        if client is None:
            if self.state is not ConnState.DISCONNECTED:
                self._set_state(ConnState.DISCONNECTED)
            return
        try:
            if client.is_connected:
                try:
                    await client.stop_notify(self._notify_uuid)
                except Exception:
                    pass
                await client.disconnect()
        except Exception as exc:
            self._log(f"Disconnect error: {exc}", "warn")
        self._set_state(ConnState.DISCONNECTED)
        self._log("Disconnected")

    def _on_link_lost(self, _client: BleakClient) -> None:
        if not self._user_disconnect:
            self._log("Bluetooth LE link lost", "error")
        self._client = None
        self._set_state(ConnState.DISCONNECTED)

    # ---------------------------------------------------------------- data path
    def _on_notify(self, _char: Any, data: bytearray) -> None:
        raw = bytes(data)
        chunk = raw.decode("ascii", errors="replace")
        level = "rx" if all(b < 0x80 for b in raw) else "warn"
        self._log(f"RX {chunk!r}  [{raw.hex(' ')}]", level)
        for frame in self._assembler.feed(chunk):
            self._emit("frame", frame)

    async def _send(self, payload: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            self._log(f"Not connected - {payload!r} not sent", "warn")
            return
        try:
            try:
                await client.write_gatt_char(self._write_uuid, payload, response=True)
            except Exception:
                await client.write_gatt_char(self._write_uuid, payload, response=False)
            self._log(f"TX {payload.decode('ascii', 'replace')!r}  [{payload.hex(' ')}]", "tx")
        except Exception as exc:
            self._log(f"Write failed: {exc}", "error")
