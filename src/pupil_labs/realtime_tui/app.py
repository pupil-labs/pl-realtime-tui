from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from collections import deque
from datetime import datetime
from typing import Any, ClassVar, cast

import aiohttp
from rich.text import Text
from scapy.layers.l2 import ARP, Ether
from scapy.sendrecv import srp
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.command import Hit, Hits, Provider
from textual.containers import Center, Horizontal, Vertical
from textual.fuzzy import Matcher
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    RichLog,
    Static,
)

from pupil_labs.realtime_api import Device, StatusUpdateNotifier
from pupil_labs.realtime_api.discovery import discover_devices
from pupil_labs.realtime_api.models import Recording, Sensor, Status
from pupil_labs.realtime_api.time_echo import TimeOffsetEstimator
from pupil_labs.realtime_tui.classes import DeviceClass
from pupil_labs.realtime_tui.events import EVENT_MAP
from pupil_labs.realtime_tui.modals import ManualIpModal, TimeSyncModal
from pupil_labs.realtime_tui.settings import load_settings, save_settings
from pupil_labs.realtime_tui.utils import (
    byte_size_to_gb,
    get_offset_age_color,
    make_battery_bar,
    make_signal_bar,
)


class SettingsProvider(Provider):
    async def search(self, query: str) -> Hits:
        matcher: Matcher = self.matcher(query)
        app: Pupil = cast(Pupil, self.app)

        label = "Enable Persistent Settings"
        if app.persist_settings:
            label = "Disable Persistent Settings"

        score: int | float = matcher.match(label)
        if score > 0:
            yield Hit(
                score,
                matcher.highlight(label),
                app.action_toggle_persistence,
                help="Save changes to events and intervals across sessions.",
            )


