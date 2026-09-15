"""
Graphical interface for the detector.

A console window is an intimidating thing to put in front of someone who has
just been warned by SmartScreen about an unsigned download. This shows the same
work as a short progress list with a plain-language result. The console path
stays available behind --no-gui.

tkinter is used deliberately: it ships with Python, so the executable gains a
interface without gaining a dependency or several megabytes.
"""

import json
import queue
import threading
import urllib.error
import urllib.request
import webbrowser

STEPS = [
    "Reading system information",
    "Detecting graphics hardware",
    "Checking installed AI runtimes",
    "Sending results to the website",
]

# Matches the site header so the app and the page look related.
BG = "#0b2a5b"
PANEL = "#ffffff"
TEXT = "#0f172a"
MUTED = "#64748b"
ACCENT = "#2563eb"
OK = "#059669"
ERR = "#dc2626"

# Phrased for someone who does not know what an HTTP status code is.
HTTP_MESSAGES = {
    401: "This link is not valid any more. Please start a new scan on the website.",
    404: "That scan session no longer exists. Please start a new scan on the website.",
    409: "This scan was already completed. Start a new one on the website to scan again.",
    410: "This scan expired. Scans stay valid for 15 minutes, so please start a new one.",
    413: "The hardware report was unexpectedly large and was rejected.",
    429: "Too many attempts from this network. Please wait a minute and try again.",
}

# The session named in the filename is unusable and a fresh one should be
# started: it expired, was already completed, or has been deleted. Keeping the
# executable and running it a week later is the normal way to arrive here, so
# it is not an error worth showing anyone.
STALE_SESSION_CODES = (401, 404, 409, 410)


