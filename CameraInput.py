# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""Camera input GUI.

Add, edit and delete cameras in cameras.json and manage their thumbnails in
assets/. Run with:

    uv run CameraInput.py
"""

from __future__ import annotations

import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "cameras.json"
ASSETS_DIR = ROOT / "assets"
THUMB_SIZE = (256, 256)

TYPES = ["Mirrorless", "DSLR", "Compact"]
SENSORS = ["Medium Format", "Full Frame", "APS-C", "Micro Four Thirds", "1.4-inch", "1-inch", "Smaller"]
CURRENCIES = ["GBP", "USD", "EUR"]

# (key, label, kind) — kind: str | int | float | bool | choice:<list>
FIELDS: list[tuple[str, str, object]] = [
    ("brand", "Brand *", str),
    ("model", "Model *", str),
    ("type", "Type", TYPES),
    ("price", "Price *", float),
    ("currency", "Currency", CURRENCIES),
    ("release_year", "Release year", int),
    ("sensor", "Sensor", SENSORS),
    ("megapixels", "Megapixels", float),
    ("mount", "Mount / lens", str),
    ("ibis", "IBIS", bool),
    ("max_video", "Max video", str),
    ("iso_max", "Max ISO", int),
    ("weight_g", "Weight (g)", float),
    ("burst_fps", "Burst (fps)", float),
    ("viewfinder", "Viewfinder", str),
    ("link", "Link", str),
]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "camera"


def load_cameras() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open(encoding="utf-8") as f:
        return json.load(f).get("cameras", [])


def save_cameras(cameras: list[dict]) -> None:
    cameras.sort(key=lambda c: (c.get("brand", "").lower(), c.get("model", "").lower()))
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump({"cameras": cameras}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def make_thumbnail(src: Path, dest: Path) -> None:
    with Image.open(src) as img:
        img = img.convert("RGBA")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG", optimize=True)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Camera Input")
        self.geometry("900x640")
        self.minsize(760, 560)

        self.cameras = load_cameras()
        self.current_id: str | None = None  # id of camera being edited, None = new
        self.new_image: Path | None = None  # image picked but not yet saved
        self.image_removed = False  # user cleared the existing image
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.vars: dict[str, tk.Variable] = {}

        self._build()
        self.refresh_list()
        self.new_camera()

    # ---------- layout ----------
    def _build(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)

        # Left: list of cameras
        left = ttk.Frame(paned)
        ttk.Label(left, text="CAMERAS").pack(anchor="w")
        self.listbox = tk.Listbox(left, activestyle="none", exportselection=False, width=32)
        self.listbox.pack(fill="both", expand=True, pady=(4, 4))
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        ttk.Button(left, text="New camera", command=self.new_camera).pack(fill="x")
        paned.add(left, weight=1)

        # Right: form
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        form = ttk.Frame(right)
        form.grid(row=0, column=0, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        for i, (key, label, kind) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            if kind is bool:
                var: tk.Variable = tk.BooleanVar()
                widget = ttk.Checkbutton(form, variable=var)
            elif isinstance(kind, list):
                var = tk.StringVar()
                widget = ttk.Combobox(form, textvariable=var, values=kind)
            else:
                var = tk.StringVar()
                widget = ttk.Entry(form, textvariable=var)
            widget.grid(row=i, column=1, sticky="ew", pady=2)
            self.vars[key] = var
        form.columnconfigure(1, weight=1)

        n = len(FIELDS)
        ttk.Label(form, text="Notes").grid(row=n, column=0, sticky="nw", pady=2)
        self.notes = tk.Text(form, height=4, wrap="word")
        self.notes.grid(row=n, column=1, sticky="ew", pady=2)

        # Image preview column
        img_col = ttk.Frame(right)
        img_col.grid(row=0, column=1, sticky="n", padx=(12, 0))
        self.preview = tk.Label(img_col, text="No image", width=24, height=12, relief="solid", bd=1, bg="#f4f1ea")
        self.preview.pack()
        ttk.Button(img_col, text="Choose image…", command=self.choose_image).pack(fill="x", pady=(6, 0))
        ttk.Button(img_col, text="Remove image", command=self.remove_image).pack(fill="x", pady=(4, 0))

        # Actions
        actions = ttk.Frame(right)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Save", command=self.save).pack(side="left")
        ttk.Button(actions, text="Delete", command=self.delete).pack(side="left", padx=6)
        self.status = ttk.Label(actions, text="")
        self.status.pack(side="left", padx=12)

        self.bind("<Control-s>", lambda e: self.save())

    # ---------- list ----------
    def refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        for c in self.cameras:
            price = c.get("price")
            price_s = f"  {c.get('currency', '')} {price:,.0f}" if isinstance(price, (int, float)) else ""
            self.listbox.insert("end", f"{c.get('brand', '')} {c.get('model', '')}{price_s}")

    def on_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if sel:
            self.load_into_form(self.cameras[sel[0]])

    # ---------- form ----------
    def new_camera(self) -> None:
        self.listbox.selection_clear(0, "end")
        self.load_into_form({"currency": "GBP", "type": "Mirrorless"})
        self.current_id = None

    def load_into_form(self, cam: dict) -> None:
        self.current_id = cam.get("id")
        self.new_image = None
        self.image_removed = False
        for key, _label, kind in FIELDS:
            val = cam.get(key)
            if kind is bool:
                self.vars[key].set(bool(val))
            else:
                if isinstance(val, float) and val.is_integer():
                    val = int(val)
                self.vars[key].set("" if val is None else str(val))
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", cam.get("notes", ""))
        image = cam.get("image")
        self.show_preview(ROOT / image if image else None)
        self.status.config(text="Editing" if self.current_id else "New camera")

    def show_preview(self, path: Path | None) -> None:
        if path and path.exists():
            with Image.open(path) as img:
                img = img.copy()
            img.thumbnail((180, 180))
            self.preview_ref = ImageTk.PhotoImage(img)
            self.preview.config(image=self.preview_ref, text="", width=180, height=180)
        else:
            self.preview_ref = None
            self.preview.config(image="", text="No image", width=24, height=12)

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose camera image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"), ("All files", "*.*")],
        )
        if path:
            self.new_image = Path(path)
            self.image_removed = False
            self.show_preview(self.new_image)

    def remove_image(self) -> None:
        self.new_image = None
        self.image_removed = True
        self.show_preview(None)

    def read_form(self) -> dict | None:
        cam: dict = {}
        for key, label, kind in FIELDS:
            raw = self.vars[key].get()
            if kind is bool:
                cam[key] = bool(raw)
                continue
            raw = str(raw).strip()
            if not raw:
                continue
            if kind in (int, float):
                try:
                    num = float(raw.replace(",", ""))
                except ValueError:
                    messagebox.showerror("Invalid value", f"{label.rstrip(' *')} must be a number.")
                    return None
                cam[key] = int(num) if kind is int or num.is_integer() else num
            else:
                cam[key] = raw
        for req in ("brand", "model", "price"):
            if req not in cam:
                messagebox.showerror("Missing value", f"{req.capitalize()} is required.")
                return None
        notes = self.notes.get("1.0", "end").strip()
        if notes:
            cam["notes"] = notes
        return cam

    # ---------- actions ----------
    def save(self) -> None:
        cam = self.read_form()
        if cam is None:
            return
        new_id = slugify(f"{cam['brand']} {cam['model']}")
        old = next((c for c in self.cameras if c.get("id") == self.current_id), None)

        clash = next((c for c in self.cameras if c.get("id") == new_id and c is not old), None)
        if clash and not messagebox.askyesno("Overwrite?", f"'{new_id}' already exists. Overwrite it?"):
            return

        cam["id"] = new_id
        dest = ASSETS_DIR / f"{new_id}.png"
        old_image = ROOT / old["image"] if old and old.get("image") else None

        try:
            if self.new_image:
                make_thumbnail(self.new_image, dest)
                cam["image"] = f"assets/{dest.name}"
                if old_image and old_image != dest and old_image.exists():
                    old_image.unlink()
            elif old_image and not self.image_removed:
                if old_image != dest and old_image.exists():
                    old_image.replace(dest)  # camera renamed — move thumbnail
                cam["image"] = f"assets/{dest.name}"
            elif old_image and self.image_removed and old_image.exists():
                old_image.unlink()
        except Exception as exc:  # noqa: BLE001 — surface any image error to the user
            messagebox.showerror("Image error", str(exc))
            return

        self.cameras = [c for c in self.cameras if c is not old and c is not clash]
        self.cameras.append(cam)
        save_cameras(self.cameras)
        self.refresh_list()

        idx = next(i for i, c in enumerate(self.cameras) if c["id"] == new_id)
        self.listbox.selection_set(idx)
        self.listbox.see(idx)
        self.load_into_form(cam)
        self.status.config(text=f"Saved {cam['brand']} {cam['model']}")

    def delete(self) -> None:
        cam = next((c for c in self.cameras if c.get("id") == self.current_id), None)
        if not cam:
            return
        if not messagebox.askyesno("Delete", f"Delete {cam['brand']} {cam['model']}?"):
            return
        if cam.get("image"):
            (ROOT / cam["image"]).unlink(missing_ok=True)
        self.cameras.remove(cam)
        save_cameras(self.cameras)
        self.refresh_list()
        self.new_camera()
        self.status.config(text="Deleted")


if __name__ == "__main__":
    App().mainloop()
