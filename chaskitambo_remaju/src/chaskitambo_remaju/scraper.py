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
        history_path: str | Path = BASE_DIR / "historial_procesados.json",
        config_path: str | Path = BASE_DIR / "config.json",
        headless: bool = False,
        executable_path: str = r"D:\libs\navegadores\chrome-win64\chrome.exe",
    ):
        # CORREGIDO: Eliminamos self.creds_path dado que ahora se autogestiona por variables de entorno (.env)
        self.history_path = Path(history_path)
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

        # CORREGIDO: Para evitar fugas de memoria si el consumidor corta el AsyncGenerator,
        # se inicializa el gestor de Playwright en un contexto de control absoluto.
        async with async_playwright() as p:
            launch_kwargs = {"headless": self.headless}
            
            if os.path.isfile(self.executable_path):
                launch_kwargs["executable_path"] = self.executable_path
                logger.info(" -> [REMAJU-PLUGIN] Usando navegador local en: %s", self.executable_path)
            else:
                logger.warning(
                    " -> [REMAJU-PLUGIN] No se encontró navegador en %s. Playwright usará sus binarios internos.",
                    self.executable_path
                )

            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                accept_downloads=True,
            )
            page = await context.new_page()

            try:
                # CORREGIDO: Adaptación de la llamada removiendo 'creds_path' conforme a la nueva firma de auth.py
                authenticator = RemajuAuthenticator(page, captcha_builder)
                if not await authenticator.execute_login():
                    logger.error(" -> [REMAJU-PLUGIN] Falló la autenticación. Abortando.")
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

                    # CORREGIDO: En lugar de iterar por índices estáticos expuestos a Stale Element,
                    # evaluamos la longitud en tiempo de ejecución de forma dinámica en cada vuelta.
                    tarjetas_procesadas_en_pagina = 0
                    
                    while True:
                        await extractor.esperar_sincronizacion_primefaces()
                        await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                        
                        num_tarjetas = await page.locator("div.card.azul").count()
                        if tarjetas_procesadas_en_pagina >= num_tarjetas:
                            break  # Terminamos las tarjetas visibles de esta página actual

                        tarjeta_actual = page.locator("div.card.azul").nth(tarjetas_procesadas_en_pagina)
                        btn_detalle = tarjeta_actual.locator("button:has-text('Detalle')").first

                        if await btn_detalle.count() == 0:
                            tarjetas_procesadas_en_pagina += 1
                            continue

                        raw_title = (await tarjeta_actual.locator(".label-danger, .h6").first.inner_text()).strip()

                        if "REMATE N°" not in raw_title or " - " not in raw_title:
                            tarjetas_procesadas_en_pagina += 1
                            continue

                        parts = raw_title.split(" - ", 1)
                        numero_expediente, numero_convocatoria = parts[0].strip(), parts[1].strip()

                        if history_manager.is_processed(numero_expediente, numero_convocatoria):
                            logger.info(" -> [HISTORIAL] Saltando expediente ya procesado: %s", numero_expediente)
                            tarjetas_procesadas_en_pagina += 1
                            continue

                        en_detalle = False
                        try:
                            await btn_detalle.click(force=True)
                            await page.wait_for_selector(
                                "button:has-text('Regresar'), a:has-text('Regresar')",
                                state="visible",
                                timeout=15000,
                            )
                            await extractor.esperar_sincronizacion_primefaces()
                            en_detalle = True

                            # Evaluación de Cortocircuito por materia de alimentos
                            xpath_materia = (
                                "//div[contains(@class, 'ui-g')]"
                                "[div[contains(text(), 'Materia')]]"
                                "/div[contains(@class, 'text-justify') or contains(@class, 'ui-panelgrid-cell')]"
                                "[last()]"
                            )
                            materia_text = ""
                            try:
                                materia_text = (await page.locator(xpath_materia).first.inner_text(timeout=3000)).strip()
                            except Exception:
                                pass

                            materia_norm = " ".join(materia_text.lower().split())
                            if "alimentos" in materia_norm:
                                logger.info(" -> Expediente descartado por alimentos: %s", numero_expediente)
                                # CORREGIDO: No podemos hacer 'continue' libre sin antes regresar la UI a la bandeja
                                tarjetas_procesadas_en_pagina += 1
                                continue

                            detalle_extraido = await extractor.extract_tab_remate_completo()
                            nombre_pdf = await extractor.download_resolucion_pdf(
                                numero_expediente, str(ruta_local_descargas)
                            )

                            pdf_bytes = b""
                            if nombre_pdf:
                                ruta_pdf = ruta_local_descargas / nombre_pdf
                                if ruta_pdf.is_file():
                                    pdf_bytes = await asyncio.to_thread(ruta_pdf.read_bytes)

                            dto_mapeado = extractor.adaptar_a_dto(detalle_extraido, nombre_pdf)

                            documento = ChaskiDocument(
                                id_externo=numero_expediente,
                                fuente="remaju",
                                metadatos={
                                    "convocatoria": numero_convocatoria,
                                    "detalle": dto_mapeado,
                                },
                                pdf_bytes=pdf_bytes,
                                nombre_archivo_sugerido=nombre_pdf or f"resolucion_{numero_expediente}.pdf",
                            )

                            yield documento
                            history_manager.save_processed(numero_expediente, numero_convocatoria)
                            tarjetas_procesadas_en_pagina += 1

                        except Exception:
                            logger.exception(" -> Error procesando tarjeta %s", numero_expediente)
                            tarjetas_procesadas_en_pagina += 1
                        finally:
                            if en_detalle:
                                try:
                                    btn_regresar = page.locator(
                                        "button:has-text('Regresar'), a:has-text('Regresar')"
                                    ).first
                                    if await btn_regresar.count() > 0:
                                        await btn_regresar.click(force=True)
                                        await page.wait_for_selector(
                                            "div.card.azul", state="visible", timeout=15000
                                        )
                                        await extractor.esperar_sincronizacion_primefaces()
                                except Exception:
                                    logger.exception(" -> Error retornando a la bandeja general.")

                    # Paginación general de bandeja
                    btn_siguiente = page.locator("a.ui-paginator-next:not(.ui-state-disabled)").first
                    if await btn_siguiente.count() == 0 or not await btn_siguiente.is_visible():
                        logger.info(" -> [REMAJU-PLUGIN] Se alcanzó el final de la paginación.")
                        break

                    pagina_num += 1
                    await btn_siguiente.click(force=True)
                    await extractor.esperar_sincronizacion_primefaces()

            finally:
                # CORREGIDO: Uso explícito de close() en lugar de await page.wait_for_load_state
                # para asegurar el cierre inmediato y la liberación de recursos.
                logger.info(" -> [REMAJU-PLUGIN] Cerrando flujos y liberando controladores de Playwright...")
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()