def create_session(server_url):
    """
    Start a scan the detector owns, for when it has no usable one.

    Returns (scan_id, upload_secret, read_token), or None if the site could not
    be reached. This is the same endpoint the website calls when someone presses
    the scan button, so it grants nothing the browser could not already ask for.
    """
    request = urllib.request.Request(
        f"{server_url}/api/scan",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("success"):
            return None
        return body["scanId"], body["uploadSecret"], body["readToken"]
    except Exception:  # noqa: BLE001 - the caller reports the original failure
        return None


def upload_profile(server_url, scan_id, upload_secret, profile, schema_version, detector_version):
    """
    POST the profile.

    Returns (ok, result_url_or_message, status_code), where the status code is
    None for anything that never reached the server.
    """
    payload = {
        "schemaVersion": schema_version,
        "detectorVersion": detector_version,
        "uploadSecret": upload_secret,
        "hardware": profile,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{server_url}/api/scan/{scan_id}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"CanMyPCRunAI-Detector/{detector_version}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status == 200:
                return True, f"{server_url}/results/{scan_id}", 200
            return False, f"Unexpected response from the website ({response.status}).", response.status
    except urllib.error.HTTPError as e:
        return False, HTTP_MESSAGES.get(e.code, f"The website rejected the upload ({e.code})."), e.code
    except urllib.error.URLError as e:
        return False, f"Could not reach {server_url}.\n\nCheck your internet connection.\n({e.reason})", None
    except Exception as e:  # noqa: BLE001 - any failure here is reported, never raised at the user
        return False, f"Something went wrong while sending the results.\n\n({e})", None


def run(scan_system, scan_id, upload_secret, server_url, schema_version, detector_version):
    """
    Scan and upload behind a progress window.

    Returns True on success, False on failure, or None when tkinter is
    unavailable so the caller can fall back to the console path.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return None

    events = queue.Queue()
    state = {"ok": False}

    root = tk.Tk()
    root.title("CanMyPCRunAI Detector")
    root.configure(bg=PANEL)
    root.resizable(False, False)

    width, height = 460, 410
    root.update_idletasks()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 3
    root.geometry(f"{width}x{height}+{x}+{y}")

    header = tk.Frame(root, bg=BG, height=88)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="CanMyPCRunAI", bg=BG, fg="white",
             font=("Segoe UI", 17, "bold")).pack(pady=(19, 0))
    tk.Label(header, text="Checking what AI models your PC can run",
             bg=BG, fg="#bcd4ee", font=("Segoe UI", 9)).pack()

    body = tk.Frame(root, bg=PANEL, padx=28, pady=20)
    body.pack(fill="both", expand=True)

    rows = []
    for label in STEPS:
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x", pady=3)
        bullet = tk.Label(row, text="○", bg=PANEL, fg=MUTED, font=("Segoe UI", 11))
        bullet.pack(side="left")
        name = tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                        font=("Segoe UI", 10), anchor="w")
        name.pack(side="left", padx=(8, 0))
        rows.append((bullet, name))

    bar = ttk.Progressbar(body, mode="determinate", maximum=len(STEPS))
    bar.pack(fill="x", pady=(16, 10))

    detail = tk.Label(body, text="Starting…", bg=PANEL, fg=MUTED,
                      font=("Segoe UI", 9), wraplength=390, justify="left", anchor="w")
    detail.pack(fill="x")

    footer = tk.Frame(root, bg=PANEL, padx=28, pady=14)
    footer.pack(fill="x")
    tk.Label(footer,
             text="Only hardware specifications are read. No personal files are touched.",
             bg=PANEL, fg=MUTED, font=("Segoe UI", 8), wraplength=390).pack()
    close_button = tk.Button(footer, text="Close", command=root.destroy, relief="flat",
                             bg=ACCENT, fg="white", font=("Segoe UI", 10, "bold"),
                             padx=22, pady=6, cursor="hand2",
                             activebackground="#1d4ed8", activeforeground="white",
                             borderwidth=0)

    def worker():
        """Detection and upload, off the UI thread so the window stays responsive."""
        try:
            events.put(("step", 0))
            profile = scan_system()

            events.put(("step", 1))
            gpus = profile.get("gpus") or []
            if gpus:
                gpu = gpus[0]
                vram = (gpu.get("dedicatedVramTotalBytes")
                        or gpu.get("vramTotalBytes") or 0) / (1024 ** 3)
                events.put(("detail",
                            f"{gpu.get('vendor', '')} {gpu.get('model', '')} — {vram:.1f} GB VRAM"))
            else:
                events.put(("detail", "No dedicated GPU found — CPU-only inference"))

            events.put(("step", 2))
            events.put(("step", 3))

            ok, result, code = False, None, None
            if scan_id and upload_secret:
                ok, result, code = upload_profile(server_url, scan_id, upload_secret, profile,
                                                  schema_version, detector_version)

            # Either this copy was never paired with a scan, or the scan it was
            # named after is gone. Running the same download again days later is
            # the ordinary way to get here, so start a fresh scan rather than
            # sending the user back to the website to fetch a new executable.
            if not ok and (code in STALE_SESSION_CODES or not scan_id):
                session = create_session(server_url)
                if session:
                    new_id, new_secret, read_token = session
                    ok, result, code = upload_profile(server_url, new_id, new_secret, profile,
                                                      schema_version, detector_version)
                    if ok:
                        # A browser that never saw this scan has no read token
                        # stored, so it travels in the link.
                        result = f"{server_url}/results/{new_id}?token={read_token}"
                elif result is None:
                    result = (f"Could not reach {server_url}.\n\n"
                              "Check your internet connection and try again.")

            events.put(("done", (ok, result, profile)))
        except Exception as e:  # noqa: BLE001
            events.put(("done", (False, f"Could not read your hardware.\n\n({e})", None)))

    def finish(ok, result, profile):
        state["ok"] = ok
        bar.pack_forget()
        if ok:
            for bullet, name in rows:
                bullet.config(text="✓", fg=OK)
                name.config(fg=TEXT)
            summary = ""
            if profile:
                ram = profile["memory"]["totalBytes"] / (1024 ** 3)
                summary = f"\n\n{profile['cpu']['model']}\n{ram:.0f} GB RAM"
            detail.config(text="Done. Your results are opening in your browser." + summary, fg=TEXT)
            try:
                webbrowser.open(result)
            except Exception:  # noqa: BLE001
                detail.config(text=f"Done. Open this address to see your results:\n{result}", fg=TEXT)
        else:
            detail.config(text=result, fg=ERR)
        close_button.pack()

    def pump():
        """Drain worker messages on the UI thread; tkinter is not thread-safe."""
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "step":
                    for i, (bullet, name) in enumerate(rows):
                        if i < value:
                            bullet.config(text="✓", fg=OK)
                            name.config(fg=TEXT)
                        elif i == value:
                            bullet.config(text="●", fg=ACCENT)
                            name.config(fg=TEXT)
                    bar["value"] = value
                    detail.config(text=STEPS[value] + "…", fg=MUTED)
                elif kind == "detail":
                    detail.config(text=value, fg=MUTED)
                elif kind == "done":
                    finish(*value)
                    return
        except queue.Empty:
            pass
        root.after(90, pump)

    threading.Thread(target=worker, daemon=True).start()
    root.after(120, pump)
    root.mainloop()
    return state["ok"]
