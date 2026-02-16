import logging
import pathlib
from collections import deque
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
import typer
from rich.logging import RichHandler
from tqdm import tqdm

import pupil_labs.neon_recording as nr
import pupil_labs.video as plv
from pupil_labs.neon_recording.neon_recording import NeonRecording
from pupil_labs.neon_recording.timeseries.av.video import GrayFrame

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)


def get_cv2_palette(
    num_colors: int = 7, cmap: int = cv2.COLORMAP_HSV
) -> list[tuple[int, int, int]]:
    gray_gradient = np.linspace(0, 255, num_colors).astype(np.uint8).reshape(1, -1)
    palette_bgr = cv2.applyColorMap(gray_gradient, cmap).squeeze()
    return [tuple(int(c) for c in color) for color in palette_bgr]


COLOR_PALETTE = get_cv2_palette(10)


def get_event_timestamp(
    recording: nr.NeonRecording,
    event_name: str,
    rec_path: pathlib.Path | None = None,
    choice: int | None = None,
) -> tuple[np.int64 | None, int | None]:
    try:
        events = recording.events.by_name[event_name]
        if len(events) == 0:
            return None, None
        if len(events) == 1:
            return events[0], 0

        name = rec_path.name if rec_path else "recording"
        typer.echo(f"\nMultiple '{event_name}' events found in {name}:")
        for i, ev in enumerate(events):
            typer.echo(f"  [{i}] {unix_to_hhmmss(ev)}")

        if choice is None:
            choice = typer.prompt(
                "Select event index. Same would be applied to all recordings",
                default=0,
                type=int,
            )
        if 0 <= choice < len(events):
            return events[choice], choice
        return events[0], 0

    except Exception:
        return None, None


def unix_to_hhmmss(timestamp_ns: int) -> str:
    seconds = timestamp_ns / 1e9
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%H:%M:%S.%f")[:-3]


def load_recordings(
    recs_dir: pathlib.Path, event_name: str
) -> list[tuple[nr.NeonRecording, np.int64]]:
    valid_recs = []
    candidates = [p.parent for p in recs_dir.rglob("info.json")]
    choice = None
    for p in candidates:
        try:
            rec = nr.open(p)
            ts, choice = get_event_timestamp(rec, event_name, rec_path=p, choice=choice)
            if ts is not None:
                valid_recs.append((rec, ts))
            else:
                logging.warning(
                    f"Event '{event_name}' not found in recording at {p}. Skipping."
                    f"Did you mean one of these events? "
                    f"{', '.join(f'{e}' for e in rec.events.by_name)}"
                )
        except Exception:
            logging.warning(f"Failed to load recording from {p}. Skipping.")
            continue
    valid_recs.sort(key=lambda x: x[0].start_time)
    return valid_recs


def iter_rec(
    valid_recs: list[tuple[NeonRecording, np.int64]],
    start_time: np.int64 | None = None,
    duration: float = 60.0,
) -> tuple[Any, int]:
    duration_ns = int(duration * 1e9)
    interval_ns = int(0.033 * 1e9)
    min_len = float("inf")
    streams = []
    for rec, event_ts in valid_recs:
        t0 = start_time if start_time is not None else event_ts
        t1 = t0 + duration_ns
        timestamps = rec.scene.time
        target_ts = np.arange(t0, t1, interval_ns, dtype=np.int64)
        indices = np.searchsorted(timestamps, target_ts)
        indices = indices[indices < len(timestamps)]
        subset = timestamps[indices]
        min_len = min(min_len, len(subset))
        streams.append(
            zip(
                rec.scene.sample(subset),
                rec.gaze.sample(subset),
                rec.pupil.sample(subset),
                rec.blinks.sample(subset),
                subset,
                strict=False,
            )
        )
    return zip(*streams, strict=False), int(min_len)