class Pupil(App):
    CSS_PATH = "css/main.tcss"
    COMMANDS = App.COMMANDS | {SettingsProvider}

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("d", "discover_devices", "Discover (mDNS)", show=True),
        Binding("n", "scan_network", "Deep Network Scan", show=True),
        Binding("r", "start_recording", "Rec All", show=True),
        Binding("s", "stop_recording", "Stop All", show=True),
        Binding("e", "toggle_edit", "Edit Events", show=True),
        Binding("t", "change_sync_interval", "Sync Interval", show=True),
        Binding("x", "deselect_device", "Deselect", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("/", "add_manually", "Add IP", show=True),
        *[
            Binding(str(i), f"send_event('{i}')", f"Evt {i}", show=False)
            for i in range(10)
        ],
    ]

    devices_info_list: reactive[list[DeviceClass]] = reactive(list)
    selected_device_address: reactive[str | None] = reactive(None)
    sync_interval: reactive[float] = reactive(300.0)
    status_interval: reactive[float] = reactive(10.0)
    persist_settings: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        settings = load_settings()
        if settings:
            self.sync_interval = settings.get("sync_interval", 300.0)
            self.status_interval = settings.get("status_interval", 10.0)
            self.persist_settings = settings.get("persist", False)
        self.event_log_deque: deque[tuple[float, str]] = deque(maxlen=10)
        self.notifiers: dict[str, StatusUpdateNotifier] = {}
        self.is_discovering = False
        self.sync_timer: Timer | None = None
        self.status_timer: Timer | None = None
        self.theme = "flexoki"

    def compose(self) -> ComposeResult:
        yield Header(icon="◎", name="Pupil Labs Controller")

        with Center(id="loading_container"):
            yield LoadingIndicator()
            yield Label("Scanning network...", id="loading_label")

        yield DataTable(id="devices_table")

        with Horizontal(id="controls"):
            events_panel = Vertical(id="events_panel")
            events_panel.border_title = "Event Triggers"
            with events_panel:
                yield DataTable(id="events_table")

            with Vertical(id="log_and_edit"):
                yield RichLog(
                    id="event_log", max_lines=200, highlight=True, markup=True
                )

                with Vertical(id="selected_device_panel"):
                    yield Static("Selected: None", id="selected_device_label")
                    with Horizontal(id="selected_device_buttons"):
                        yield Button("Start Selected", id="start_selected")
                        yield Button("Stop Selected", id="stop_selected")
                        yield Button("Deselect", id="deselect_device", variant="error")

                edit_container = Vertical(id="edit_container")
                edit_container.border_title = "Edit Event Key"
                with edit_container:
                    with Horizontal(id="edit_inputs"):
                        yield Input(placeholder="Key (0-9)", id="edit_key")
                        yield Input(placeholder="New Event Name", id="edit_name")
                    yield Button("Save Event Name", id="edit_save", variant="primary")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "Status",
            "Device Name",
            "IP Address",
            "SN",
            "Battery",
            "Signal (RTT)",
            "Offset (Age)",
            "Storage",
            "Last Event",
            "Rec Duration",
        )

        events_table = self.query_one("#events_table", DataTable)
        events_table.add_columns("Key", "Event Name")
        events_table.show_header = False
        events_table.cursor_type = "none"
        await self.update_events_table()

        self.log_message("App mounted. Starting auto-discovery...")
        self.discover_and_connect_devices()

        self.set_interval(1.0, self.update_device_table)
        self.status_timer = self.set_interval(
            self.status_interval, self.refresh_device_statuses
        )
        self.sync_timer = self.set_interval(self.sync_interval, self.update_all_offsets)

    def update_loading(self, message: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#loading_label", Static).update(message)

    async def setup_device(self, device: Device, ip_address: str) -> None:
        try:
            self.update_loading(f"Fetching status for {ip_address}...")
            status: Status = await device.get_status()

            self.update_loading(f"Syncing time with {status.phone.device_name}...")
            if status.phone.time_echo_port is None:
                raise ValueError("Device does not have a time echo port")  # noqa: TRY301
            time_offset_estimator = TimeOffsetEstimator(
                status.phone.ip, status.phone.time_echo_port
            )
            estimate = await time_offset_estimator.estimate()
            if estimate is None:
                raise ValueError("Could not estimate clock offset")  # noqa: TRY301
            clock_offset_ns = round(estimate.time_offset_ms.mean * 1_000_000)

            new_device_info = DeviceClass(
                device=device,
                address=device.address,
                phone_name=status.phone.device_name,
                sn=status.hardware.module_serial,
                estimate=estimate,
                estimator=time_offset_estimator,
                clock_offset_ns=clock_offset_ns,
                is_recording=False,
                is_online=True,
                last_status_update_time=time.time(),
                last_offset_update_time=time.time(),
                battery_level=status.phone.battery_level,
                storage=byte_size_to_gb(status.phone.memory),
                last_event_name="",
                last_event_time=0.0,
                last_event_pupil_ts=0.0,
                rec_duration_ns=status.recording.rec_duration_ns
                if status.recording
                else 0,
            )
            new_device_info.rtt_history.append(estimate.roundtrip_duration_ms.mean)

            def callback(component: Any, di: DeviceClass = new_device_info) -> None:
                self.on_status_update(component, di)

            notifier = StatusUpdateNotifier(device, callbacks=[callback])
            await notifier.receive_updates_start()
            self.notifiers[new_device_info.address] = notifier

            current_list: list[DeviceClass] = list(self.devices_info_list)
            current_list.append(new_device_info)
            current_list.sort(key=lambda d: d.address)
            connected_ips = [d.address.split(":")[0] for d in self.devices_info_list]
            self.devices_info_list: list[DeviceClass] = current_list
            if device.address not in connected_ips:
                self.log_message(
                    f"[#$success]Connected:[/] "
                    f"{status.phone.device_name} {device.address}"
                )
                self.notify(f"Connected to {status.phone.device_name} {device.address}")

        except Exception as e:
            self.log_message(f"[#$error]Error initializing {ip_address}: {e}[/]")
            await device.close()

    @work(exclusive=True)
    async def discover_and_connect_devices(self, timeout_seconds: float = 10) -> None:
        self.add_class("loading")
        self.update_loading("Scanning local network (mDNS)...")
        try:
            self.log_message(f"Scanning network ({timeout_seconds}s)...")
            existing_addresses = {dev.address for dev in self.devices_info_list}
            new_found = False
            async for dev_info in discover_devices(timeout_seconds=timeout_seconds):
                if dev_info.server in existing_addresses:
                    continue

                self.log_message(
                    f"Found new device: {dev_info.server} {dev_info.addresses}"
                )
                self.update_loading(f"Found {dev_info.server}. Connecting...")

                existing_addresses.add(dev_info.server)
                new_found = True
                device = await Device.from_discovered_device(dev_info).__aenter__()
                await self.setup_device(device, dev_info.server)

            if not self.devices_info_list:
                self.log_message("No devices found via mDNS.")
            elif new_found:
                self.log_message(
                    f"Scan complete. Total devices: {len(self.devices_info_list)}"
                )
        except Exception as e:
            self.log_message(f"Scan failed: {e}")
        finally:
            self.remove_class("loading")

    def _run_arp_scan(self, subnet: str) -> list[str]:
        """Run ARP scan in a thread-safe manner using Scapy if available."""
        try:
            ans, _ = srp(
                Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet),
                timeout=1.5,
                verbose=0,
            )

            return [received.psrc for _, received in ans]
        except Exception:
            return []

    async def _check_ip_status(
        self, session: aiohttp.ClientSession, ip: str
    ) -> str | None:
        """Check if an IP is a Pupil device. Returns IP if valid."""
        url = f"http://{ip}:8080/api/status"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=2.0)
            ) as resp:
                if resp.status == 200:
                    return ip
        except Exception:
            return None
        return None

    @work(exclusive=True)
    async def action_scan_network(self) -> None:
        """Smart network scan: tries ARP first, falls back to brute force."""
        self.log_message("Starting Deep Network Scan...")
        self.add_class("loading")
        self.update_loading("Determining local subnet...")

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception as e:
                self.log_message(f"[#$error]Could not determine local IP: {e}[/]")
                return

            subnet_base = ".".join(local_ip.split(".")[:-1])
            subnet_cidr = f"{subnet_base}.0/24"
            self.log_message(f"Target Subnet: {subnet_cidr}")

            ips_to_scan = []
            self.update_loading("Running ARP Scan (requires root/admin)...")
            active_ips = await asyncio.to_thread(self._run_arp_scan, subnet_cidr)
            if active_ips:
                self.log_message(f"ARP Scan found {len(active_ips)} active hosts.")
                ips_to_scan = active_ips
            else:
                self.log_message(
                    "ARP Scan failed or found no hosts (permission issue?). "
                    "Falling back to brute force."
                )

            if not ips_to_scan:
                ips_to_scan = [f"{subnet_base}.{i}" for i in range(1, 255)]

            existing_ips = {d.address.split(":")[0] for d in self.devices_info_list}
            existing_ips.add(local_ip)
            ips_to_scan = [ip for ip in ips_to_scan if ip not in existing_ips]

            self.update_loading(f"Probing {len(ips_to_scan)} IPs for Pupil devices...")

            found_ips = []
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                tasks = [self._check_ip_status(session, ip) for ip in ips_to_scan]
                results = await asyncio.gather(*tasks)
                found_ips = [ip for ip in results if ip]

            if found_ips:
                self.log_message(
                    f"Deep scan found {len(found_ips)} devices: {', '.join(found_ips)}"
                )
                for ip in found_ips:
                    self.connect_manual_device(ip)
            else:
                self.log_message("Deep scan finished. No new devices found.")

        except Exception as e:
            self.log_message(f"[#$error]Deep scan failed: {e}[/]")
        finally:
            self.remove_class("loading")

    @work(exclusive=False)
    async def connect_manual_device(self, ip: str) -> None:
        self.log_message(f"Connecting manually to {ip}...")
        self.add_class("loading")
        self.update_loading(f"Connecting to {ip}...")

        existing_addresses = {dev.address for dev in self.devices_info_list}
        full_address = f"{ip}:8080"
        if full_address in existing_addresses or ip in existing_addresses:
            self.log_message(f"Device {ip} already connected.")
            self.remove_class("loading")
            return
        try:
            device = Device(address=ip, port=8080)
            await device.__aenter__()
            await self.setup_device(device, full_address)
        except Exception as e:
            self.log_message(f"[red]Manual connection failed: {e}[/red]")
        finally:
            self.remove_class("loading")

    async def shutdown_notifiers(self) -> None:
        for notifier in self.notifiers.values():
            with contextlib.suppress(Exception):
                await notifier.receive_updates_stop()

    async def on_unmount(self) -> None:
        await self.shutdown_notifiers()
        for device_info in self.devices_info_list:
            if device_info.is_recording:
                with contextlib.suppress(Exception):
                    await device_info.device.recording_stop_and_save()
            await device_info.device.close()

    def log_message(self, message: str) -> None:
        try:
            log = self.query_one(RichLog)
            now = datetime.now().strftime("%H:%M:%S")
            log.write(
                Text.from_markup(rf"[dim]\[{now}][/] ") + Text.from_markup(message)
            )
        except Exception as e:
            print(f"LOG ERROR: {e} | {message}")

    def on_status_update(self, component: Any, device_info: DeviceClass) -> None:
        should_refresh = False
        try:
            if isinstance(component, Recording):
                if component.action == "started":
                    device_info.is_recording = True
                    self.call_next(
                        self.log_message,
                        (
                            f"[#$success]Started: {device_info.phone_name} "
                            f"(ID: {component.id})[/]"
                        ),
                    )
                    self.notify(f"Started: {device_info.phone_name}")
                    should_refresh = True
                elif component.action in ("stopped", "ERROR"):
                    device_info.is_recording = False
                    if component.action == "stopped":
                        self.call_next(
                            self.log_message,
                            f"[#$warning]Stopped: {device_info.phone_name}[/]",
                        )
                        self.notify(f"Saved: {device_info.phone_name}")
                    else:
                        self.call_next(
                            self.log_message, f"[#$error]Error: {component.message}[/]"
                        )
                    should_refresh = True

            elif isinstance(component, Sensor) and component.stream_error:
                device_info.is_recording = False
                self.call_next(
                    self.log_message,
                    (
                        f"[#$error]Sensor Error {device_info.phone_name}:"
                        f" {component.sensor}[/]"
                    ),
                )
                should_refresh = True

            if should_refresh:
                self.call_next(self.update_device_table)
        except Exception as e:
            print(f"Status Update Error: {e}")

    async def refresh_single_status(self, dev: DeviceClass) -> None:
        try:
            status = await dev.device.get_status()
            dev.battery_level = status.phone.battery_level
            dev.storage = byte_size_to_gb(status.phone.memory)
            dev.is_online = True
            if status.recording:
                dev.is_recording = True
                dev.rec_duration_ns = status.recording.rec_duration_ns
            else:
                dev.is_recording = False
                dev.rec_duration_ns = 0
            dev.last_status_update_time = time.time()
        except Exception:
            if dev.is_online:
                self.log_message(f"[#$error]Lost contact with {dev.phone_name}[/]")
                dev.is_online = False

    @work(exclusive=True)
    async def refresh_device_statuses(self) -> None:
        tasks = [self.refresh_single_status(dev) for dev in self.devices_info_list]
        if tasks:
            await asyncio.gather(*tasks)

    def update_device_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        now: int | float = time.time()

        for dev in self.devices_info_list:
            if not dev.is_online:
                status_icon = "⚫"
            elif dev.is_recording:
                status_icon = "🔴"
            else:
                status_icon = "🟢"

            bat_bar: str = make_battery_bar(dev.battery_level)

            offset_ms: int | float = dev.estimate.time_offset_ms.mean
            rtt_ms: int | float = dev.estimate.roundtrip_duration_ms.mean
            signal_bar: str = make_signal_bar(rtt_ms)

            age: int | float = now - dev.last_offset_update_time
            age_color: str = get_offset_age_color(age)
            offset_str = f"{offset_ms:+.1f}ms ([{age_color}]{age:.0f}s ago[/])"

            if dev.rec_duration_ns > 0:
                total_seconds: int = dev.rec_duration_ns // 1_000_000_000
                hours: int = total_seconds // 3600
                minutes: int = (total_seconds % 3600) // 60
                seconds: int = total_seconds % 60
                dur_str = f"{hours:02}:{minutes:02}:{seconds:02}"
            else:
                dur_str = "00:00:00"

            evt_str: str = dev.last_event_name
            if evt_str:
                ts_str = f"{dev.last_event_pupil_ts:.3f}"
                if now - dev.last_event_time < 2.0:
                    evt_str = f"[bold cyan reverse] {evt_str} [/] [dim]({ts_str})[/dim]"
                else:
                    evt_str = f"{evt_str} [dim]({ts_str})[/dim]"
            else:
                evt_str = "-"

            row = [
                status_icon,
                f"[bold]{dev.phone_name}[/bold]",
                dev.address.split(":")[0],
                dev.sn,
                bat_bar,
                signal_bar,
                offset_str,
                f"{dev.storage:.1f}GB",
                evt_str,
                dur_str,
            ]

            if not dev.is_online:
                row = [f"[dim]{c}[/dim]" if isinstance(c, str) else c for c in row]

            if dev.address in table.rows:
                pass
            else:
                table.add_row(*row, key=dev.address)

    async def update_events_table(self) -> None:
        table = self.query_one("#events_table", DataTable)
        table.clear()
        for key in sorted(EVENT_MAP.keys(), key=lambda x: int(x)):
            table.add_row(f"{key}", EVENT_MAP[key])

    def watch_selected_device_address(self, new_address: str | None) -> None:
        panel: Widget = self.query_one("#selected_device_panel")
        label: Static = self.query_one("#selected_device_label", Static)
        if new_address is None:
            panel.display = False
            label.update("Selected: None")
        else:
            panel.display = True
            with contextlib.suppress(StopIteration):
                device: DeviceClass = self.get_device_by_address(new_address)
                label.update(f"Selected: [bold]{device.phone_name}[/bold]")

    def get_device_by_address(self, address: str) -> DeviceClass:
        return cast(
            DeviceClass,
            next(dev for dev in self.devices_info_list if dev.address == address),
        )

    async def action_discover_devices(self) -> None:
        self.log_message("User-triggered discovery...")
        self.discover_and_connect_devices()

    def action_add_manually(self) -> None:
        def check_ip(ip: str | None) -> None:
            if ip:
                self.connect_manual_device(ip.strip())

        self.push_screen(ManualIpModal(), check_ip)

    def action_change_sync_interval(self) -> None:
        def set_intervals(values: tuple[str, str, bool] | None) -> None:
            if not values:
                return
            sync_val, status_val, persist_val = values

            if sync_val and sync_val.isdigit():
                new_sync = float(sync_val)
                if new_sync < 10:
                    new_sync = 10.0
                self.sync_interval = new_sync
                self.log_message(f"Sync interval set to {new_sync}s")
                if self.sync_timer:
                    self.sync_timer.stop()
                self.sync_timer = self.set_interval(
                    self.sync_interval, self.update_all_offsets
                )

            if status_val and status_val.isdigit():
                new_status = float(status_val)
                if new_status < 1:
                    new_status = 1.0
                self.status_interval = new_status
                self.log_message(f"Status interval set to {new_status}s")
                if self.status_timer:
                    self.status_timer.stop()
                self.status_timer = self.set_interval(
                    self.status_interval, self.refresh_device_statuses
                )

            self.persist_settings = persist_val
            save_settings(
                EVENT_MAP,
                self.sync_interval,
                self.status_interval,
                self.persist_settings,
            )

        self.push_screen(
            TimeSyncModal(
                self.sync_interval, self.status_interval, self.persist_settings
            ),
            set_intervals,
        )

    async def action_quit(self) -> None:
        self.exit()

    @work(exclusive=False)
    async def action_start_recording(self) -> None:
        count = 0
        for dev in self.devices_info_list:
            if dev.is_recording or not dev.is_online:
                continue
            try:
                dev.is_recording = True
                await dev.device.recording_start()
                self.log_message(f"Starting recording on {dev.phone_name}...")
                self.notify(f"Started: {dev.phone_name}")
                count += 1
            except Exception as e:
                dev.is_recording = False
                self.log_message(f"[#$error]Fail start {dev.phone_name}: {e}[/]")
                print(f"START ERROR: {e}")

        if count == 0:
            self.log_message("[#$warning]No eligible devices found to start.[/]")

        self.update_device_table()

    @work(exclusive=False)
    async def action_stop_recording(self) -> None:
        stopped_count = 0
        for dev in self.devices_info_list:
            is_selected = (
                self.selected_device_address
                and dev.address == self.selected_device_address
            )

            if dev.is_recording or is_selected:
                try:
                    dev.is_recording = False
                    await dev.device.recording_stop_and_save()
                    self.log_message(f"Stopped {dev.phone_name}")
                    self.notify(f"Saved: {dev.phone_name}")
                    stopped_count += 1
                except Exception as e:
                    self.log_message(f"[#$error]Fail stop {dev.phone_name}: {e}[/]")
                    print(f"STOP ERROR: {e}")

        if stopped_count == 0:
            self.log_message("[#$warning]No active recordings found to stop.[/]")

        self.update_device_table()

    @work(exclusive=False)
    async def action_send_event(self, key: str) -> None:
        if key not in EVENT_MAP:
            return
        event_name = EVENT_MAP[key]
        now_ns = time.time_ns()
        self.log_message(f"Event Triggered: [bold #$accent]{event_name}[/]")
        self.notify(f"Sent: {event_name}")

        targets = []
        if self.selected_device_address:
            with contextlib.suppress(StopIteration):
                targets.append(self.get_device_by_address(self.selected_device_address))
        else:
            targets = self.devices_info_list

        for dev in targets:
            if not dev.is_recording or not dev.is_online:
                continue
            ts = now_ns - dev.clock_offset_ns

            dev.last_event_name = event_name
            dev.last_event_time = time.time()
            dev.last_event_pupil_ts = ts / 1e9

            with contextlib.suppress(Exception):
                await dev.device.send_event(event_name, event_timestamp_unix_ns=ts)

    def action_toggle_edit(self) -> None:
        box = self.query_one("#edit_container")
        box.display = not box.display
        if box.display:
            self.query_one("#edit_key").focus()

    def action_deselect_device(self) -> None:
        self.selected_device_address = None
        self.log_message("Selection cleared.")

    def action_toggle_persistence(self) -> None:
        """Toggle persistent settings saving."""
        self.persist_settings = not self.persist_settings
        state = "enabled" if self.persist_settings else "disabled"
        self.log_message(f"Persistent settings {state}")
        self.notify(f"Persistence {state}")
        save_settings(
            EVENT_MAP, self.sync_interval, self.status_interval, self.persist_settings
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self.selected_device_address = event.row_key.value

    async def _save_edit(self) -> None:
        k_in: Input = self.query_one("#edit_key", Input)
        n_in: Input = self.query_one("#edit_name", Input)
        key, name = k_in.value, n_in.value
        if key in EVENT_MAP and name:
            EVENT_MAP[key] = name
            save_settings(
                EVENT_MAP,
                self.sync_interval,
                self.status_interval,
                self.persist_settings,
            )
            await self.update_events_table()
            k_in.value = ""
            n_in.value = ""
            self.query_one("#edit_container").display = False
            self.notify(f"Event '{key}' updated")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "edit_key":
            self.query_one("#edit_name").focus()
        elif event.input.id == "edit_name":
            await self._save_edit()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "edit_save":
            await self._save_edit()
        elif bid == "start_selected":
            if self.selected_device_address:
                dev: DeviceClass = self.get_device_by_address(
                    self.selected_device_address
                )
                if not dev.is_recording and dev.is_online:
                    try:
                        dev.is_recording = True
                        await dev.device.recording_start()
                        self.update_device_table()
                    except Exception as e:
                        dev.is_recording = False
                        self.log_message(f"Error: {e}")
        elif bid == "stop_selected":
            if self.selected_device_address:
                dev = self.get_device_by_address(self.selected_device_address)
                try:
                    dev.is_recording = False
                    await dev.device.recording_stop_and_save()
                    self.update_device_table()
                except Exception as e:
                    self.log_message(f"Error: {e}")
        elif bid == "deselect_device":
            self.action_deselect_device()

    async def update_single_device_offset(self, device_info: DeviceClass) -> bool:
        if not device_info.is_online:
            return False
        try:
            new_estimate = await device_info.estimator.estimate()
            if new_estimate is None:
                return False
        except Exception:
            return False
        else:
            device_info.estimate = new_estimate
            device_info.clock_offset_ns = round(
                new_estimate.time_offset_ms.mean * 1_000_000
            )
            device_info.last_offset_update_time = time.time()
            return True

    @work(exclusive=True)
    async def update_all_offsets(self) -> None:
        self.log_message("Syncing clocks...")
        tasks = [
            self.update_single_device_offset(dev) for dev in self.devices_info_list
        ]
        if tasks:
            await asyncio.gather(*tasks)
