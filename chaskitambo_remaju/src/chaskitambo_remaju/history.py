import json
import logging
import os
from pathlib import Path
import tempfile

# Configuración básica de logging para el gestor de historial
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuHistoryManager:
    def __init__(self, filepath: str = "historial_procesados.json"):
        """
        Inicializa el gestor de historial para prevenir la duplicidad de expedientes procesados.
        :param filepath: Ruta al archivo JSON de persistencia local.
        """
        self.filepath = Path(filepath)
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """Regla 1: Busca el archivo local de historial; si no existe, lo crea vacío."""
        if not self.filepath.exists():
            try:
                self.filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(self.filepath, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4, ensure_ascii=False)
                logger.info(f"Archivo de historial creado exitosamente en: {self.filepath.resolve()}")
            except Exception as e:
                logger.error(f"Error crítico al inicializar el archivo de historial {self.filepath}: {e}")
                raise

    def _load_data(self) -> list:
        """Carga de forma segura los registros actuales desde el archivo JSON."""
        if not self.filepath.exists():
            return []
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                logger.warning(f"El archivo {self.filepath} no contiene una lista válida. Reinicializando.")
                return []
        except json.JSONDecodeError:
            logger.warning(f"El archivo {self.filepath} está corrupto o malformado. Retornando historial vacío.")
            return []
        except Exception as e:
            logger.error(f"Error inesperado al leer el archivo de historial: {e}")
            return []

    def _save_data_atomically(self, data: list):
        """
        Guarda los datos en disco de forma síncrona y atómica usando un archivo temporal
        en el mismo directorio para prevenir pérdida o corrupción de datos ante cortes abruptos.
        """
        dir_name = self.filepath.parent
        dir_name.mkdir(parents=True, exist_ok=True)
        
        temp_name = None
        try:
            # Crear archivo temporal seguro en la misma partición/directorio
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
                json.dump(data, tf, indent=4, ensure_ascii=False)
                temp_name = tf.name
            
            # Operación atómica de reemplazo a nivel de sistema operativo
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
        """
        Regla 2: Retorna True si la combinación exacta de expediente y convocatoria ya existe en el JSON.
        """
        records = self._load_data()
        exp = str(numero_expediente).strip()
        conv = str(numero_convocatoria).strip()

        for record in records:
            r_exp = str(record.get("expediente", "")).strip()
            r_conv = str(record.get("convocatoria", "")).strip()
            if r_exp == exp and r_conv == conv:
                return True
                
        return False

    def save_processed(self, numero_expediente: str, numero_convocatoria: str):
        """
        Regla 3: Añade la combinación al archivo JSON y guarda los cambios inmediatamente 
        de forma síncrona y atómica.
        """
        exp = str(numero_expediente).strip()
        conv = str(numero_convocatoria).strip()

        if not exp or not conv:
            logger.warning("Intento de registrar un expediente o convocatoria vacíos en el historial. Omitido.")
            return

        records = self._load_data()

        # Validación en memoria para evitar duplicados redundantes
        exists = any(
            str(r.get("expediente", "")).strip() == exp and 
            str(r.get("convocatoria", "")).strip() == conv
            for r in records
        )

        if exists:
            logger.info(f"El expediente '{exp}' (Convocatoria: {conv}) ya se encontraba registrado previamente.")
            return

        new_entry = {
            "expediente": exp,
            "convocatoria": conv
        }
        
        records.append(new_entry)
        self._save_data_atomically(records)
        logger.info(f"Historial actualizado exitosamente -> Expediente: {exp} | Convocatoria: {conv}")
