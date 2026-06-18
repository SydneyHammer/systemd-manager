#!/usr/bin/env python3
"""
systemd Service Manager — a GTK3 GUI
Supports system and user services: status, start/stop/restart, live journal logs.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

import subprocess
import threading
import os
import sys
import signal


# ── Colour tokens (dark terminal palette, fits XFCE dark themes) ──────────────
CSS = b"""
* { font-family: "Cantarell", "DejaVu Sans", sans-serif; }

.window-bg { background-color: #1c1e26; }

/* Sidebar */
.sidebar {
    background-color: #14151c;
    border-right: 1px solid #2e3040;
}
.sidebar-title {
    color: #a0a8c0;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 14px 14px 6px 14px;
}
.scope-btn {
    color: #6b7394;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    min-width: 70px;
}
.scope-btn:hover  { background-color: #2a2d3e; color: #c8d0f0; }
.scope-btn.active { background-color: #2e3a5c; color: #7eb8f7; font-weight: bold; }

/* Search */
.search-entry {
    background-color: #22253a;
    color: #c8d0f0;
    border: 1px solid #2e3040;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    caret-color: #7eb8f7;
}
.search-entry:focus { border-color: #7eb8f7; }

/* Service list */
.service-list { background-color: #1c1e26; }
.service-row {
    padding: 8px 14px;
    border-bottom: 1px solid #22253a;
}
.service-row:hover    { background-color: #22253a; }
.service-row:selected { background-color: #2e3a5c; }
.svc-name  { color: #c8d0f0; font-size: 12px; font-weight: bold; }
.svc-desc  { color: #6b7394; font-size: 11px; }

/* Status badges */
.badge {
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: bold;
}
.badge-active   { background-color: #1e4a2e; color: #5de085; }
.badge-inactive { background-color: #2e2a1e; color: #d4a840; }
.badge-failed   { background-color: #3e1e1e; color: #e05555; }
.badge-other    { background-color: #252535; color: #8890b0; }

/* Detail panel */
.detail-panel { background-color: #1c1e26; }
.detail-title { color: #c8d0f0; font-size: 15px; font-weight: bold; padding: 16px 18px 4px 18px; }
.detail-sub   { color: #6b7394; font-size: 11px; padding: 0 18px 10px 18px; }
.detail-sep   { color: #2e3040; }

/* Action buttons */
.action-btn {
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: bold;
    border: 1px solid transparent;
}
.btn-start   { background-color: #1a3d28; color: #5de085; border-color: #2a6040; }
.btn-start:hover { background-color: #214d32; }
.btn-stop    { background-color: #3d1a1a; color: #e05555; border-color: #602a2a; }
.btn-stop:hover  { background-color: #4d2121; }
.btn-restart { background-color: #1e2e4a; color: #7eb8f7; border-color: #2a4070; }
.btn-restart:hover { background-color: #253858; }
.btn-refresh { background-color: #252535; color: #a0a8c0; border-color: #3a3a50; }
.btn-refresh:hover { background-color: #2e2e40; }

/* Properties grid */
.prop-label { color: #6b7394; font-size: 11px; }
.prop-value { color: #c8d0f0; font-size: 11px; font-weight: bold; }

/* Log view */
.log-header { background-color: #14151c; border-top: 1px solid #2e3040; }
.log-label  { color: #a0a8c0; font-size: 10px; font-weight: bold; letter-spacing: 1px; padding: 8px 14px; }
.log-view   { background-color: #0e0f14; color: #9ab0d0; font-size: 11px; }
.log-toggle { background-color: transparent; color: #6b7394; border: 1px solid #2e3040; border-radius: 4px; padding: 3px 10px; font-size: 11px; }
.log-toggle:hover { color: #c8d0f0; border-color: #6b7394; }

/* Status bar */
.statusbar { background-color: #14151c; border-top: 1px solid #2e3040; }
.status-text { color: #6b7394; font-size: 10px; padding: 4px 12px; }
"""


def run_cmd(args, user=False):
    """Run a systemctl command. user=True adds --user flag."""
    cmd = ["systemctl"] + (["--user"] if user else []) + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def get_services(user=False):
    """Return list of (name, description, active_state, sub_state) tuples."""
    rc, out, err = run_cmd(
        ["list-units", "--type=service", "--all", "--no-pager",
         "--output=json", "--no-legend"],
        user=user
    )
    services = []
    if rc != 0 or not out:
        # Fallback: plain text parse
        rc2, out2, _ = run_cmd(
            ["list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
            user=user
        )
        for line in out2.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].endswith(".service"):
                name = parts[0].replace(".service", "")
                load   = parts[1]
                active = parts[2]
                sub    = parts[3]
                desc   = " ".join(parts[4:]) if len(parts) > 4 else ""
                services.append((name, desc, active, sub))
        return services

    import json
    try:
        units = json.loads(out)
        for u in units:
            name = u.get("unit", "").replace(".service", "")
            desc = u.get("description", "")
            active = u.get("active", "unknown")
            sub    = u.get("sub", "")
            services.append((name, desc, active, sub))
    except Exception:
        pass
    return services


def get_service_properties(name, user=False):
    """Return a dict of useful service properties."""
    rc, out, _ = run_cmd(
        ["show", name + ".service",
         "--property=ActiveState,SubState,LoadState,UnitFileState,"
         "MainPID,ExecMainStartTimestamp,FragmentPath,Description"],
        user=user
    )
    props = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props


class LogMonitor:
    """Runs journalctl -f in a thread and feeds lines to a GTK TextView."""

    def __init__(self, textview, name, user=False):
        self.textview = textview
        self.name     = name
        self.user     = user
        self._proc    = None
        self._thread  = None
        self._running = False

    def start(self):
        self.stop()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None

    def _run(self):
        cmd = ["journalctl", "-f", "-n", "200",
               "-u", self.name + ".service", "--no-pager", "--output=short-iso"]
        if self.user:
            cmd += ["--user"]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            for line in self._proc.stdout:
                if not self._running:
                    break
                line = line.rstrip("\n")
                GLib.idle_add(self._append_line, line)
        except Exception as e:
            GLib.idle_add(self._append_line, f"[error] {e}")

    def _append_line(self, line):
        buf = self.textview.get_buffer()
        end = buf.get_end_iter()
        buf.insert(end, line + "\n")
        # Auto-scroll
        adj = self.textview.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        # Keep buffer size manageable (last 2000 lines)
        line_count = buf.get_line_count()
        if line_count > 2000:
            start = buf.get_start_iter()
            cut   = buf.get_iter_at_line(line_count - 2000)
            buf.delete(start, cut)
        return False


class ServiceRow(Gtk.ListBoxRow):
    def __init__(self, name, desc, active, sub):
        super().__init__()
        self.svc_name = name
        self.active   = active
        self.sub      = sub

        self.get_style_context().add_class("service-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        self.add(box)

        # Badge
        badge_state = active.lower() if active else "other"
        badge = Gtk.Label(label=(sub or active or "?").upper())
        badge.get_style_context().add_class("badge")
        if badge_state == "active":
            badge.get_style_context().add_class("badge-active")
        elif badge_state == "failed":
            badge.get_style_context().add_class("badge-failed")
        elif badge_state == "inactive":
            badge.get_style_context().add_class("badge-inactive")
        else:
            badge.get_style_context().add_class("badge-other")
        badge.set_size_request(72, -1)
        badge.set_xalign(0.5)
        box.pack_start(badge, False, False, 0)

        # Name + description
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        lbl_name = Gtk.Label(label=name)
        lbl_name.get_style_context().add_class("svc-name")
        lbl_name.set_xalign(0)
        lbl_name.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.pack_start(lbl_name, False, False, 0)

        if desc:
            lbl_desc = Gtk.Label(label=desc)
            lbl_desc.get_style_context().add_class("svc-desc")
            lbl_desc.set_xalign(0)
            lbl_desc.set_ellipsize(Pango.EllipsizeMode.END)
            vbox.pack_start(lbl_desc, False, False, 0)

        box.pack_start(vbox, True, True, 0)
        self.show_all()


class SystemdManager(Gtk.Window):
    def __init__(self):
        super().__init__(title="systemd Manager")
        self.set_default_size(1100, 700)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", self._on_destroy)

        self._scope       = "system"   # "system" | "user"
        self._services    = []
        self._filter_text = ""
        self._selected    = None
        self._log_monitor = None
        self._log_visible = False

        self._apply_css()
        self._build_ui()
        self._load_services()

    # ── CSS ────────────────────────────────────────────────────────────────────
    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        self.get_style_context().add_class("window-bg")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        # Horizontal split: sidebar list | detail panel
        hpaned = Gtk.HPaned()
        hpaned.set_position(340)
        root.pack_start(hpaned, True, True, 0)

        hpaned.pack1(self._build_sidebar(), resize=False, shrink=False)
        hpaned.pack2(self._build_detail(), resize=True, shrink=True)

        # Status bar
        root.pack_start(self._build_statusbar(), False, False, 0)

    # ── Sidebar ────────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.get_style_context().add_class("sidebar")

        # Scope toggle
        scope_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        scope_box.set_margin_top(12)
        scope_box.set_margin_bottom(8)
        scope_box.set_margin_start(12)
        scope_box.set_margin_end(12)

        self._btn_system = Gtk.Button(label="System")
        self._btn_system.get_style_context().add_class("scope-btn")
        self._btn_system.get_style_context().add_class("active")
        self._btn_system.connect("clicked", self._on_scope, "system")

        self._btn_user = Gtk.Button(label="User")
        self._btn_user.get_style_context().add_class("scope-btn")
        self._btn_user.connect("clicked", self._on_scope, "user")

        scope_box.pack_start(self._btn_system, True, True, 0)
        scope_box.pack_start(self._btn_user, True, True, 0)
        sidebar.pack_start(scope_box, False, False, 0)

        # Search
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Filter services…")
        self._search.get_style_context().add_class("search-entry")
        self._search.set_margin_start(12)
        self._search.set_margin_end(12)
        self._search.set_margin_bottom(8)
        self._search.connect("search-changed", self._on_search)
        sidebar.pack_start(self._search, False, False, 0)

        # Count label
        self._count_lbl = Gtk.Label(label="")
        self._count_lbl.get_style_context().add_class("sidebar-title")
        self._count_lbl.set_xalign(0)
        sidebar.pack_start(self._count_lbl, False, False, 0)

        # Service list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._listbox = Gtk.ListBox()
        self._listbox.get_style_context().add_class("service-list")
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.set_filter_func(self._filter_func)
        self._listbox.connect("row-selected", self._on_row_selected)
        scroll.add(self._listbox)
        sidebar.pack_start(scroll, True, True, 0)

        return sidebar

    # ── Detail panel ───────────────────────────────────────────────────────────
    def _build_detail(self):
        self._detail_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._detail_root.get_style_context().add_class("detail-panel")

        # Placeholder when nothing selected
        self._placeholder = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER
        )
        ph_icon = Gtk.Label(label="⚙")
        ph_icon.set_markup('<span size="xx-large" foreground="#2e3040">⚙</span>')
        ph_label = Gtk.Label(label="Select a service")
        ph_label.get_style_context().add_class("prop-label")
        self._placeholder.pack_start(ph_icon, False, False, 4)
        self._placeholder.pack_start(ph_label, False, False, 4)
        self._detail_root.pack_start(self._placeholder, True, True, 0)

        # Detail content (shown when service is selected)
        self._detail_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._detail_content.set_no_show_all(True)
        self._detail_root.pack_start(self._detail_content, True, True, 0)

        self._build_detail_header()
        self._build_detail_actions()
        self._build_detail_props()
        self._build_log_panel()

        return self._detail_root

    def _build_detail_header(self):
        self._lbl_title = Gtk.Label(label="")
        self._lbl_title.get_style_context().add_class("detail-title")
        self._lbl_title.set_xalign(0)
        self._lbl_title.set_line_wrap(True)
        self._detail_content.pack_start(self._lbl_title, False, False, 0)

        self._lbl_sub = Gtk.Label(label="")
        self._lbl_sub.get_style_context().add_class("detail-sub")
        self._lbl_sub.set_xalign(0)
        self._lbl_sub.set_line_wrap(True)
        self._detail_content.pack_start(self._lbl_sub, False, False, 0)

        sep = Gtk.Separator()
        sep.get_style_context().add_class("detail-sep")
        self._detail_content.pack_start(sep, False, False, 0)

    def _build_detail_actions(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(12)
        bar.set_margin_bottom(12)
        bar.set_margin_start(18)
        bar.set_margin_end(18)

        def make_btn(label, cls, cb):
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("action-btn")
            b.get_style_context().add_class(cls)
            b.connect("clicked", cb)
            return b

        self._btn_start   = make_btn("▶  Start",   "btn-start",   self._on_start)
        self._btn_stop    = make_btn("■  Stop",    "btn-stop",    self._on_stop)
        self._btn_restart = make_btn("↺  Restart", "btn-restart", self._on_restart)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)

        self._btn_refresh_svc = make_btn("Refresh", "btn-refresh", self._on_refresh_svc)

        bar.pack_start(self._btn_start,   False, False, 0)
        bar.pack_start(self._btn_stop,    False, False, 0)
        bar.pack_start(self._btn_restart, False, False, 0)
        bar.pack_start(spacer,            True,  True,  0)
        bar.pack_start(self._btn_refresh_svc, False, False, 0)

        self._detail_content.pack_start(bar, False, False, 0)

        sep = Gtk.Separator()
        sep.get_style_context().add_class("detail-sep")
        self._detail_content.pack_start(sep, False, False, 0)

    def _build_detail_props(self):
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(6)
        grid.set_margin_top(12)
        grid.set_margin_bottom(12)
        grid.set_margin_start(18)
        grid.set_margin_end(18)

        self._prop_labels = {}
        fields = [
            ("Active State",  "ActiveState"),
            ("Sub State",     "SubState"),
            ("Load State",    "LoadState"),
            ("Unit File",     "UnitFileState"),
            ("Main PID",      "MainPID"),
            ("Started At",    "ExecMainStartTimestamp"),
            ("Unit File Path","FragmentPath"),
        ]
        for i, (human, key) in enumerate(fields):
            lbl = Gtk.Label(label=human + ":")
            lbl.get_style_context().add_class("prop-label")
            lbl.set_xalign(1)

            val = Gtk.Label(label="—")
            val.get_style_context().add_class("prop-value")
            val.set_xalign(0)
            val.set_selectable(True)
            val.set_ellipsize(Pango.EllipsizeMode.END)

            grid.attach(lbl, 0, i, 1, 1)
            grid.attach(val, 1, i, 1, 1)
            self._prop_labels[key] = val

        self._detail_content.pack_start(grid, False, False, 0)

        sep = Gtk.Separator()
        sep.get_style_context().add_class("detail-sep")
        self._detail_content.pack_start(sep, False, False, 0)

    def _build_log_panel(self):
        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        log_box.set_vexpand(True)

        # Log header row
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hdr.get_style_context().add_class("log-header")
        hdr.set_margin_start(14)
        hdr.set_margin_end(14)

        lbl = Gtk.Label(label="JOURNAL LOG")
        lbl.get_style_context().add_class("log-label")
        lbl.set_xalign(0)

        self._log_toggle_btn = Gtk.Button(label="▶  Live tail")
        self._log_toggle_btn.get_style_context().add_class("log-toggle")
        self._log_toggle_btn.set_margin_top(6)
        self._log_toggle_btn.set_margin_bottom(6)
        self._log_toggle_btn.connect("clicked", self._on_log_toggle)

        clear_btn = Gtk.Button(label="Clear")
        clear_btn.get_style_context().add_class("log-toggle")
        clear_btn.set_margin_top(6)
        clear_btn.set_margin_bottom(6)
        clear_btn.set_margin_start(6)
        clear_btn.connect("clicked", self._on_log_clear)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)

        hdr.pack_start(lbl, False, False, 0)
        hdr.pack_start(spacer, True, True, 0)
        hdr.pack_end(clear_btn, False, False, 0)
        hdr.pack_end(self._log_toggle_btn, False, False, 0)
        log_box.pack_start(hdr, False, False, 0)

        # Log text view
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_vexpand(True)
        self._log_scroll = log_scroll

        self._log_view = Gtk.TextView()
        self._log_view.set_editable(False)
        self._log_view.set_cursor_visible(False)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_view.get_style_context().add_class("log-view")

        # Monospace font for log
        font_desc = Pango.FontDescription("Monospace 10")
        self._log_view.override_font(font_desc)

        log_scroll.add(self._log_view)
        log_box.pack_start(log_scroll, True, True, 0)
        self._detail_content.pack_start(log_box, True, True, 0)

    def _build_statusbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.get_style_context().add_class("statusbar")
        self._status_lbl = Gtk.Label(label="Ready")
        self._status_lbl.get_style_context().add_class("status-text")
        self._status_lbl.set_xalign(0)
        bar.pack_start(self._status_lbl, True, True, 0)
        return bar

    # ── Data loading ───────────────────────────────────────────────────────────
    def _load_services(self):
        self._set_status("Loading services…")
        threading.Thread(target=self._load_thread, daemon=True).start()

    def _load_thread(self):
        user = (self._scope == "user")
        services = get_services(user=user)
        GLib.idle_add(self._populate_list, services)

    def _populate_list(self, services):
        # Clear existing rows
        for row in self._listbox.get_children():
            self._listbox.remove(row)

        self._services = services
        for name, desc, active, sub in sorted(services, key=lambda x: x[0]):
            row = ServiceRow(name, desc, active, sub)
            self._listbox.add(row)

        self._listbox.show_all()
        n = len(services)
        self._count_lbl.set_text(f"SERVICES  ({n})")
        self._set_status(f"Loaded {n} {self._scope} services")

    # ── Filtering ──────────────────────────────────────────────────────────────
    def _filter_func(self, row):
        if not self._filter_text:
            return True
        term = self._filter_text.lower()
        return term in row.svc_name.lower()

    def _on_search(self, entry):
        self._filter_text = entry.get_text()
        self._listbox.invalidate_filter()

    # ── Scope toggle ───────────────────────────────────────────────────────────
    def _on_scope(self, btn, scope):
        if scope == self._scope:
            return
        self._scope = scope
        # Update button styles
        for b, s in [(self._btn_system, "system"), (self._btn_user, "user")]:
            ctx = b.get_style_context()
            if s == scope:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")
        self._stop_log()
        self._hide_detail()
        self._load_services()

    # ── Service selection ──────────────────────────────────────────────────────
    def _on_row_selected(self, listbox, row):
        if row is None:
            self._hide_detail()
            return
        self._selected = row.svc_name
        self._stop_log()
        self._show_detail(row.svc_name)

    def _show_detail(self, name):
        user = (self._scope == "user")
        props = get_service_properties(name, user=user)

        self._lbl_title.set_text(name + ".service")
        self._lbl_sub.set_text(props.get("Description", ""))

        for key, lbl in self._prop_labels.items():
            v = props.get(key, "—")
            lbl.set_text(v if v else "—")

        # Clear old log
        self._log_view.get_buffer().set_text("")
        self._log_toggle_btn.set_label("▶  Live tail")
        self._log_visible = False

        self._placeholder.hide()
        self._detail_content.set_no_show_all(False)
        self._detail_content.show_all()
        self._set_status(f"Selected: {name}.service  [{props.get('ActiveState', '?')}]")

    def _hide_detail(self):
        self._selected = None
        self._detail_content.hide()
        self._placeholder.show()

    # ── Action buttons ─────────────────────────────────────────────────────────
    def _run_action(self, action):
        if not self._selected:
            return
        user = (self._scope == "user")
        self._set_status(f"Running {action} on {self._selected}…")

        def do():
            rc, out, err = run_cmd([action, self._selected + ".service"], user=user)
            msg = f"{action} {self._selected}: {'OK' if rc == 0 else 'Error — ' + err}"
            GLib.idle_add(self._set_status, msg)
            GLib.idle_add(self._refresh_current_row)

        threading.Thread(target=do, daemon=True).start()

    def _on_start(self, _):   self._run_action("start")
    def _on_stop(self, _):    self._run_action("stop")
    def _on_restart(self, _): self._run_action("restart")

    def _on_refresh_svc(self, _):
        if self._selected:
            self._show_detail(self._selected)

    def _refresh_current_row(self):
        """Reload the selected service's status badge."""
        if not self._selected:
            return
        user = (self._scope == "user")
        props = get_service_properties(self._selected, user=user)
        active = props.get("ActiveState", "unknown")
        sub    = props.get("SubState", "")
        # Update in list
        for row in self._listbox.get_children():
            if isinstance(row, ServiceRow) and row.svc_name == self._selected:
                row.active = active
                row.sub    = sub
                # Re-render row badge
                for child in row.get_children():
                    row.remove(child)
                new_row = ServiceRow(row.svc_name, "", active, sub)
                for child in new_row.get_children():
                    new_row.remove(child)
                    row.add(child)
                row.show_all()
                break
        # Refresh detail props
        self._show_detail(self._selected)

    # ── Live log ───────────────────────────────────────────────────────────────
    def _on_log_toggle(self, _):
        if self._log_monitor and self._log_visible:
            self._stop_log()
        else:
            self._start_log()

    def _start_log(self):
        if not self._selected:
            return
        user = (self._scope == "user")
        self._log_view.get_buffer().set_text("")
        self._log_monitor = LogMonitor(self._log_view, self._selected, user=user)
        self._log_monitor.start()
        self._log_visible = True
        self._log_toggle_btn.set_label("■  Stop tail")
        self._set_status(f"Live log: {self._selected}.service")

    def _stop_log(self):
        if self._log_monitor:
            self._log_monitor.stop()
            self._log_monitor = None
        self._log_visible = False
        self._log_toggle_btn.set_label("▶  Live tail")

    def _on_log_clear(self, _):
        self._log_view.get_buffer().set_text("")

    # ── Status bar ─────────────────────────────────────────────────────────────
    def _set_status(self, msg):
        self._status_lbl.set_text(msg)

    # ── Cleanup ────────────────────────────────────────────────────────────────
    def _on_destroy(self, _):
        self._stop_log()
        Gtk.main_quit()


def main():
    # Allow Ctrl-C in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    win = SystemdManager()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