def precompute_geometry(
    valid_recs: list[tuple[nr.NeonRecording, int]],
    width: int = 1920,
    height: int = 1080,
    margin: int = 10,
    layout: str = "star",
) -> tuple[np.ndarray, list[np.ndarray], tuple[int, int, int, int]]:
    width, height = (width // 2) * 2, (height // 2) * 2
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    video_matrices = []

    if layout == "star":
        video_zone_w = (2 * width) // 3
        plot_zone_w = width - video_zone_w

        slot_w = video_zone_w // 2
        slot_h = height // 2

        for i in range(min(len(valid_recs), 4)):
            row, col = divmod(i, 2)
            qx, qy = col * slot_w, row * slot_h
            rec = valid_recs[i][0]

            scale = min(
                (slot_w - 2 * margin) / rec.scene.width,
                (slot_h - 2 * margin) / rec.scene.height,
            )

            tx = qx + (slot_w - rec.scene.width * scale) / 2
            ty = qy + (slot_h - rec.scene.height * scale) / 2
            video_matrices.append(
                np.array([[scale, 0, tx], [0, scale, ty]], dtype=np.float32)
            )

        if len(valid_recs) >= 5:
            rec = valid_recs[4][0]
            size_factor = 0.8
            center_scale = min(
                ((slot_w * size_factor) - 4 * margin) / rec.scene.width,
                ((slot_h * size_factor) - 4 * margin) / rec.scene.height,
            )

            tx = (video_zone_w / 2) - (rec.scene.width * center_scale) / 2
            ty = (height / 2) - (rec.scene.height * center_scale) / 2
            video_matrices.append(
                np.array(
                    [[center_scale, 0, tx], [0, center_scale, ty]], dtype=np.float32
                )
            )

        plot_roi = (
            video_zone_w + margin,
            margin,
            plot_zone_w - 2 * margin,
            height - 2 * margin,
        )

    else:
        n_slots = len(valid_recs) + 1
        cols = int(np.ceil(np.sqrt(n_slots)))
        rows = int(np.ceil(n_slots / cols))
        slot_w, slot_h = ((width // cols) // 2) * 2, ((height // rows) // 2) * 2

        for i in range(len(valid_recs)):
            row, col = divmod(i, cols)
            qx, qy = col * slot_w, row * slot_h
            rec = valid_recs[i][0]
            scale = min(
                (slot_w - 2 * margin) / rec.scene.width,
                (slot_h - 2 * margin) / rec.scene.height,
            )

            video_matrices.append(
                np.array(
                    [
                        [scale, 0, qx + (slot_w - rec.scene.width * scale) / 2],
                        [0, scale, qy + (slot_h - rec.scene.height * scale) / 2],
                    ],
                    dtype=np.float32,
                )
            )

        p_row, p_col = divmod(n_slots - 1, cols)
        plot_roi = (
            p_col * slot_w + margin,
            p_row * slot_h + margin,
            slot_w - 2 * margin,
            slot_h - 2 * margin,
        )

    return canvas, video_matrices, plot_roi


class AestheticTimeSeriesPlotter:
    def __init__(
        self,
        num_streams: int,
        max_len: int = 300,
        y_range: tuple[float, float] = (1.5, 8.0),
        norm_bounds: list[tuple[float, float]] | None = None,
    ) -> None:
        self.histories: list[deque] = [
            deque(maxlen=max_len) for _ in range(num_streams)
        ]
        self.max_len, self.norm_bounds = max_len, norm_bounds
        self.y_min: float = 0.0 if norm_bounds else y_range[0]
        self.y_max: float = 1.0 if norm_bounds else y_range[1]
        self.title = "Normalized Pupil" if norm_bounds else "Pupil Diameter (mm)"

    def __call__(
        self,
        canvas: np.ndarray,
        roi: tuple[int, int, int, int],
        multi_rec_data: list[Any],
    ) -> np.ndarray:
        x, y, w, h = roi
        overlay = canvas[y : y + h, x : x + w].copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (15, 15, 15), -1)
        canvas[y : y + h, x : x + w] = cv2.addWeighted(
            canvas[y : y + h, x : x + w], 0.3, overlay, 0.7, 0
        )
        plot_area = canvas[y : y + h, x : x + w]

        cv2.putText(
            plot_area,
            self.title,
            (10, 40),
            cv2.FONT_HERSHEY_DUPLEX,
            0.9,
            (220, 220, 220),
            1,
        )

        y_ticks = 5
        for i in range(y_ticks + 1):
            val = self.y_max - (i * (self.y_max - self.y_min) / y_ticks)
            curr_y = int(i * h / y_ticks)
            cv2.line(plot_area, (0, curr_y), (w, curr_y), (60, 60, 60), 1)
            cv2.putText(
                plot_area,
                f"{val:.1f}",
                (5, curr_y - 5),
                cv2.FONT_HERSHEY_PLAIN,
                0.8,
                (150, 150, 150),
                1,
            )

        for i, rec_data in enumerate(multi_rec_data):
            try:
                is_blink = (
                    rec_data[3].start_time < rec_data[2].time < rec_data[3].stop_time
                )
                val = (
                    np.nan
                    if is_blink
                    else np.nanmean([
                        rec_data[2].diameter_left,
                        rec_data[2].diameter_right,
                    ])
                )
                if not np.isnan(val) and self.norm_bounds:
                    p_min, p_max = self.norm_bounds[i]
                    val = (
                        np.clip((val - p_min) / (p_max - p_min), 0, 1)
                        if p_max > p_min
                        else 0
                    )
            except Exception:
                val = np.nan
            self.histories[i].append(val)

            pts: list[list[int]] = []
            for j, v in enumerate(self.histories[i]):
                if np.isnan(v):
                    if len(pts) > 1:
                        cv2.polylines(
                            plot_area,
                            [np.array(pts, np.int32)],  # type: ignore[arg-type]
                            False,
                            COLOR_PALETTE[i % len(COLOR_PALETTE)],
                            2,
                            cv2.LINE_AA,
                        )
                    pts = []
                else:
                    px, py = (
                        int(j * w / self.max_len),
                        int(h - (v - self.y_min) * h / (self.y_max - self.y_min)),
                    )
                    pts.append([px, py])
            if len(pts) > 1:
                cv2.polylines(
                    plot_area,
                    [np.array(pts, np.int32)],  # type: ignore[arg-type]
                    False,
                    COLOR_PALETTE[i % len(COLOR_PALETTE)],
                    2,
                    cv2.LINE_AA,
                )

        return plot_area


def generate_individual_contact_sheet(
    wearer_path: pathlib.Path, wearer_name: str
) -> None:
    thumbs = sorted((wearer_path / "thumbnails").glob("*.jpg"))
    if not thumbs:
        return
    images = [cv2.resize(cv2.imread(str(p)), (400, 225)) for p in thumbs]
    strip = np.hstack(images)  # Horizontal
    cv2.imwrite(str(wearer_path / f"{wearer_name}_horizontal_strip.jpg"), strip)


def generate_master_contact_sheet(
    output_root: pathlib.Path,
    wearer_folders: list[pathlib.Path],
    wearer_names: list[str],
) -> None:
    rows = []
    target_w = 400
    for w_path, _ in zip(wearer_folders, wearer_names, strict=False):
        thumbs = sorted((w_path / "thumbnails").glob("*.jpg"))
        if not thumbs:
            continue
        processed = [cv2.resize(cv2.imread(str(p)), (target_w, 300)) for p in thumbs]
        rows.append(np.hstack(processed))
    if rows:
        cv2.imwrite(str(output_root / "master_contact_sheet.jpg"), np.vstack(rows))


def run_render(  # noqa: C901
    recs_dir: str,
    event: str,
    synced: bool = True,
    duration: float = 60.0,
    private: bool = True,
    normalize: bool = False,
    layout: str = "star",
    visualize: bool = False,
) -> bool:
    THUMBNAILS_EVERY = 3.0
    recs_path = pathlib.Path(recs_dir)
    valid_recs: list[tuple[NeonRecording, np.int64]] = load_recordings(recs_path, event)
    if not valid_recs:
        logging.error(f"No recordings found with event '{event}' in {recs_dir}")
        return False

    mode_str = (
        f"{'private' if private else 'public'}_{'synced' if synced else 'unsynced'}"
    )
    output_root = recs_path / f"analysis_{mode_str}"
    output_root.mkdir(exist_ok=True)
    mosaic_filename = f"mosaic_{mode_str}.mp4"

    wearer_folders, wearer_writers, wearer_names = [], [], []
    for i, (rec, _) in enumerate(valid_recs):
        name = rec.wearer["name"] if not private else f"Wearer_{i + 1}"
        w_path = output_root / name
        w_path.mkdir(exist_ok=True)
        (w_path / "thumbnails").mkdir(exist_ok=True)
        wearer_folders.append(w_path)
        wearer_names.append(name)
        wearer_writers.append(plv.Writer(str(w_path / f"{name}_individual.mp4")))

    norm_bounds = []
    if normalize:
        for rec, _ in valid_recs:
            d = np.concatenate([rec.pupil.diameter_left, rec.pupil.diameter_right])
            norm_bounds.append((np.nanmin(d), np.nanmax(d)))

    base_canvas, matrices, plot_roi = precompute_geometry(valid_recs, layout=layout)
    start_time = None if synced else valid_recs[0][1]
    frame_gen, n_frames = iter_rec(valid_recs, start_time=start_time, duration=duration)
    plotter = AestheticTimeSeriesPlotter(len(valid_recs), norm_bounds=norm_bounds)
    dts, next_thumb_target_sec = 0.0, 0.0
    with (
        plv.Writer(str(output_root / mosaic_filename)) as mosaic_writer,
        plv.Writer(str(output_root / "pupil_size_plot.mp4")) as pupil_writer,
    ):
        for multi_rec_data in tqdm(frame_gen, total=n_frames, desc="Processing"):
            canvas = base_canvas.copy()
            elapsed_sec = (multi_rec_data[0][4] - valid_recs[0][1]) / 1e9
            capture_now = elapsed_sec >= next_thumb_target_sec
            if capture_now:
                next_thumb_target_sec += THUMBNAILS_EVERY

            for i, (matrix, (scene, gaze, _, blink, _)) in enumerate(
                zip(matrices, multi_rec_data, strict=False)
            ):
                if i >= len(matrices):
                    break
                raw_pixels = (
                    scene.bgr if scene is not None else GrayFrame(1920, 1080).bgr
                )
                if gaze is not None:
                    color = (
                        COLOR_PALETTE[i % len(COLOR_PALETTE)]
                        if not (blink.start_time < gaze.time < blink.stop_time)
                        else (100, 100, 100)
                    )
                    cv2.circle(
                        raw_pixels,
                        (int(gaze.point[0]), int(gaze.point[1])),
                        40,
                        color,
                        8,
                    )
                cv2.putText(
                    raw_pixels,
                    wearer_names[i],
                    (50, 1150),
                    cv2.FONT_HERSHEY_DUPLEX,
                    1.5,
                    COLOR_PALETTE[i % len(COLOR_PALETTE)],
                    2,
                )

                wearer_writers[i].write_image(raw_pixels, dts)
                if capture_now:
                    target_name_sec = int(next_thumb_target_sec - THUMBNAILS_EVERY)
                    cv2.imwrite(
                        str(
                            wearer_folders[i]
                            / "thumbnails"
                            / f"thumb_{target_name_sec:02d}s.jpg"
                        ),
                        raw_pixels,
                    )
                if i == 4 and layout == "star":
                    pts = np.array(
                        [
                            [0, 0],
                            [scene.width, 0],
                            [scene.width, scene.height],
                            [0, scene.height],
                        ],
                        dtype=np.float32,
                    ).reshape(-1, 1, 2)
                    dst_pts = cv2.perspectiveTransform(
                        pts.reshape(-1, 1, 2), np.vstack([matrix, [0, 0, 1]])
                    )
                    cv2.polylines(canvas, [np.int32(dst_pts)], True, (0, 0, 0), 10)

                cv2.warpAffine(
                    raw_pixels,
                    matrix,
                    (canvas.shape[1], canvas.shape[0]),
                    dst=canvas,
                    borderMode=cv2.BORDER_TRANSPARENT,
                )

            plot_frame = plotter(canvas, plot_roi, multi_rec_data)
            mosaic_writer.write_image(canvas, dts)
            pupil_writer.write_image(plot_frame, dts)
            dts += 0.033
            if visualize:
                cv2.imshow("Mosaic", canvas)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    for i, writer in enumerate(wearer_writers):
        writer.close()
        generate_individual_contact_sheet(wearer_folders[i], wearer_names[i])
        generate_master_contact_sheet(output_root, wearer_folders, wearer_names)
    logging.info(f"Complete. Outputs in {output_root}")
    return True
