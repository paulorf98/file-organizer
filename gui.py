from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from organizer import ConfigError, FileOrganizer, load_categories

# Configurações de tema do CustomTkinter
ctk.set_appearance_mode("System")  # "System", "Dark" ou "Light"
ctk.set_default_color_theme("blue")  # "blue", "green" ou "dark-blue"


class FileOrganizerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        # Configurações da Janela
        self.title("File Organizer Pro")
        self.geometry("600x500")
        self.resizable(False, False)

        # Variáveis de Estado
        self.selected_path = ctk.StringVar(value="")
        self.config_path = ctk.StringVar(value="")

        # Layout da Interface
        self._create_widgets()

    def _create_widgets(self) -> None:
        # Título Principal
        title_label = ctk.CTkLabel(
            self, 
            text="File Organizer", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title_label.pack(pady=(20, 10))

        # Seção 1: Seleção de Diretório
        path_frame = ctk.CTkFrame(self)
        path_frame.pack(fill="x", padx=20, pady=10)

        path_label = ctk.CTkLabel(path_frame, text="Target Directory:", font=ctk.CTkFont(weight="bold"))
        path_label.pack(anchor="w", padx=10, pady=(10, 2))

        path_entry = ctk.CTkEntry(path_frame, textvariable=self.selected_path, placeholder_text="Select a folder...")
        path_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)

        browse_btn = ctk.CTkButton(path_frame, text="Browse", width=80, command=self._browse_directory)
        browse_btn.pack(side="right", padx=(5, 10), pady=10)

        # Seção 2: Configuração e Opções
        options_frame = ctk.CTkFrame(self)
        options_frame.pack(fill="x", padx=20, pady=10)

        # Config JSON opcional
        config_entry = ctk.CTkEntry(
            options_frame, 
            textvariable=self.config_path, 
            placeholder_text="Custom config.json (optional)"
        )
        config_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)

        config_btn = ctk.CTkButton(options_frame, text="Config", width=80, command=self._browse_config)
        config_btn.pack(side="right", padx=(5, 10), pady=10)

        # Switch para Dry-Run (Modo de Teste)
        self.dry_run_switch = ctk.CTkSwitch(self, text="Dry-Run Mode (Preview without moving files)")
        self.dry_run_switch.pack(pady=10)

        # Seção 3: Botões de Ação
        actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        actions_frame.pack(pady=10)

        organize_btn = ctk.CTkButton(
            actions_frame, 
            text="Organize Files", 
            fg_color="#2b8a3e", 
            hover_color="#216a30", 
            font=ctk.CTkFont(weight="bold"),
            command=self._run_organize
        )
        organize_btn.pack(side="left", padx=10)

        undo_btn = ctk.CTkButton(
            actions_frame, 
            text="Undo Last Run", 
            fg_color="#c92a2a", 
            hover_color="#a61e1e", 
            font=ctk.CTkFont(weight="bold"),
            command=self._run_undo
        )
        undo_btn.pack(side="right", padx=10)

        # Seção 4: Log / Feedback Visual
        self.log_textbox = ctk.CTkTextbox(self, width=560, height=150)
        self.log_textbox.pack(padx=20, pady=(10, 20))
        self._log("Welcome! Select a folder to organize.")

    # Handlers & Lógica
    def _browse_directory(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.selected_path.set(folder)

    def _browse_config(self) -> None:
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if file_path:
            self.config_path.set(file_path)

    def _log(self, message: str) -> None:
        self.log_textbox.insert("end", f"{message}\n")
        self.log_textbox.see("end")

    def _get_organizer_instance(self, dry_run: bool = False) -> FileOrganizer | None:
        target_path = self.selected_path.get().strip()
        if not target_path:
            messagebox.showwarning("Warning", "Please select a target directory first.")
            return None

        categories = None
        config_file = self.config_path.get().strip()
        if config_file:
            try:
                categories = load_categories(config_file)
            except ConfigError as err:
                messagebox.showerror("Config Error", str(err))
                return None

        try:
            return FileOrganizer(target_path, categories=categories, dry_run=dry_run)
        except ValueError as err:
            messagebox.showerror("Error", str(err))
            return None

    def _run_organize(self) -> None:
        is_dry_run = bool(self.dry_run_switch.get())
        
        # Confirmação de segurança antes de disparar (exceto em dry-run)
        if not is_dry_run:
            target = self.selected_path.get()
            confirmed = messagebox.askyesno(
                "Confirmation", 
                f"Are you sure you want to organize files in:\n{target}?"
            )
            if not confirmed:
                return

        organizer = self._get_organizer_instance(dry_run=is_dry_run)
        if not organizer:
            return

        mode_str = "[DRY-RUN] " if is_dry_run else ""
        self._log(f"\n--- {mode_str}Starting Organization ---")

        try:
            moves = organizer.organize()
        except ValueError as err:
            messagebox.showerror("History Error", str(err))
            self._log(f"Error: {err}")
            return

        action_verb = "Would move" if is_dry_run else "Moved"
        for move in moves:
            src = Path(move["source"]).name
            dest_folder = Path(move["destination"]).parent.name
            self._log(f"-> {action_verb}: '{src}' to '{dest_folder}/'")

        suffix_text = " would be processed." if is_dry_run else " processed."
        self._log(f"Done! {len(moves)} file(s){suffix_text}")

    def _run_undo(self) -> None:
        target = self.selected_path.get()
        if not target:
            messagebox.showwarning("Warning", "Please select a target directory first.")
            return

        confirmed = messagebox.askyesno(
            "Confirmation", 
            "Are you sure you want to revert the last organization run?"
        )
        if not confirmed:
            return

        organizer = self._get_organizer_instance()
        if not organizer:
            return

        self._log("\n--- Starting Undo ---")
        
        try:
            restored = organizer.undo()
        except ValueError as err:
            messagebox.showerror("History Error", str(err))
            self._log(f"Error: {err}")
            return

        if restored == 0:
            self._log("Nothing to undo: no valid history found or files already gone.")
            messagebox.showinfo("Undo", "Nothing to undo: no history found.")
        else:
            self._log(f"Undo completed! {restored} file(s) restored.")


if __name__ == "__main__":
    app = FileOrganizerApp()
    app.mainloop()