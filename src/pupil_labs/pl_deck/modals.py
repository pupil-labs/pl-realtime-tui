from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label


class ManualIpModal(ModalScreen[str]):
    CSS_PATH = "css/modal_manual_ip.tcss"

    def compose(self) -> ComposeResult:
        with Grid(id="dialog"):
            yield Label("Enter Device IP Address:", id="question")
            yield Input(placeholder="192.168.1.x", id="ip_input")
            yield Button("Connect", variant="primary", id="connect")
            yield Button("Cancel", variant="error", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect":
            self.dismiss(self.query_one("#ip_input", Input).value)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class TimeSyncModal(ModalScreen[tuple[str, str, bool] | None]):
    CSS_PATH = "css/modal_time_sync.tcss"

    def __init__(
        self,
        initial_sync: float = 300.0,
        initial_status: float = 10.0,
        initial_persist: bool = False,
    ):
        super().__init__()
        self.initial_sync = str(int(initial_sync))
        self.initial_status = str(int(initial_status))
        self.initial_persist = initial_persist

    def compose(self) -> ComposeResult:
        with Grid(id="dialog"):
            yield Label("Sync Interval (seconds):", id="question")
            yield Input(
                value=self.initial_sync,
                placeholder="300",
                id="sync_interval_input",
                type="number",
            )
            yield Label("Status Refresh (seconds):")
            yield Input(
                value=self.initial_status,
                placeholder="10",
                id="status_interval_input",
                type="number",
            )
            yield Label("Persist Settings:")
            yield Checkbox(
                "Save changes across sessions",
                value=self.initial_persist,
                id="persist_checkbox",
            )
            yield Button("Save Settings", variant="primary", id="set")
            yield Button("Cancel", variant="error", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "set":
            sync_val = self.query_one("#sync_interval_input", Input).value
            status_val = self.query_one("#status_interval_input", Input).value
            persist_val = self.query_one("#persist_checkbox", Checkbox).value
            self.dismiss((sync_val, status_val, persist_val))
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        sync_val = self.query_one("#sync_interval_input", Input).value
        status_val = self.query_one("#status_interval_input", Input).value
        persist_val = self.query_one("#persist_checkbox", Checkbox).value
        self.dismiss((sync_val, status_val, persist_val))
