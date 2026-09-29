# D:\libs\chaskitambo_plugins\chaskitambo_remaju\src\chaskitambo_remaju\scraper.py
import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from playwright.async_api import async_playwright
from chaskitambo import BaseScraper, ChaskiDocument

from .auth import RemajuAuthenticator
from .extractor import RemajuExtractorScraper
from .history import RemajuHistoryManager
from .ocr import CaptchaResolver
from .search import RemajuSearchScraper

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent

class RemajuScraper(BaseScraper):
    def __init__(
        self,
        history_path: str | Path = None, # Heredará la ruta unificada absoluta por defecto
        config_path: str | Path = BASE_DIR / "config.json",
        headless: bool = False,
        executable_path: str = r"D:\libs\navegadores\chrome-win64\chrome.exe",
    ):
        self.history_path = history_path
        self.config_path = Path(config_path)
        self.headless = headless
        self.executable_path = executable_path

    async def extract(self) -> AsyncGenerator[ChaskiDocument, None]:
        logger.info(" -> [REMAJU-PLUGIN] Iniciando ejecución autónoma...")

        history_manager = RemajuHistoryManager(self.history_path)
        captcha_builder = CaptchaResolver()
        tipo_inmueble_filtro = "1"
        ruta_local_descargas = Path("./descargas_resoluciones")
        ruta_local_descargas.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            launch_kwargs = {"headless": self.headless}
            if os.path.isfile(self.executable_path):
                launch_kwargs["executable_path"] = self.executable_path
            
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(viewport={"width": 1280, "height": 720}, accept_downloads=True)
            page = await context.new_page()

            try:
                authenticator = RemajuAuthenticator(page, captcha_builder)
                if not await authenticator.execute_login():
                    return

                search_scraper = RemajuSearchScraper(page, history_manager=history_manager)
                await search_scraper.navigate_to_search_module()
                await search_scraper.apply_search_filters(tipo_inmueble_filtro)

                extractor = RemajuExtractorScraper(page, config_path=self.config_path)
                pagina_num = 1

                while True:
                    logger.info(" -> [REMAJU-PLUGIN] Procesando página #%s...", pagina_num)
                    await extractor.esperar_sincronizacion_primefaces()
                    await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)

                    tarjetas_procesadas_en_pagina = 0
                    while True:
                        await extractor.esperar_sincronizacion_primefaces()
                        await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                        
                        num_tarjetas = await page.locator("div.card.azul").count()
                        if tarjetas_procesadas_en_pagina >= num_tarjetas:
                            break

                        tarjeta_actual = page.locator("div.card.azul").nth(tarjetas_procesadas_en_pagina)
                        btn_detalle = tarjeta_actual.locator("button:has-text('Detail'), button:has-text('Detalle')").first

                        if await btn_detalle.count() == 0:
                            tarjetas_procesadas_en_pagina += 1
                            continue

                        raw_title = (await tarjeta_actual.locator(".label-danger, .h6").first.inner_text()).strip()
                        if "REMATE N°" not in raw_title or " - " not in raw_title:
                            tarjetas_procesadas_en_pagina += 1
                            continue

                        parts = raw_title.split(" - ", 1)
                        identificador_tarjeta, numero_convocatoria = parts[0].strip(), parts[1].strip()

                        # Control perimetral preventivo rápido
                        if history_manager.is_processed(identificador_tarjeta, numero_convocatoria):
                            logger.info(" -> [HISTORIAL] Saltando tarjeta ya procesada: %s", identificador_tarjeta)
                            try:
                                btn_regresar = page.locator("button:has-text('Regresar'), a:has-text('Regresar')").first
                                await btn_regresar.click(force=True)
                                await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                                await extractor.esperar_sincronizacion_primefaces()
                            except Exception:
                                logger.error("Fallo al regresar a la bandeja desde el cortocircuito interno de historial.")
                            
                            tarjetas_procesadas_en_pagina += 1
                            continue

                        en_detalle = False
                        try:
                            await btn_detalle.click(force=True)
                            await page.wait_for_selector("button:has-text('Regresar'), a:has-text('Regresar')", state="visible", timeout=15000)
                            await extractor.esperar_sincronizacion_primefaces()
                            en_detalle = True

                            # Cortocircuito Alimentos
                            xpath_materia = "//div[contains(@class, 'ui-g')][div[contains(text(), 'Materia')]]/div[last()]"
                            materia_text = ""
                            try:
                                materia_text = (await page.locator(xpath_materia).first.inner_text(timeout=3000)).strip()
                            except:
                                pass

                            if "alimentos" in " ".join(materia_text.lower().split()):
                                logger.info(" -> Tarjeta descartada por alimentos.")
                                tarjetas_procesadas_en_pagina += 1
                                continue

                            # Extracción de la ficha detallada
                            detalle_extraido = await extractor.extract_tab_remate_completo()
                            
                            # 🎯 CORREGIDO: Extraemos el identificador de 27 caracteres oficial del Formulario Interno
                            expediente_real_judicial = detalle_extraido.get("remate", {}).get("expediente", "").strip()
                            convocatoria_real_judicial = detalle_extraido.get("remate", {}).get("convocatoria", "").strip() or numero_convocatoria

                            if not expediente_real_judicial:
                                expediente_real_judicial = identificador_tarjeta

                            # Doble control de seguridad contra el expediente real rehidratado
                            if history_manager.is_processed(expediente_real_judicial, convocatoria_real_judicial):
                                logger.info(" -> [HISTORIAL] Saltando ID Judicial ya procesado: %s", expediente_real_judicial)
                                tarjetas_procesadas_en_pagina += 1
                                continue

                            nombre_pdf = await extractor.download_resolucion_pdf(expediente_real_judicial, str(ruta_local_descargas))

                            pdf_bytes = b""
                            if nombre_pdf:
                                ruta_pdf = ruta_local_descargas / nombre_pdf
                                if ruta_pdf.is_file():
                                    pdf_bytes = await asyncio.to_thread(ruta_pdf.read_bytes)

                            # Sincronizamos los datos forzando el formato limpio
                            detalle_extraido["remate"]["expediente"] = expediente_real_judicial
                            detalle_extraido["remate"]["convocatoria"] = convocatoria_real_judicial
                            dto_mapeado = extractor.adaptar_a_dto(detalle_extraido, nombre_pdf)

                            documento = ChaskiDocument(
                                id_externo=expediente_real_judicial,
                                fuente="remaju",
                                metadatos={"convocatoria": convocatoria_real_judicial, "detalle": dto_mapeado},
                                pdf_bytes=pdf_bytes,
                                nombre_archivo_sugerido=nombre_pdf or f"resolucion_{expediente_real_judicial}.pdf",
                            )

                            yield documento
                            history_manager.save_processed(expediente_real_judicial, convocatoria_real_judicial)
                            tarjetas_procesadas_en_pagina += 1

                        except Exception:
                            logger.exception(" -> Error procesando tarjeta")
                            tarjetas_procesadas_en_pagina += 1
                        finally:
                            if en_detalle:
                                try:
                                    btn_regresar = page.locator("button:has-text('Regresar'), a:has-text('Regresar')").first
                                    await btn_regresar.click(force=True)
                                    await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                                    await extractor.esperar_sincronizacion_primefaces()
                                except Exception:
                                    logger.exception(" -> Error retornando a la bandeja general.")

                    btn_siguiente = page.locator("a.ui-paginator-next:not(.ui-state-disabled)").first
                    if await btn_siguiente.count() == 0 or not await btn_siguiente.is_visible():
                        break

                    pagina_num += 1
                    await btn_siguiente.click(force=True)
                    await extractor.esperar_sincronizacion_primefaces()

            finally:
                logger.info(" -> [REMAJU-PLUGIN] Liberando controladores de Playwright...")
                await page.close()
                await context.close()
                await browser.close()
