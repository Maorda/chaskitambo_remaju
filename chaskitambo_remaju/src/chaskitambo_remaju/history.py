# D:\libs\chaskitambo_plugins\chaskitambo_remaju\src\chaskitambo_remaju\history.py
import json
import logging
import os
from pathlib import Path
import tempfile

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuHistoryManager:
    def __init__(self, filepath: str | Path = None):
        """Inicializa el gestor con una ruta absoluta unificada para evitar archivos fantasmas."""
        # CORREGIDO: Forzamos la persistencia centralizada en la raíz común del ecosistema
        if filepath is None:
            self.filepath = Path(r"D:\libs\chaskitambo\historial_procesados.json")
        else:
            self.filepath = Path(filepath)
            
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not self.filepath.exists():
            try:
                self.filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(self.filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4, ensure_ascii=False)
                logger.info(f"[HISTORIAL] Archivo unificado inicializado en: {self.filepath.resolve()}")
            except Exception as e:
                logger.error(f"Error crítico al inicializar el archivo de historial {self.filepath}: {e}")
                raise

    def _load_data(self) -> list:
        if not self.filepath.exists():
            return []
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
        except Exception as e:
            logger.error(f"Error al leer el archivo de historial: {e}")
            return []

    def _save_data_atomically(self, data: list):
        dir_name = self.filepath.parent
        dir_name.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
                json.dump(data, tf, indent=4, ensure_ascii=False)
                temp_name = tf.name
            os.replace(temp_name, self.filepath)
        except Exception as e:
            logger.error(f"Error crítico al guardar de forma atómica el historial: {e}")
            if temp_name and os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except Exception:
                    pass
            raise

    def is_processed(self, numero_expediente: str, numero_convocatoria: str) -> bool:
        records = self._load_data()
        exp = str(numero_expediente).strip().upper()
        conv = str(numero_convocatoria).strip().upper()

        for record in records:
            r_exp = str(record.get("expediente", "")).strip().upper()
            r_conv = str(record.get("convocatoria", "")).strip().upper()
            if r_exp == exp and r_conv == conv:
                return True
        return False

    def save_processed(self, numero_expediente: str, numero_convocatoria: str):
        exp = str(numero_expediente).strip().upper()
        conv = str(numero_convocatoria).strip().upper()

        if not exp or not conv:
            return

        records = self._load_data()
        exists = any(
            str(r.get("expediente", "")).strip().upper() == exp and 
            str(r.get("convocatoria", "")).strip().upper() == conv
            for r in records
        )

        if exists:
            return

        records.append({"expediente": exp, "convocatoria": conv})
        self._save_data_atomically(records)
        logger.info(f"💾 [HISTORIAL] Registro indexado -> Expediente: {exp} | Convocatoria: {conv}")
