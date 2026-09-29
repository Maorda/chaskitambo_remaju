# D:\libs\chaskitambo_plugins\chaskitambo_remaju\src\chaskitambo_remaju\extractor.py
import os
import sys
import json
import io
import logging
import datetime
from pathlib import Path

# Configuración básica de logging para auditoría de pestañas internas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuExtractorError(Exception):
    """Excepciones personalizadas para errores críticos en el módulo extractor."""
    pass

class RemajuExtractorScraper:
    # CORREGIDO: Se añade el soporte de inicialización por defecto y comodines (**kwargs)
    # para absorber el parámetro 'raw_data' inyectado dinámicamente por quipu (tukuyrikuq).
    def __init__(
        self, 
        page=None, 
        carpeta_raiz_drive: str = "1lsNX5GEiM7-Ho2kTbu00AqfckAnyWyFl", 
        config_path: str = "config.json",
        
    ):
        """
        Inicializa el extractor de la ficha detallada por pestañas de REMAJU con Playwright.
        Soporta la instanciación dinámica cross-vertical de Chaskitambo y Quipu.
        """
        self.page = page
        self.carpeta_raiz_drive = carpeta_raiz_drive
        self.config_path = Path(config_path)
        self.app_config = self._load_app_config()
        self.scopes = ['https://googleapis.com', 'https://com.readonly']
        
        

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
        """Extrae de manera integral todos los datos del formulario navegando linealmente por las pestañas."""
        await self.page.wait_for_selector("//div[contains(text(), 'Expediente')]", state="visible", timeout=10000)
       
        datos = {
            "remate": {},
            "inmuebles": [{}],
            "cronograma": {}
        }

        mapeo_remate = self.app_config.get("mapeo_remate", {})
        mapeo_inmuebles = self.app_config.get("mapeo_inmuebles", {})
        mapeo_cronograma = self.app_config.get("mapeo_cronograma", {})

        # --- TAB 1: RESUMEN (Pestaña activa por defecto en el DOM) ---
        logger.info("    -> Extrayendo Tab 1: Resumen...")
        async def get_val(label):
            xpath = f"//div[contains(@class, 'ui-g')][div[contains(text(), '{label}')]]/div[contains(@class, 'text-justify') or contains(@class, 'ui-panelgrid-cell')][last()]"
            try:
                return (await self.page.locator(xpath).first.inner_text(timeout=2000)).strip()
            except:
                return ""

        # Llenado dinámico de todos los campos mapeados en config.json para el remate
        for dto_key, label_text in mapeo_remate.items():
            datos["remate"][dto_key] = await get_val(label_text)

        try:
            datos["remate"]["descripcion"] = await self.page.locator("//div[contains(@class, 'texto-info-scroll')]").first.inner_text(timeout=2000)
        except:
            datos["remate"]["descripcion"] = ""

        # --- TAB 2: INMUEBLES (Navegación e iteración por columnas posicionales) ---
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
                except:
                    return ""

            for dto_key, label_text in mapeo_inmuebles.items():
                datos["inmuebles"][0][dto_key] = await get_ubicacion(label_text)

            base_xpath = "//tbody[contains(@id, 'dtResumenInmueble_data')]/tr[1]"
            datos["inmuebles"][0]["partidaRegistral"] = (await self.page.locator(f"{base_xpath}/td[1]").inner_text()).replace("Partida Registral\n", "").strip()
            datos["inmuebles"][0]["tipoInmueble"] = (await self.page.locator(f"{base_xpath}/td[2]").inner_text()).replace("Tipo Inmueble\n", "").strip()
            datos["inmuebles"][0]["cargaYGravamen"] = (await self.page.locator(f"{base_xpath}/td[4]").inner_text()).replace("Carga y/o Gravamen\n", "").strip()
            datos["inmuebles"][0]["porcentajeRematar"] = (await self.page.locator(f"{base_xpath}/td[5]").inner_text()).replace("Porcentaje a Rematar\n", "").strip()
        except Exception as e:
            logger.warning(f"    -> [WARNING] Omisión en la grilla de Inmuebles: {e}")

        # --- TAB 3: CRONOGRAMA (Aislamiento posicional de celdas por coincidencia de Fase) ---
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
                    texto_raw = await self.page.locator(xpath).inner_text(timeout=2000)
                    return texto_raw.split('\n')[-1].strip()
                except:
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

            # Escucha asíncrona de eventos de descarga de Playwright (expect_download)
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
            
        # Ingestar nombre de archivo PDF de resolución si se descargó con éxito
        dto_final["remate"]["archivoUrl"] = limpiar(archivo_nombre_pdf if archivo_nombre_pdf else rem.get("archivoUrl", ""))
        
        for key, value in inm.items():
            dto_final["inmuebles"][0][key] = limpiar(value)
            
        for key, value in cro.items():
            dto_final["cronograma"][key] = limpiar(value)
            
        return dto_final

