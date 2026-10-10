# D:\libs\chaskitambo_plugins\chaskitambo_remaju\src\chaskitambo_remaju\history.py
import json
import logging
import os
from pathlib import Path
import tempfile

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class RemajuHistoryManager:

  def __init__(
      self,
      filepath: str | Path = None,
      failed_filepath: str | Path = None,
  ):
    """Inicializa el gestor con rutas unificadas absolutas para registros procesados y fallidos[cite: 6]."""
    if filepath is None:
      self.filepath = Path(r"D:\libs\chaskitambo\historial_procesados.json")
    else:
      self.filepath = Path(filepath)

    if failed_filepath is None:
      self.failed_filepath = (
          self.filepath.parent / "historial_fallidos.json"
      )
    else:
      self.failed_filepath = Path(failed_filepath)

    self._ensure_files_exist()

  def _ensure_files_exist(self):
    """Crea los archivos JSON de persistencia si no existen en el sistema de archivos[cite: 6]."""
    for path in [self.filepath, self.failed_filepath]:
      if not path.exists():
        try:
          path.parent.mkdir(parents=True, exist_ok=True)
          with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)
          logger.info(
              f"[HISTORIAL] Archivo de persistencia inicializado en:"
              f" {path.resolve()}"
          )
        except Exception as e:
          logger.error(
              f"Error crítico al inicializar el archivo de historial {path}:"
              f" {e}"
          )
          raise

  def _load_data(self, target_path: Path) -> list:
    if not target_path.exists():
      return []
    try:
      with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
      return []
    except Exception as e:
      logger.error(f"Error al leer archivo {target_path}: {e}")
      return []

  def _save_data_atomically(self, target_path: Path, data: list):
    """Guarda los registros en disco de forma atómica para evitar corrupción de archivos[cite: 6]."""
    dir_name = target_path.parent
    dir_name.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
      with tempfile.NamedTemporaryFile(
          "w", dir=dir_name, delete=False, encoding="utf-8"
      ) as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
      os.replace(temp_name, target_path)
    except Exception as e:
      logger.error(f"Error crítico al guardar atómicamente en {target_path}: {e}")
      if temp_name and os.path.exists(temp_name):
        try:
          os.remove(temp_name)
        except Exception:
          pass
      raise

  # --- PROCESADOS EXITOSOS ---
  def is_processed(
      self, numero_expediente: str, numero_convocatoria: str
  ) -> bool:
    records = self._load_data(self.filepath)
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

    records = self._load_data(self.filepath)
    exists = any(
        str(r.get("expediente", "")).strip().upper() == exp
        and str(r.get("convocatoria", "")).strip().upper() == conv
        for r in records
    )

    if not exists:
      records.append({"expediente": exp, "convocatoria": conv})
      self._save_data_atomically(self.filepath, records)
      logger.info(
          f"💾 [HISTORIAL] Registro indexado -> Expediente: {exp} | Convocatoria:"
          f" {conv}"
      )

    # Remueve el expediente de la cola de fallidos si se procesa exitosamente
    self.remove_failed(exp, conv)

  # --- COLA DE REINTENTOS Y FALLIDOS ---
  def save_failed(
      self,
      identificador_remate: str,
      convocatoria: str = "",
      motivo: str = "",
  ):
    """Guarda un expediente o remate que presentó fallos en la cola de reintentos[cite: 6]."""
    rem_id = str(identificador_remate).strip().upper()
    conv = str(convocatoria).strip().upper()

    if not rem_id:
      return

    records = self._load_data(self.failed_filepath)
    exists = any(
        str(r.get("remate", "")).strip().upper() == rem_id for r in records
    )

    if exists:
      return

    records.append(
        {"remate": rem_id, "convocatoria": conv, "motivo": motivo}
    )
    self._save_data_atomically(self.failed_filepath, records)
    logger.warning(
        f"⚠️ [HISTORIAL-FALLIDOS] Indexado a cola de reintentos -> Remate:"
        f" {rem_id} | Motivo: {motivo}"
    )

  def get_failed_items(self) -> list:
    """Retorna la lista completa de remates pendientes de reintento[cite: 6]."""
    return self._load_data(self.failed_filepath)

  def remove_failed(self, identificador_remate: str, convocatoria: str = ""):
    """Elimina un remate de la lista de fallidos una vez procesado correctamente[cite: 6]."""
    rem_id = str(identificador_remate).strip().upper()
    if not rem_id:
      return

    records = self._load_data(self.failed_filepath)
    nuevos_records = [
        r
        for r in records
        if str(r.get("remate", "")).strip().upper() != rem_id
        and str(r.get("expediente", "")).strip().upper() != rem_id
    ]

    if len(nuevos_records) != len(records):
      self._save_data_atomically(self.failed_filepath, nuevos_records)
      logger.info(
          f"🧹 [HISTORIAL-FALLIDOS] Remate eliminado de la cola de fallidos:"
          f" {rem_id}"
      )
