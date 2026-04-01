#!/usr/bin/env python3
"""
GTFS time–space (string) diagram dashboard.

Reads a GTFS folder (default: ./GTFS/BART), builds cumulative distance along each trip
from shape_dist_traveled when present, otherwise from stop coordinates, and plots
each trip as a trajectory: time on X, distance (km) on Y, with dwell as horizontal
segments (same distance, time advances) and running as diagonals between stops.

Run:  streamlit run gtfs2gmns_dashboard.py

Requires: streamlit, plotly, pandas (stdlib only for GitHub HTTP).

GitHub: public repo. Paste either a **raw** base URL or a normal repo folder link, e.g.
``https://github.com/OWNER/REPO/tree/main/GTFS/BART`` — it is converted automatically.
"""
from __future__ import annotations

import io
import math
import re
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Time and geometry helpers
# ---------------------------------------------------------------------------


def time_to_minutes(t) -> float:
    """GTFS H:MM:SS or HH:MM:SS to minutes from midnight (supports hours > 24)."""
    if pd.isna(t) or t == "":
        return float("nan")
    s = str(t).strip().strip('"')
    parts = s.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    sec = float(parts[2]) if len(parts) > 2 else 0.0
    return h * 60 + m + sec / 60.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def minutes_axis_label(m: float) -> str:
    if not math.isfinite(m):
        return ""
    total = int(round(m * 60))
    hh = (total // 3600) % 48
    mm = (total % 3600) // 60
    return f"{hh:02d}:{mm:02d}"


# ---------------------------------------------------------------------------
# GTFS loading
# ---------------------------------------------------------------------------

GTFS_TXT = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")


def _coerce_gtfs_types(
    stops: pd.DataFrame, routes: pd.DataFrame, trips: pd.DataFrame, stop_times: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for col in ("stop_lat", "stop_lon"):
        if col in stops.columns:
            stops[col] = pd.to_numeric(stops[col], errors="coerce")

    if "shape_dist_traveled" in stop_times.columns:
        stop_times["shape_dist_traveled"] = pd.to_numeric(
            stop_times["shape_dist_traveled"], errors="coerce"
        )
    if "stop_sequence" in stop_times.columns:
        stop_times["stop_sequence"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")

    return stops, routes, trips, stop_times


@st.cache_data(show_spinner="Loading GTFS…")
def load_gtfs_local(gtfs_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    p = Path(gtfs_dir)
    stops = pd.read_csv(p / "stops.txt", dtype=str, low_memory=False)
    routes = pd.read_csv(p / "routes.txt", dtype=str, low_memory=False)
    trips = pd.read_csv(p / "trips.txt", dtype=str, low_memory=False)
    stop_times = pd.read_csv(p / "stop_times.txt", dtype=str, low_memory=False)
    return _coerce_gtfs_types(stops, routes, trips, stop_times)


def _normalize_github_raw_base(url: str) -> str:
    u = url.strip().split("?", 1)[0].rstrip("/")
    # https://github.com/owner/repo/tree/branch/path/to/folder
    tree_m = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$",
        u,
        re.I,
    )
    if tree_m:
        owner, repo, branch, path = tree_m.groups()
        path = path.strip("/")
        u = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    elif "raw.githubusercontent.com" not in u and "github.com" in u and "/blob/" in u:
        u = u.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return u.rstrip("/") + "/"


@st.cache_data(show_spinner="Loading GTFS from GitHub…")
def load_gtfs_github_raw(raw_base_url: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = _normalize_github_raw_base(raw_base_url)
    stops = routes = trips = stop_times = None
    try:
        for name in GTFS_TXT:
            req = urllib.request.Request(
                base + name,
                headers={"User-Agent": "gtfs2gmns-dashboard/1.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8-sig")
            df = pd.read_csv(io.StringIO(body), dtype=str, low_memory=False)
            if name == "stops.txt":
                stops = df
            elif name == "routes.txt":
                routes = df
            elif name == "trips.txt":
                trips = df
            else:
                stop_times = df
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"HTTP {e.code} while fetching GTFS from GitHub. "
            f"Use a **raw** URL like https://raw.githubusercontent.com/OWNER/REPO/BRANCH/path/to/GTFS/ "
            f"(public repo). Failed URL may be: {base}{GTFS_TXT[0]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach GitHub: {e}") from e

    assert stops is not None and routes is not None and trips is not None and stop_times is not None
    return _coerce_gtfs_types(stops, routes, trips, stop_times)


def build_stop_times_enriched(
    stops: pd.DataFrame,
    routes: pd.DataFrame,
    trips: pd.DataFrame,
    stop_times: pd.DataFrame,
) -> pd.DataFrame:
    st_df = stop_times.merge(trips, on="trip_id", how="left", suffixes=("", "_trip"))
    st_df = st_df.merge(routes, on="route_id", how="left", suffixes=("", "_route"))
    st_df = st_df.merge(
        stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
        on="stop_id",
        how="left",
    )

    st_df["dir"] = st_df["direction_id"].fillna("0").astype(str)
    st_df["shape_key"] = st_df.get("shape_id", pd.Series("", index=st_df.index)).fillna("")

    st_df["arr_min"] = st_df["arrival_time"].map(time_to_minutes)
    st_df["dep_min"] = st_df["departure_time"].map(time_to_minutes)
    st_df = st_df.dropna(subset=["arr_min", "dep_min", "stop_sequence"])
    st_df = st_df.sort_values(["trip_id", "stop_sequence"])

    # Cumulative distance (km) per trip
    def dist_km_per_trip(g: pd.DataFrame) -> pd.Series:
        g = g.sort_values("stop_sequence")
        idx = g.index
        if "shape_dist_traveled" in g.columns and g["shape_dist_traveled"].notna().any():
            d_m = g["shape_dist_traveled"].ffill().bfill()
            if d_m.notna().all() and bool((d_m >= 0).all()):
                return pd.Series(d_m.to_numpy(dtype=float) / 1000.0, index=idx)

        lat = g["stop_lat"].to_numpy(dtype=float)
        lon = g["stop_lon"].to_numpy(dtype=float)
        cum = [0.0]
        for i in range(1, len(g)):
            if math.isfinite(lat[i - 1]) and math.isfinite(lat[i]):
                cum.append(
                    cum[-1] + haversine_m(lat[i - 1], lon[i - 1], lat[i], lon[i]) / 1000.0
                )
            else:
                cum.append(cum[-1])
        return pd.Series(cum, index=idx)

    st_df = st_df.sort_values(["trip_id", "stop_sequence"])
    st_df["dist_km"] = st_df.groupby("trip_id", group_keys=False).apply(dist_km_per_trip)

    return st_df


def corridor_options(enriched: pd.DataFrame) -> list[tuple[str, str, str, str]]:
    """(value_key, label) pairs for selectbox."""
    rows = []
    for (rid, direction_id, shape_key), g in enriched.groupby(
        ["route_id", "dir", "shape_key"], dropna=False
    ):
        rname = g["route_short_name"].iloc[0] if "route_short_name" in g.columns else rid
        longn = g["route_long_name"].iloc[0] if "route_long_name" in g.columns else ""
        head = g["trip_headsign"].dropna().astype(str).mode()
        head = head.iloc[0] if len(head) else ""
        n_trips = g["trip_id"].nunique()
        label = f"{rname} dir {direction_id} — {n_trips} trips"
        if head:
            label += f" ({head[:40]}{'…' if len(head) > 40 else ''})"
        key = f"{rid}|{direction_id}|{shape_key}"
        rows.append((key, label, rid, str(direction_id)))
    rows.sort(key=lambda x: x[1])
    return rows


def parse_corridor_key(key: str) -> tuple[str, str, str]:
    parts = key.split("|", 2)
    return parts[0], parts[1], parts[2] if len(parts) > 2 else ""


def trip_polyline_time_x_space_y(g: pd.DataFrame) -> tuple[list[float], list[float]]:
    """Piecewise polyline for X=time (min), Y=distance (km): dwell is horizontal, run is diagonal."""
    g = g.sort_values("stop_sequence")
    ts: list[float] = []
    ds: list[float] = []
    for _, row in g.iterrows():
        d = float(row["dist_km"])
        ta = float(row["arr_min"])
        td = float(row["dep_min"])
        if not ts:
            ts.append(ta)
            ds.append(d)
        else:
            if abs(ts[-1] - ta) > 1e-6 or abs(ds[-1] - d) > 1e-9:
                ts.append(ta)
                ds.append(d)
        if abs(td - ta) > 1e-6:
            ts.append(td)
            ds.append(d)
    return ts, ds


def build_figure(
    trip_groups: list[tuple[str, pd.DataFrame]],
    route_color_hex: str | None,
    playback_min: float | None,
    time_lo: float,
    time_hi: float,
) -> go.Figure:
    fig = go.Figure()
    palette = [
        "#FF6B6B",
        "#FFA94D",
        "#69DB7C",
        "#4DABF7",
        "#9775FA",
        "#F783AC",
        "#FFD43B",
        "#38D9A9",
    ]
    dist_max = 0.0
    for i, (trip_id, g) in enumerate(trip_groups):
        ts, ds = trip_polyline_time_x_space_y(g)
        if len(ts) < 2:
            continue
        dist_max = max(dist_max, max(ds))
        if route_color_hex and len(route_color_hex) == 6:
            color = "#" + route_color_hex
        else:
            color = palette[i % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=ts,
                y=ds,
                mode="lines",
                name=str(trip_id),
                line=dict(width=2, color=color),
                hovertemplate=(
                    "trip %{text}<br>"
                    "time %{customdata}<br>"
                    "distance %{y:.2f} km<extra></extra>"
                ),
                text=[str(trip_id)] * len(ts),
                customdata=[minutes_axis_label(t) for t in ts],
            )
        )

    shapes = []
    if playback_min is not None and math.isfinite(playback_min):
        shapes.append(
            dict(
                type="line",
                xref="x",
                yref="paper",
                x0=playback_min,
                x1=playback_min,
                y0=0,
                y1=1,
                line=dict(color="rgba(77,171,247,0.9)", width=2, dash="dash"),
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#161b22",
        font=dict(color="#e6edf3"),
        margin=dict(l=60, r=20, t=40, b=60),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(0,0,0,0.3)",
        ),
        xaxis_title="Time of day",
        yaxis_title="Distance along line (km)",
        shapes=shapes,
        hovermode="closest",
        height=700,
    )
    fig.update_xaxes(
        range=[time_lo, time_hi],
        tickmode="linear",
        dtick=30,
        showgrid=True,
        gridcolor="rgba(255,255,255,0.08)",
    )
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
    if dist_max > 0:
        fig.update_yaxes(range=[0, dist_max * 1.05])

    tick_vals = list(range(int(time_lo // 30) * 30, int(time_hi) + 1, 30))
    fig.update_xaxes(
        tickvals=tick_vals,
        ticktext=[minutes_axis_label(v) for v in tick_vals],
    )

    return fig


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(page_title="GTFS Time–Space Viewer", layout="wide")
    st.title("GTFS Time–Space Diagram")
    st.caption(
        "X: time of day. Y: cumulative distance along the line (km). "
        "Horizontal segments: dwell at stops. Diagonals: running between stops."
    )

    default_path = Path(__file__).resolve().parent / "GTFS" / "BART"
    with st.sidebar:
        source = st.radio(
            "GTFS source",
            ("Local folder", "GitHub (raw)"),
            help="GitHub: public repo only, via raw.githubusercontent.com",
        )
        gtfs_path = ""
        raw_base = ""
        if source == "Local folder":
            gtfs_path = st.text_input("GTFS directory", value=str(default_path))
        else:
            st.caption("Public repo: files `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt` under this path.")
            gh_owner = st.text_input("GitHub owner", value="itsfangtang")
            gh_repo = st.text_input("GitHub repo", value="gtfs2gmns")
            gh_branch = st.text_input("Branch", value="main")
            gh_path = st.text_input("Path to GTFS folder in repo", value="GTFS/BART")
            raw_paste = st.text_input(
                "Or paste repo folder or raw URL (overrides fields above if non-empty)",
                placeholder="https://github.com/itsfangtang/gtfs2gmns/tree/main/GTFS/BART",
            )
            if raw_paste.strip():
                raw_base = raw_paste.strip()
            elif gh_owner.strip() and gh_repo.strip():
                p = gh_path.strip().strip("/")
                raw_base = (
                    f"https://raw.githubusercontent.com/{gh_owner.strip()}/{gh_repo.strip()}/"
                    f"{gh_branch.strip()}/{p}/"
                )
            if raw_base:
                st.caption(f"Loading from: `{raw_base}`")

        t_start = st.time_input("Window start", value=pd.Timestamp("07:00:00").time())
        t_end = st.time_input("Window end", value=pd.Timestamp("10:00:00").time())
        max_trips = st.slider("Max trips to plot", 5, 120, 40)
        show_playback = st.checkbox("Show playback time guide line", value=True)

    if source == "Local folder":
        path = Path(gtfs_path)
        if not (path / "stop_times.txt").exists():
            st.error(f"GTFS file not found: {path / 'stop_times.txt'}")
            return
        try:
            stops, routes, trips, stop_times = load_gtfs_local(str(path))
        except Exception as e:
            st.error(f"Failed to load GTFS: {e}")
            return
    else:
        if not raw_base.strip():
            st.error("Set GitHub owner + repo, or paste a raw base URL.")
            return
        try:
            stops, routes, trips, stop_times = load_gtfs_github_raw(raw_base)
        except RuntimeError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Failed to load GTFS from GitHub: {e}")
            return
    enriched = build_stop_times_enriched(stops, routes, trips, stop_times)

    win_lo = t_start.hour * 60 + t_start.minute + t_start.second / 60.0
    win_hi = t_end.hour * 60 + t_end.minute + t_end.second / 60.0
    if win_hi <= win_lo:
        win_hi += 24 * 60

    # Trips that intersect the window (by first departure / last arrival)
    trip_first = enriched.groupby("trip_id")["dep_min"].min()
    trip_last = enriched.groupby("trip_id")["arr_min"].max()
    trip_ok = trip_first.index[
        (trip_first <= win_hi) & (trip_last >= win_lo)
    ]
    filtered = enriched[enriched["trip_id"].isin(trip_ok)]

    opts = corridor_options(filtered)
    if not opts:
        st.warning("No trips overlap the selected time window.")
        return

    labels = [o[1] for o in opts]
    keys = [o[0] for o in opts]
    choice = st.selectbox("Route / corridor", range(len(labels)), format_func=lambda i: labels[i])
    rid, direction_id, shape_key = parse_corridor_key(keys[choice])

    corridor_df = filtered[
        (filtered["route_id"] == rid)
        & (filtered["dir"] == direction_id)
        & (filtered["shape_key"] == shape_key)
    ]
    trip_ids = corridor_df["trip_id"].unique().tolist()[:max_trips]
    corridor_df = corridor_df[corridor_df["trip_id"].isin(trip_ids)]

    route_row = routes[routes["route_id"] == rid]
    rc = None
    if not route_row.empty and "route_color" in route_row.columns:
        rc = str(route_row["route_color"].iloc[0]).strip()
        if not rc or rc.lower() == "nan":
            rc = None

    trip_groups = [(tid, corridor_df[corridor_df["trip_id"] == tid]) for tid in trip_ids]

    y0 = win_lo
    y1 = win_hi
    playback = None
    if show_playback:
        playback = st.slider(
            "Playback time (blue vertical guide; value = minutes from midnight)",
            min_value=float(win_lo),
            max_value=float(win_hi),
            value=float(win_lo + (win_hi - win_lo) * 0.35),
            step=1.0,
        )
        st.caption(f"**Clock time:** {minutes_axis_label(playback)}")

    fig = build_figure(trip_groups, rc, playback, y0, y1)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Trips in selected corridor"):
        st.dataframe(
            corridor_df.groupby("trip_id")
            .agg(first_dep=("dep_min", "min"), last_arr=("arr_min", "max"), stops=("stop_id", "count"))
            .reset_index(),
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
