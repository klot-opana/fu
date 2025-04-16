import os
import json
import base64
import time
import requests
import re
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, Menu, messagebox, PhotoImage, filedialog
import ctypes
import platform
import threading
from PIL import Image, ImageTk
from io import BytesIO
from collections import deque

# Константы
CONFIG_FILE = "config.json"
HISTORY_FILE = "prompt_history.json"
API_URL = "https://api-key.fusionbrain.ai/"
DEFAULT_SIZE = 1024
OUTPUT_FOLDER = "Generated_Images"
MAX_FOLDER_NAME_LENGTH = 50
THUMBNAIL_SIZE = (100, 100)
MAX_THUMBNAILS = 5
MAX_REPEATS = 1000
MAX_HISTORY = 20
TIME_ESTIMATE_PER_STEP = 5

SIZE_OPTIONS = [

    ("128x128", 128),
    ("256x256", 256),
    ("512x512", 512),
    ("768x768", 768),
    ("1024x1024", 1024),
    ("1280x1280", 1280),
    ("1536x1536", 1536),
    
    ("Custom", "custom")
]

class SmartTextWidget(scrolledtext.ScrolledText):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bind("<Control-v>", self.smart_paste)
        self.bind("<Control-V>", self.smart_paste)
        self.bind("<<Paste>>", self.smart_paste)
        
    def smart_paste(self, event=None):
        try:
            text = self.clipboard_get()
            if self.tag_ranges("sel"):
                self.delete("sel.first", "sel.last")
            self.insert("insert", text)
            return "break"
        except tk.TclError:
            return "break"

