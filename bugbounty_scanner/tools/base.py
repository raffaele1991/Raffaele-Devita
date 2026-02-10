"""Classe base per i wrapper dei tool esterni."""

import json
import logging
import shutil
import subprocess
import tempfile
import os

logger = logging.getLogger("bugbounty_scanner")


class ToolNotFoundError(Exception):
    """Il tool non è installato nel sistema."""
    pass


class BaseTool:
    """Classe base che wrappa un tool esterno da riga di comando."""

    name = "base"
    binary = "base"
    install_url = ""

    # Path aggiuntive dove cercare i binari (Go, snap, usr/local, ecc.)
    _EXTRA_PATHS = [
        os.path.expanduser("~/go/bin"),
        "/usr/local/go/bin",
        "/usr/local/bin",
        "/snap/bin",
        os.path.expanduser("~/.local/bin"),
        "/opt/homebrew/bin",
    ]

    def __init__(self):
        self.output_dir = None
        self._custom_headers = {}
        self._binary_path = None  # Cache del path completo trovato

    def set_headers(self, headers_dict):
        """Imposta header custom da passare ai tool che li supportano."""
        self._custom_headers = headers_dict or {}

    def get_header_args(self, flag="-H"):
        """Genera argomenti CLI per gli header custom (formato -H 'Key: Value')."""
        args = []
        for key, value in self._custom_headers.items():
            args.extend([flag, f"{key}: {value}"])
        return args

    def _find_binary(self) -> str | None:
        """Cerca il binario nelle directory Go/local PRIMA del PATH di sistema.

        Questo evita conflitti come Python httpx (pip) vs Go httpx
        (projectdiscovery). I tool di sicurezza sono quasi tutti Go-based,
        quindi le directory Go/local hanno priorità.
        """
        # 1) Cerca PRIMA nelle directory Go / local / snap
        for extra_dir in self._EXTRA_PATHS:
            candidate = os.path.join(extra_dir, self.binary)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        # 2) Fallback al PATH di sistema
        path = shutil.which(self.binary)
        if path:
            return path

        return None

    def is_installed(self) -> bool:
        """Verifica se il tool è installato."""
        self._binary_path = self._find_binary()
        return self._binary_path is not None

    def check_installed(self):
        """Lancia errore se il tool non è installato."""
        if not self.is_installed():
            raise ToolNotFoundError(
                f"'{self.binary}' non trovato. "
                f"Installalo da: {self.install_url}\n"
                f"Oppure lancia: ./install_tools.sh"
            )

    def _get_binary_cmd(self) -> str:
        """Restituisce il path completo al binario, o il nome se nel PATH."""
        if self._binary_path:
            return self._binary_path
        # Riprova a cercare
        found = self._find_binary()
        return found if found else self.binary

    def run_command(self, args, timeout=300, parse_json=False, stdin_data=None):
        """Esegue un comando e ritorna l'output."""
        cmd = [self._get_binary_cmd()] + args
        logger.debug(f"  [{self.name}] Eseguo: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=stdin_data,
            )

            if result.returncode != 0 and result.stderr:
                logger.warning(f"  [{self.name}] stderr: {result.stderr[:500]}")

            output = result.stdout.strip()

            if parse_json and output:
                try:
                    return json.loads(output)
                except json.JSONDecodeError:
                    # Prova a parsare riga per riga (JSONL)
                    results = []
                    for line in output.splitlines():
                        line = line.strip()
                        if line:
                            try:
                                results.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                    return results

            return output

        except subprocess.TimeoutExpired:
            logger.error(f"  [{self.name}] Timeout dopo {timeout}s")
            return None
        except FileNotFoundError:
            raise ToolNotFoundError(f"'{self.binary}' non trovato nel PATH")

    def make_temp_file(self, content="", suffix=".txt"):
        """Crea un file temporaneo con il contenuto dato."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return path

    def run(self, target, scan_result):
        """Da implementare nelle sottoclassi."""
        raise NotImplementedError
