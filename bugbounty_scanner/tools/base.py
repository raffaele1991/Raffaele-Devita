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

    def __init__(self):
        self.output_dir = None

    def is_installed(self) -> bool:
        """Verifica se il tool è installato."""
        return shutil.which(self.binary) is not None

    def check_installed(self):
        """Lancia errore se il tool non è installato."""
        if not self.is_installed():
            raise ToolNotFoundError(
                f"'{self.binary}' non trovato. "
                f"Installalo da: {self.install_url}\n"
                f"Oppure lancia: ./install_tools.sh"
            )

    def run_command(self, args, timeout=300, parse_json=False, stdin_data=None):
        """Esegue un comando e ritorna l'output."""
        cmd = [self.binary] + args
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