class ImageGenerator:
    def __init__(self, root):
        self.root = root
        self.root.title("FusionBrain Image Generator")
        self.root.geometry("1100x900")
        
        if platform.system() == 'Windows':
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        
        # Инициализация переменных
        self.api_key = ""
        self.secret_key = ""
        self.is_generating = False
        self.should_stop = False
        self.selected_size = DEFAULT_SIZE
        self.custom_size = None
        self.save_original_size = tk.BooleanVar(value=True)
        self.repeat_generation = tk.BooleanVar(value=False)
        self.repeat_count = tk.IntVar(value=1)
        self.last_generated_images = []
        self.current_repeat = 0
        self.prompt_history = deque(maxlen=MAX_HISTORY)
        self.start_time = None
        self.estimated_time = 0
        self.progress_steps = 0
        
        # Сначала создаем интерфейс
        self.create_ui()
        
        # Затем загружаем конфиг и историю
        self.load_config()
        self.load_prompt_history()
        
        # Обновляем меню после загрузки истории
        self.update_history_menu()
        
        self.setup_hotkeys()

    def setup_hotkeys(self):
        self.root.bind('<Key>', self.check_hotkeys)
        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Копировать (Ctrl+C)", command=self.copy_text)
        self.context_menu.add_command(label="Вставить (Ctrl+V)", command=self.paste_text)
        self.context_menu.add_command(label="Вырезать (Ctrl+X)", command=self.cut_text)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Выделить все (Ctrl+A)", command=self.select_all)

    def load_prompt_history(self):
        """Загрузка истории промптов из файла"""
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    # Очищаем текущую историю перед загрузкой
                    self.prompt_history.clear()
                    # Загружаем историю из файла
                    self.prompt_history.extend(history)
                    self.log_message(f"Загружено {len(history)} промптов из истории")
        except Exception as e:
            self.log_message(f"Ошибка загрузки истории: {str(e)}", "error")

    def save_prompt_history(self):
        """Сохранение истории промптов в файл"""
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(self.prompt_history), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_message(f"Ошибка сохранения истории: {str(e)}", "error")

    def clear_prompt_history(self):
        """Очистка истории промптов"""
        self.prompt_history.clear()
        self.update_history_menu()
        try:
            if os.path.exists(HISTORY_FILE):
                os.remove(HISTORY_FILE)
            self.log_message("История промптов очищена")
        except Exception as e:
            self.log_message(f"Ошибка очистки истории: {str(e)}", "error")

    def update_history_menu(self):
        """Обновление меню истории с актуальными промптами"""
        if hasattr(self, 'history_menu'):
            self.history_menu.delete(0, tk.END)
            
            # Добавляем команду очистки истории
            self.history_menu.add_command(
                label="Очистить историю",
                command=self.clear_prompt_history,
                foreground="red"
            )
            self.history_menu.add_separator()
            
            # Добавляем промпты из истории
            for i, prompt in enumerate(self.prompt_history):
                short_prompt = (prompt[:30] + "...") if len(prompt) > 30 else prompt
                # Используем lambda с явным захватом значения prompt
                self.history_menu.add_command(
                    label=f"{i+1}. {short_prompt}",
                    command=lambda p=prompt: self.use_history_prompt(p)
                )

    def check_hotkeys(self, event):
        char = event.char.lower()
        if event.state & 0x4:
            if char == '\x16':
                self.paste_text()
                return "break"
            elif char == '\x03':
                self.copy_text()
                return "break"
            elif char == '\x18':
                self.cut_text()
                return "break"
            elif char == '\x01':
                self.select_all()
                return "break"

    def copy_text(self):
        widget = self.root.focus_get()
        if isinstance(widget, (tk.Text, SmartTextWidget)):
            widget.event_generate("<<Copy>>")

    def paste_text(self):
        widget = self.root.focus_get()
        if isinstance(widget, (tk.Text, SmartTextWidget)):
            widget.event_generate("<<Paste>>")

    def cut_text(self):
        widget = self.root.focus_get()
        if isinstance(widget, (tk.Text, SmartTextWidget)):
            widget.event_generate("<<Cut>>")

    def select_all(self):
        widget = self.root.focus_get()
        if isinstance(widget, (tk.Text, SmartTextWidget)):
            widget.tag_add('sel', '1.0', 'end')
            return "break"

    def show_context_menu(self, event):
        self.context_menu.post(event.x_root, event.y_root)

    def show_log_context_menu(self, event):
        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Копировать", command=self.copy_log_text)
        menu.add_command(label="Очистить лог", command=self.clear_log)
        menu.post(event.x_root, event.y_root)

    def copy_log_text(self):
        selected = self.log_area.get("sel.first", "sel.last")
        if selected:
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)

    def clear_log(self):
        self.log_area.config(state=tk.NORMAL)
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state=tk.DISABLED)

    def clear_placeholder(self, event):
        if self.prompt_text.get("1.0", tk.END).strip() == "Например: 'Кот в шляпе, цифровое искусство'":
            self.prompt_text.delete("1.0", tk.END)

    def clear_prompt(self):
        self.prompt_text.delete("1.0", tk.END)
        self.log_message("Поле ввода очищено")

    def get_prompt(self):
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt or prompt == "Например: 'Кот в шляпе, цифровое искусство'":
            return None
        return prompt

    def log_message(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, formatted)
        
        if level == "error":
            self.log_area.tag_add("error", "end-2c linestart", "end-1c")
            self.log_area.tag_config("error", foreground="red")
        
        self.log_area.config(state=tk.DISABLED)
        self.log_area.see(tk.END)

    def update_progress(self):
        if not self.is_generating:
            return
            
        elapsed = time.time() - self.start_time
        remaining = max(0, self.estimated_time - elapsed)
        
        if self.progress_steps > 0:
            current_step = min(int(elapsed / TIME_ESTIMATE_PER_STEP), self.progress_steps)
            self.progress["value"] = (current_step / self.progress_steps) * 100
        
        self.time_label.config(text=f"Осталось: {int(remaining)} сек.")
        
        if remaining > 0:
            self.root.after(1000, self.update_progress)
        else:
            self.time_label.config(text="Завершение...")

    def toggle_ui_state(self, generating):
        self.is_generating = generating
        state = tk.DISABLED if generating else tk.NORMAL
        
        self.generate_btn.config(state=state)
        self.stop_btn.config(state=tk.NORMAL if generating else tk.DISABLED)
        self.clear_btn.config(state=state)
        self.prompt_text.config(state=state)
        self.size_combobox.config(state=state)
        self.custom_width_entry.config(state=state)
        self.custom_height_entry.config(state=state)
        self.save_size_check.config(state=state)
        self.repeat_check.config(state=state)
        self.repeat_entry.config(state=state)
        self.history_menubutton.config(state=state)
        
        if generating:
            self.start_time = time.time()
            self.progress["value"] = 0
            self.progress["maximum"] = 100
            self.time_label.config(text="Расчет времени...")
            self.update_progress()
        else:
            self.time_label.config(text="")
            self.progress.stop()

    def stop_generation(self):
        self.should_stop = True
        self.log_message("Запрошена остановка генерации...")

    def on_size_select(self, event):
        selected = self.size_var.get()
        if selected == "Custom":
            self.custom_size_frame.pack(fill=tk.X, pady=5)
            self.selected_size = None
        else:
            self.custom_size_frame.pack_forget()
            for name, size in SIZE_OPTIONS:
                if name == selected:
                    self.selected_size = size
                    break

    def validate_custom_size(self):
        try:
            width = int(self.custom_width_var.get())
            height = int(self.custom_height_var.get())
            
            if width < 64 or height < 64:
                messagebox.showerror("Ошибка", "Минимальный размер - 64x64 пикселей")
                return False
                
            if width > 4096 or height > 4096:
                messagebox.showerror("Ошибка", "Максимальный размер - 4096x4096 пикселей")
                return False
                
            self.custom_size = (width, height)
            return True
            
        except ValueError:
            messagebox.showerror("Ошибка", "Введите корректные числовые значения")
            return False

    def get_generation_size(self):
        if self.selected_size:
            return (self.selected_size, self.selected_size)
        elif self.custom_size:
            return self.custom_size
        else:
            return (DEFAULT_SIZE, DEFAULT_SIZE)

    def generate_image(self):
        if self.is_generating:
            return
            
        prompt = self.get_prompt()
        if not prompt:
            self.log_message("Ошибка: не введен промпт", "error")
            return
            
        if self.size_var.get() == "Custom" and not self.validate_custom_size():
            return

        try:
            repeat_count = int(self.repeat_entry.get())
            if repeat_count < 1 or repeat_count > MAX_REPEATS:
                messagebox.showerror("Ошибка", f"Количество повторений должно быть от 1 до {MAX_REPEATS}")
                return
            self.repeat_count.set(repeat_count)
        except ValueError:
            messagebox.showerror("Ошибка", "Введите корректное число повторений")
            return

        self.add_to_history(prompt)
        
        self.should_stop = False
        self.current_repeat = 0
        self.estimated_time = TIME_ESTIMATE_PER_STEP * 15 * repeat_count
        self.progress_steps = 15 * repeat_count
        
        thread = threading.Thread(
            target=self._generate_image_thread, 
            args=(prompt,),
            daemon=True
        )
        thread.start()

    def add_to_history(self, prompt):
        if prompt and prompt not in self.prompt_history:
            self.prompt_history.appendleft(prompt)
            self.update_history_menu()
            self.save_prompt_history()

    def use_history_prompt(self, prompt):
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", prompt)
        self.log_message(f"Загружен промпт из истории: {prompt[:50]}...")

    def _generate_image_thread(self, prompt):
        try:
            self.root.after(0, self.toggle_ui_state, True)
            self.root.after(0, self.log_message, f"Начало генерации: '{prompt}'")
            
            width, height = self.get_generation_size()
            self.root.after(0, self.log_message, f"Размер изображения: {width}x{height}")
            
            folder_name = self.sanitize_folder_name(prompt)
            output_path = Path(OUTPUT_FOLDER) / folder_name
            output_path.mkdir(parents=True, exist_ok=True)
            self.root.after(0, self.log_message, f"Папка создана: {output_path}")
            
            prompt_file = output_path / "prompt.txt"
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(prompt)
            self.root.after(0, self.log_message, f"Промпт сохранён: {prompt_file}")

            headers = {
                "X-Key": f"Key {self.api_key}",
                "X-Secret": f"Secret {self.secret_key}",
            }
            
            response = requests.get(
                f"{API_URL}key/api/v1/pipelines", 
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            pipeline_id = response.json()[0]["id"]
            self.root.after(0, self.log_message, f"Pipeline ID: {pipeline_id}")

            repeat_times = self.repeat_count.get() if self.repeat_generation.get() else 1

            for i in range(repeat_times):
                if self.should_stop:
                    break
                    
                self.current_repeat = i + 1
                self.root.after(0, self.update_repeat_counter)
                
                if repeat_times > 1:
                    self.root.after(0, self.log_message, f"Повторение {self.current_repeat} из {repeat_times}")

                params = {
                    "type": "GENERATE",
                    "numImages": 1,
                    "width": width,
                    "height": height,
                    "generateParams": {"query": prompt},
                }
                
                response = requests.post(
                    f"{API_URL}key/api/v1/pipeline/run",
                    headers=headers,
                    files={
                        "pipeline_id": (None, pipeline_id),
                        "params": (None, json.dumps(params), "application/json")
                    },
                    timeout=30
                )
                response.raise_for_status()
                task_id = response.json()["uuid"]
                self.root.after(0, self.log_message, f"Задача создана, ID: {task_id}")

                for attempt in range(15):
                    if self.should_stop:
                        self.root.after(0, self.log_message, "Генерация прервана пользователем")
                        break
                        
                    try:
                        status = requests.get(
                            f"{API_URL}key/api/v1/pipeline/status/{task_id}",
                            headers=headers,
                            timeout=10
                        ).json()
                        
                        if status["status"] == "DONE":
                            image_data = status["result"]["files"][0]
                            break
                        elif status["status"] == "FAILED":
                            raise RuntimeError(status.get("error", "Ошибка генерации"))
                        
                        time.sleep(5)
                        self.root.after(0, self.log_message, f"Ожидание... (попытка {attempt+1}/15)")
                    except Exception as e:
                        if attempt == 14:
                            raise TimeoutError("Таймаут ожидания")
                        time.sleep(5)

                if not self.should_stop:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = output_path / f"{timestamp}_{width}x{height}_{i+1}.png"
                    
                    with open(filename, "wb") as f:
                        f.write(base64.b64decode(image_data))

                    self.root.after(0, self.log_message, f"Изображение сохранено: {filename}")
                    self.root.after(0, self.add_thumbnail, filename)
                    
                    if not self.save_original_size.get():
                        try:
                            img = Image.open(filename)
                            target_size = self.get_save_size()
                            if target_size != (width, height):
                                img_resized = img.resize(target_size, Image.LANCZOS)
                                resized_filename = output_path / f"{timestamp}_{target_size[0]}x{target_size[1]}_{i+1}.png"
                                img_resized.save(resized_filename)
                                self.root.after(0, self.log_message, f"Изображение изменено и сохранено: {resized_filename}")
                                if self.save_original_size.get():
                                    os.remove(filename)
                                    self.root.after(0, self.log_message, "Оригинальное изображение удалено")
                        except ImportError:
                            self.root.after(0, self.log_message, "Для изменения размера установите Pillow: pip install pillow", "error")
                        except Exception as e:
                            self.root.after(0, self.log_message, f"Ошибка изменения размера: {str(e)}", "error")
                
                self.root.after(0, self.log_message, "="*50)

        except Exception as e:
            self.root.after(0, self.log_message, f"Ошибка: {str(e)}", "error")
        finally:
            self.root.after(0, self.toggle_ui_state, False)
            self.should_stop = False

    def update_repeat_counter(self):
        if self.repeat_generation.get():
            self.repeat_counter.config(text=f"Повторение: {self.current_repeat}/{self.repeat_count.get()}")
        else:
            self.repeat_counter.config(text="")

    def add_thumbnail(self, image_path):
        try:
            img = Image.open(image_path)
            img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.last_generated_images.insert(0, (photo, str(image_path)))
            
            if len(self.last_generated_images) > MAX_THUMBNAILS:
                self.last_generated_images.pop()
            
            self.update_thumbnails()
            
        except Exception as e:
            self.log_message(f"Ошибка создания миниатюры: {str(e)}", "error")

    def update_thumbnails(self):
        for widget in self.thumbnails_frame.winfo_children():
            widget.destroy()
        
        for idx, (photo, path) in enumerate(self.last_generated_images):
            frame = ttk.Frame(self.thumbnails_frame)
            frame.pack(side=tk.LEFT, padx=5, pady=5)
            
            label = ttk.Label(frame, image=photo)
            label.image = photo
            label.pack()
            
            file_name = os.path.basename(path)
            ttk.Label(frame, text=file_name[:15] + "..." if len(file_name) > 15 else file_name).pack()
            label.bind("<Button-1>", lambda e, p=path: self.open_image(p))

    def open_image(self, image_path):
        try:
            if platform.system() == "Windows":
                os.startfile(image_path)
            elif platform.system() == "Darwin":
                os.system(f"open '{image_path}'")
            else:
                os.system(f"xdg-open '{image_path}'")
        except Exception as e:
            self.log_message(f"Не удалось открыть изображение: {str(e)}", "error")

    def get_save_size(self):
        if self.save_original_size.get():
            return self.get_generation_size()
        return (1024, 1024)

    def sanitize_folder_name(self, prompt):
        name = re.sub(r'[<>:"/\\|?*]', '', prompt)
        name = name.replace(' ', '_')
        return name[:MAX_FOLDER_NAME_LENGTH] or "no_name"

    def load_config(self):
        try:
            if not os.path.exists(CONFIG_FILE):
                raise FileNotFoundError(f"Файл {CONFIG_FILE} не найден!")

            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)

            if not all(k in config for k in ["api_key", "secret_key"]):
                raise ValueError("Необходимы api_key и secret_key!")

            self.api_key = config["api_key"]
            self.secret_key = config["secret_key"]
            return True

        except Exception as e:
            self.log_message(f"Ошибка загрузки конфига: {str(e)}", "error")
            self.root.destroy()
            return False

    def create_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        prompt_frame = ttk.LabelFrame(main_frame, text="Введите промпт", padding=10)
        prompt_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        history_frame = ttk.Frame(prompt_frame)
        history_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(history_frame, text="История промптов:").pack(side=tk.LEFT, padx=5)
        
        self.history_menubutton = tk.Menubutton(
            history_frame, 
            text="Выбрать из истории", 
            relief=tk.RAISED
        )
        self.history_menubutton.pack(side=tk.LEFT, padx=5)
        
        self.history_menu = tk.Menu(self.history_menubutton, tearoff=0)
        self.history_menubutton.config(menu=self.history_menu)
        
        clear_history_btn = ttk.Button(
            history_frame,
            text="Очистить историю",
            command=self.clear_prompt_history,
            style="Danger.TButton"
        )
        clear_history_btn.pack(side=tk.LEFT, padx=5)
        
        style = ttk.Style()
        style.configure("Danger.TButton", foreground="red")
        
        self.prompt_text = SmartTextWidget(
            prompt_frame,
            wrap=tk.WORD,
            width=80,
            height=10,
            font=('Arial', 10),
            padx=5,
            pady=5
        )
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        self.prompt_text.insert(tk.END, "Например: 'Кот в шляпе, цифровое искусство'")
        self.prompt_text.bind("<FocusIn>", self.clear_placeholder)
        self.prompt_text.bind("<Button-3>", self.show_context_menu)
        
        size_frame = ttk.LabelFrame(main_frame, text="Настройки размера", padding=10)
        size_frame.pack(fill=tk.X, pady=5)
        
        self.size_var = tk.StringVar(value="1024x1024")
        ttk.Label(size_frame, text="Размер изображения:").pack(side=tk.LEFT, padx=5)
        
        self.size_combobox = ttk.Combobox(
            size_frame,
            textvariable=self.size_var,
            values=[size[0] for size in SIZE_OPTIONS],
            state="readonly",
            width=15
        )
        self.size_combobox.pack(side=tk.LEFT, padx=5)
        self.size_combobox.bind("<<ComboboxSelected>>", self.on_size_select)
        
        self.custom_size_frame = ttk.Frame(size_frame)
        
        self.custom_width_var = tk.StringVar(value="1024")
        self.custom_height_var = tk.StringVar(value="1024")
        
        ttk.Label(self.custom_size_frame, text="Ширина:").pack(side=tk.LEFT)
        self.custom_width_entry = ttk.Entry(
            self.custom_size_frame,
            textvariable=self.custom_width_var,
            width=6
        )
        self.custom_width_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(self.custom_size_frame, text="Высота:").pack(side=tk.LEFT)
        self.custom_height_entry = ttk.Entry(
            self.custom_size_frame,
            textvariable=self.custom_height_var,
            width=6
        )
        self.custom_height_entry.pack(side=tk.LEFT, padx=5)
        
        save_frame = ttk.Frame(size_frame)
        save_frame.pack(side=tk.RIGHT, padx=10)
        
        self.save_size_check = ttk.Checkbutton(
            save_frame,
            text="Сохранять оригинальный размер",
            variable=self.save_original_size,
            onvalue=True,
            offvalue=False
        )
        self.save_size_check.pack(side=tk.LEFT)
        
        repeat_frame = ttk.Frame(main_frame)
        repeat_frame.pack(fill=tk.X, pady=5)
        
        self.repeat_check = ttk.Checkbutton(
            repeat_frame,
            text="Повторить генерацию",
            variable=self.repeat_generation,
            onvalue=True,
            offvalue=False
        )
        self.repeat_check.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(repeat_frame, text="Количество повторений (1-1000):").pack(side=tk.LEFT, padx=5)
        self.repeat_entry = ttk.Entry(
            repeat_frame,
            textvariable=self.repeat_count,
            width=5
        )
        self.repeat_entry.pack(side=tk.LEFT, padx=5)
        
        self.repeat_counter = ttk.Label(repeat_frame, text="", foreground="blue")
        self.repeat_counter.pack(side=tk.LEFT, padx=10)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        self.generate_btn = ttk.Button(
            button_frame,
            text="Сгенерировать изображение",
            command=self.generate_image
        )
        self.generate_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(
            button_frame,
            text="Остановить",
            command=self.stop_generation,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        self.clear_btn = ttk.Button(
            button_frame,
            text="Очистить",
            command=self.clear_prompt
        )
        self.clear_btn.pack(side=tk.LEFT, padx=5)
        
        self.progress = ttk.Progressbar(button_frame, mode='determinate')
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.time_label = ttk.Label(button_frame, text="")
        self.time_label.pack(side=tk.LEFT, padx=5)
        
        thumbnails_frame = ttk.LabelFrame(main_frame, text="Последние изображения", padding=10)
        thumbnails_frame.pack(fill=tk.X, pady=5)
        self.thumbnails_frame = ttk.Frame(thumbnails_frame)
        self.thumbnails_frame.pack(fill=tk.X)
        
        log_frame = ttk.LabelFrame(main_frame, text="Лог выполнения", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_area = SmartTextWidget(
            log_frame,
            wrap=tk.WORD,
            width=80,
            height=15,
            font=('Consolas', 9),
            state=tk.DISABLED
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.log_area.bind("<Button-3>", self.show_log_context_menu)

if __name__ == "__main__":
    root = tk.Tk()
    app = ImageGenerator(root)
    root.mainloop()