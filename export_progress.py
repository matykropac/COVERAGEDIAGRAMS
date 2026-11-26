"""Shared Streamlit export monitor; samples RSS at completed work boundaries."""
import time

def export_monitor(st, title):
    started = time.monotonic()
    bar = st.progress(0, text=title)
    detail = st.empty()
    try:
        import psutil
        process = psutil.Process()
        baseline = process.memory_info().rss
    except Exception:
        process = None
        baseline = 0
    peak = baseline
    def update(done, total, message):
        nonlocal peak
        elapsed = time.monotonic() - started
        fraction = min(1., max(0., done / max(total, 1)))
        bar.progress(fraction, text=message)
        eta = f"{elapsed * max(0, total-done)/done:.0f} s" if done else "—"
        ram = "RSS unavailable"
        if process is not None:
            try:
                rss = process.memory_info().rss
                peak = max(peak, rss)
                unit = 1024**2
                ram = f"RSS {rss/unit:.0f} MiB · sampled peak {peak/unit:.0f} MiB · delta {(rss-baseline)/unit:+.0f} MiB"
            except Exception:
                pass
        detail.caption(f"{done}/{total} · Elapsed {elapsed:.0f} s · ETA {eta} · {ram}")
    return update
