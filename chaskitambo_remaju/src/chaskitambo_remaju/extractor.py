import os
import sys
import json
import logging
from pathlib import Path

# Configuración básica de logging para auditoría de pestañas internas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuExtractorError(Exception):
    """Excepciones personalizadas para errores críticos en el módulo extractor."""
    pass

class RemajuExtractorScraper:
    def __init__(
        self, 
        page=None, 
        carpeta_raiz_drive: str = "1lsNX5GEiM7-Ho2kTbu00AqfckAnyWyFl", 
        config_path: str = "config.json",
        **kwargs
    ):
        """
        Inicializa el extractor de la ficha detallada por pestañas de REMAJU con Playwright.
        Soporta la instanciación dinámica cross-vertical de Chaskitambo y Quipu.
        """
        self.page = page
        self.carpeta_raiz_drive = carpeta_raiz_drive
        self.config_path = Path(config_path)
        self.app_config = self._load_app_config()
        
        # Desglose estricto de URLs en variables independientes y concatenación posterior
        protocolo = "https://"
        subdominio_api = "google"
        dominio_api = "apis.com"
        subdominio_com = "com."
        dominio_readonly = "readonly"

        url_scope_1 = protocolo + subdominio_api + dominio_api
        url_scope_2 = protocolo + subdominio_com + dominio_readonly

        self.scopes = [url_scope_1, url_scope_2]

    def _load_app_config(self) -> dict:
        """Carga y valida el archivo de configuración dinámico para los DTOs."""
        if not self.config_path.exists():
            logger.warning(f"Archivo de configuración no encontrado en: {self.config_path}. Se usarán diccionarios vacíos.")
            return {}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer 'config.json': {e}")
            return {}

    async def esperar_sincronizacion_primefaces(self):
        """Espera activa para la desaparición del overlay de carga 'dlgEstado' y sincronización AJAX."""
        try:
            await self.page.wait_for_function("() => typeof jQuery === 'undefined' || jQuery.active === 0", timeout=12000)
        except Exception:
            pass

        try:
            await self.page.wait_for_selector("#dlgEstado_modal, .ui-widget-overlay", state="hidden", timeout=12000)
        except Exception:
            await self.page.evaluate("""() => {
                if (typeof PF !== 'undefined' && PF('dlgEstado')) {
                    try { PF('dlgEstado').hide(); } catch(e) {}
                }
                document.querySelectorAll('#dlgEstado_modal, .ui-widget-overlay').forEach(el => el.remove());
            }""")
        await self.page.wait_for_timeout(800)

    async def extract_tab_remate_completo(self) -> dict:
        """Extrae de manera integral todos los datos del formulario navegando por las pestañas."""
        await self.page.wait_for_selector("//div[contains(text(), 'Expediente')]", state="visible", timeout=10000)
       
        datos = {
            "remate": {},
            "inmuebles": [{}],
            "cronograma": {}
        }

        mapeo_remate = self.app_config.get("mapeo_remate", {})
        mapeo_inmuebles = self.app_config.get("mapeo_inmuebles", {})
        mapeo_cronograma = self.app_config.get("mapeo_cronograma", {})

        # --- TAB 1: REMATE (Resumen) ---
        logger.info("    -> Extrayendo Tab 1: Remate...")
        async def get_val(label):
            try:
                val = await self.page.locator(f"//div[contains(text(), '{label}')]/following-sibling::div[contains(@class, 'text-justify') or contains(@class, 'ui-panelgrid-cell')]").first.inner_text(timeout=2000)
                return val.strip()
            except Exception:
                try:
                    xpath = f"//div[contains(@class, 'ui-g')][div[contains(text(), '{label}')]]/div[contains(@class, 'text-justify') or contains(@class, 'ui-panelgrid-cell')][last()]"
                    val = await self.page.locator(xpath).first.inner_text(timeout=2000)
                    return val.strip()
                except Exception:
                    return ""

        for dto_key, label_text in mapeo_remate.items():
            if dto_key == "tipoCambio":
                try:
                    spans = self.page.locator("span.label-danger.text-bold")
                    count = await spans.count()
                    if count > 0:
                        partes = [(await spans.nth(i).inner_text()).strip() for i in range(count)]
                        datos["remate"]["tipoCambio"] = " ".join(partes)
                    else:
                        datos["remate"]["tipoCambio"] = await get_val(label_text)
                except Exception:
                    datos["remate"]["tipoCambio"] = await get_val(label_text)
            else:
                datos["remate"][dto_key] = await get_val(label_text)

        try:
            datos["remate"]["descripcion"] = await self.page.locator("//div[contains(@class, 'texto-info-scroll')]").first.inner_text(timeout=2000)
        except Exception:
            datos["remate"]["descripcion"] = ""

        # --- TAB 2: INMUEBLES ---
        try:
            logger.info("    -> Abriendo Tab 2: Inmuebles...")
            await self.esperar_sincronizacion_primefaces()
            await self.page.wait_for_timeout(2000)

            tab_inmuebles = self.page.locator("li[data-index='1'], li:has-text('Inmuebles')").first
            await tab_inmuebles.click(force=True)

            await self.page.wait_for_selector("xpath=//div[contains(@id, 'tbInmuebles')]", state="visible", timeout=10000)

            async def get_ubicacion(label):
                xpath = f"//div[normalize-space(text())='{label}']/following-sibling::div[1]"
                try:
                    return (await self.page.locator(xpath).inner_text(timeout=2000)).strip()
                except Exception:
                    return ""

            header_keys = ["distritoJudicial", "departamento", "provincia", "distrito"]
            for dto_key in header_keys:
                if dto_key in mapeo_inmuebles:
                    datos["inmuebles"][0][dto_key] = await get_ubicacion(mapeo_inmuebles[dto_key])

            base_xpath = "//tbody[contains(@id, 'dtResumenInmueble_data')]/tr[1]"
            
            async def get_td_val(col_index, title_text):
                try:
                    cell = self.page.locator(f"{base_xpath}/td[{col_index}]")
                    texto = await cell.inner_text(timeout=2000)
                    return texto.replace(title_text, "").replace("\n", " ").strip()
                except Exception:
                    return ""

            datos["inmuebles"][0]["partidaRegistral"] = await get_td_val(1, "Partida Registral")
            datos["inmuebles"][0]["tipoInmueble"] = await get_td_val(2, "Tipo Inmueble")
            datos["inmuebles"][0]["direccion"] = await get_td_val(3, "Dirección")
            datos["inmuebles"][0]["cargaYGravamen"] = await get_td_val(4, "Carga y/o Gravamen")
            datos["inmuebles"][0]["porcentajeRematar"] = await get_td_val(5, "Porcentaje a Rematar")

        except Exception as e:
            logger.warning(f"    -> [WARNING] Omisión en la grilla de Inmuebles: {e}")

        # --- TAB 3: CRONOGRAMA ---
        try:
            logger.info("    -> Abriendo Tab 3: Cronograma...")
            await self.esperar_sincronizacion_primefaces()
            await self.page.wait_for_timeout(2000)

            tab_cronograma = self.page.locator("li[data-index='2'], li:has-text('Cronograma')").first
            await tab_cronograma.click(force=True)

            await self.page.wait_for_selector("xpath=//div[contains(@id, 'tbCronograma')]", state="visible", timeout=10000)

            async def get_fecha_cronograma(fase_keyword, columna_idx):
                xpath = f"//tbody[contains(@id, 'dtCronograma_data')]/tr[td[2][contains(., '{fase_keyword}')]]/td[{columna_idx}]"
                try:
                    cell = self.page.locator(xpath).first
                    texto_raw = await cell.inner_text(timeout=2000)
                    return texto_raw.replace("Fecha Inicio", "").replace("Fecha Fin", "").replace("\n", " ").strip()
                except Exception:
                    return ""

            for dto_key, label_text in mapeo_cronograma.items():
                col_idx = 3 if "Inicio" in dto_key else 4
                datos["cronograma"][dto_key] = await get_fecha_cronograma(label_text, col_idx)

        except Exception as e:
            logger.warning(f"    -> [WARNING] Omisión en la grilla de Cronograma: {e}")

        return datos

    async def download_resolucion_pdf(self, expediente_num: str, ruta_descargas_local: str = "./descargas_resoluciones") -> str:
        """Regresa al Tab 1, intercepta la descarga de PrimeFaces y guarda el PDF localmente."""
        try:
            logger.info("    -> Activando Tab 1 (Resumen) para buscar el PDF...")
            tab_resumen = self.page.locator("li[data-index='0'], li:has-text('Resumen')").first
            await tab_resumen.click(force=True)
            await self.esperar_sincronizacion_primefaces()
            await self.page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"  -> [WARNING] No se pudo cambiar al Tab 1 para el PDF: {e}")

        if not os.path.exists(ruta_descargas_local):
            os.makedirs(ruta_descargas_local)

        expediente_limpio = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in str(expediente_num))
        selector_pdf = "a.ui-commandlink:has-text('resolucion.pdf')"
        nombre_archivo = f"resolucion_{expediente_limpio}.pdf"
        ruta_destino = os.path.join(ruta_descargas_local, nombre_archivo)

        try:
            btn_elemento = self.page.locator(selector_pdf)
            await btn_elemento.wait_for(state="visible", timeout=6000)

            async with self.page.expect_download(timeout=15000) as download_info:
                await btn_elemento.click(force=True)

            download = await download_info.value
            await download.save_as(ruta_destino)
            logger.info(f"  -> [OK] Archivo PDF descargado correctamente en disco: {nombre_archivo}")
            return nombre_archivo
        except Exception as e:
            logger.warning(f"  -> [INFO] Sin PDF de resolución o descarga omitida por PrimeFaces: {e}")
            return ""

    def adaptar_a_dto(self, datos_extraidos, archivo_nombre_pdf: str = None) -> dict:
        """Adapta el diccionario crudo al modelo DTO dinámico limpiando firmas de red."""
        def limpiar(val):
            if not val or not str(val).strip():
                return ""
            txt = str(val).strip()
            if "Firma Web" in txt or "Descarga componente" in txt:
                return ""
            return txt

        rem = datos_extraidos.get("remate", {})
        inm_list = datos_extraidos.get("inmuebles", [{}])
        inm = inm_list[0] if inm_list else {}
        cro = datos_extraidos.get("cronograma", {})
        
        dto_final = {
            "remate": {},
            "inmuebles": [{}],
            "cronograma": {}
        }
        
        for key, value in rem.items():
            dto_final["remate"][key] = limpiar(value)
            
        dto_final["remate"]["archivoUrl"] = limpiar(archivo_nombre_pdf if archivo_nombre_pdf else rem.get("archivoUrl", ""))
        
        for key, value in inm.items():
            dto_final["inmuebles"][0][key] = limpiar(value)
            
        for key, value in cro.items():
            dto_final["cronograma"][key] = limpiar(value)
            
        return dto_final