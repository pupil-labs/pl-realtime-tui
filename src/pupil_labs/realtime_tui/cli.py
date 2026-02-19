import typer

from pupil_labs.realtime_tui.app import Pupil
from pupil_labs.realtime_tui.render import run_render

main = typer.Typer(
    help="""A TUI to monitor, control and send synchronized events to multiple
         eye-trackers""",
    context_settings={"help_option_names": ["-h", "--help"]},
)


@main.callback(invoke_without_command=True)
def entry(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        tui()


@main.command(help="Terminal dashboard to monitor and control connected eye-trackers.")
def tui() -> None:
    app = Pupil()
    app.run()


@main.command(
    help="Sync recordings based on an event and render a mosaic visualization."
)
def render(
    recs_dir: str = typer.Argument(".", help="Root folder containing recordings"),
    event: str = typer.Option("custom_event_1", help="Event name to sync on"),
    synced: bool = typer.Option(True, help="Align recordings based on the sync event"),
    duration: float = typer.Option(
        60.0, help="Duration of the output video in seconds"
    ),
    private: bool = typer.Option(True, help="Anonymize wearer names"),
    layout: str = typer.Option("star", help="Layout style: 'auto' or 'star'"),
    normalize: bool = typer.Option(False, help="Normalize pupil size data"),
    visualize: bool = typer.Option(False, help="Show live visualization"),
) -> None:
    success = run_render(
        recs_dir=recs_dir,
        event=event,
        synced=synced,
        duration=duration,
        private=private,
        normalize=normalize,
        layout=layout,
        visualize=visualize,
    )
    if not success:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    main()
